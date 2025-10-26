from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import os
import io
import requests
import base64
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# Configuration - Set these in Render environment variables
AZURE_SPEECH_KEY = os.getenv('AZURE_SPEECH_KEY')
AZURE_REGION = os.getenv('AZURE_REGION', 'eastus')

# Fallback to free service if Azure key not provided
USE_FREE_TTS = os.getenv('USE_FREE_TTS', 'false').lower() == 'true'

class TextToSpeechAPI:
    def __init__(self):
        self.azure_token = None
        self.token_expiry = None
    
    def get_azure_token(self):
        """Get Azure Cognitive Services token"""
        if not AZURE_SPEECH_KEY:
            raise Exception("Azure Speech Key not configured")
            
        if self.azure_token and self.token_expiry and datetime.now() < self.token_expiry:
            return self.azure_token
            
        url = f"https://{AZURE_REGION}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
        headers = {
            'Ocp-Apim-Subscription-Key': AZURE_SPEECH_KEY,
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            self.azure_token = response.text
            # Token expires in 10 minutes
            self.token_expiry = datetime.now() + timedelta(minutes=9)
            return self.azure_token
        else:
            raise Exception(f"Failed to get Azure token: {response.status_code}")
    
    def synthesize_speech_azure(self, text, voice="en-US-JennyNeural"):
        """Convert text to speech using Azure Cognitive Services"""
        try:
            token = self.get_azure_token()
            url = f"https://{AZURE_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
            
            ssml = f"""
            <speak version='1.0' xml:lang='en-US'>
                <voice xml:lang='en-US' xml:gender='Female' name='{voice}'>
                    {text}
                </voice>
            </speak>
            """
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/ssml+xml',
                'X-Microsoft-OutputFormat': 'audio-16khz-128kbitrate-mono-mp3',
                'User-Agent': 'TextToSpeechAPI'
            }
            
            response = requests.post(url, data=ssml, headers=headers)
            if response.status_code == 200:
                return response.content
            else:
                raise Exception(f"Azure API error: {response.status_code}")
                
        except Exception as e:
            raise Exception(f"Azure synthesis failed: {str(e)}")
    
    def synthesize_speech_free(self, text):
        """Free TTS using Google Translate TTS API"""
        try:
            # Google Translate TTS (free but limited)
            url = f"https://translate.google.com/translate_tts"
            params = {
                'ie': 'UTF-8',
                'q': text,
                'tl': 'en',
                'client': 'tw-ob'
            }
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, params=params, headers=headers)
            if response.status_code == 200:
                return response.content
            else:
                raise Exception(f"Free TTS error: {response.status_code}")
                
        except Exception as e:
            raise Exception(f"Free TTS failed: {str(e)}")

tts_api = TextToSpeechAPI()

@app.route('/')
def home():
    return jsonify({
        'message': 'Text-to-Speech API',
        'endpoints': {
            'GET /speech?text=hello': 'Generate speech from text',
            'POST /speech': 'Generate speech with JSON body',
            'GET /voices': 'List available voices',
            'GET /health': 'Health check'
        },
        'usage': 'Visit /speech?text=Your+text+here to get audio'
    })

@app.route('/speech', methods=['GET'])
def text_to_speech():
    """Endpoint: GET /speech?text=Your+text+here"""
    text = request.args.get('text', '')
    
    if not text:
        return jsonify({'error': 'No text provided. Use ?text=Your+message'}), 400
    
    if len(text) > 1000:
        return jsonify({'error': 'Text too long. Maximum 1000 characters.'}), 400
    
    try:
        # Choose service based on configuration
        if USE_FREE_TTS or not AZURE_SPEECH_KEY:
            audio_data = tts_api.synthesize_speech_free(text)
        else:
            audio_data = tts_api.synthesize_speech_azure(text)
        
        # Return as audio file
        return send_file(
            io.BytesIO(audio_data),
            mimetype='audio/mpeg',
            as_attachment=False,
            download_name='speech.mp3'
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/speech', methods=['POST'])
def text_to_speech_post():
    """Endpoint: POST /speech with JSON body"""
    data = request.get_json()
    
    if not data or 'text' not in data:
        return jsonify({'error': 'No text provided in JSON body'}), 400
    
    text = data['text']
    voice = data.get('voice', 'en-US-JennyNeural')
    
    try:
        if USE_FREE_TTS or not AZURE_SPEECH_KEY:
            audio_data = tts_api.synthesize_speech_free(text)
        else:
            audio_data = tts_api.synthesize_speech_azure(text, voice)
        
        # Return as base64 for flexibility
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
        
        return jsonify({
            'status': 'success',
            'text': text,
            'audio_format': 'mp3',
            'audio_data': audio_base64,
            'voice': voice if not USE_FREE_TTS else 'free-tts'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/voices', methods=['GET'])
def get_available_voices():
    """Get list of available voices (Azure only)"""
    if USE_FREE_TTS or not AZURE_SPEECH_KEY:
        return jsonify({
            'message': 'Using free TTS service - voice selection not available',
            'default_voice': 'free-tts'
        })
    
    try:
        token = tts_api.get_azure_token()
        url = f"https://{AZURE_REGION}.tts.speech.microsoft.com/cognitiveservices/voices/list"
        
        headers = {
            'Authorization': f'Bearer {token}'
        }
        
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            voices = response.json()
            # Filter English voices for simplicity
            english_voices = [v for v in voices if v['Locale'].startswith('en-')]
            return jsonify(english_voices[:10])  # Return first 10 English voices
        else:
            return jsonify({'error': 'Failed to fetch voices'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy', 
        'service': 'Text-to-Speech API',
        'using_free_tts': USE_FREE_TTS or not AZURE_SPEECH_KEY
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
