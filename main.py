import os
import json
import logging
from typing import List, Dict, Any
from datetime import datetime
from dataclasses import dataclass
import tempfile
from pathlib import Path
import gunicorn

from flask import Flask, request, send_file, jsonify, render_template_string
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException
from io import BytesIO
from waitress import serve

# Configuration
class Config:
    RATE_LIMIT = os.getenv('RATE_LIMIT', '100 per hour')
    MAX_MESSAGES = int(os.getenv('MAX_MESSAGES', 50))
    MAX_MESSAGE_LENGTH = int(os.getenv('MAX_MESSAGE_LENGTH', 2000))
    ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', '*').split(',')
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    ENV = os.getenv('FLASK_ENV', 'production')
    SECRET_KEY = os.getenv('SECRET_KEY', os.urandom(24))

# Set up logging
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Message validation class
@dataclass
class Message:
    username: str
    message: str
    color: str
    timestamp: str
    avatar_url: str = ""

    def validate(self) -> None:
        if len(self.message) > Config.MAX_MESSAGE_LENGTH:
            raise ValueError(f"Message exceeds maximum length of {Config.MAX_MESSAGE_LENGTH}")
        if not self.username:
            raise ValueError("Username cannot be empty")
        if not self.color.startswith('#'):
            self.color = f"#{self.color}"

# HTML Templates
HTML_BASE = """
<!DOCTYPE html>
<html>
<head>
<style>
body {
    background: #1a1a1a;
    font-family: Arial, sans-serif;
    color: #fff;
    padding: 20px;
    margin: 0;
    width: fit-content;
}
.message-container {
    margin-bottom: 20px;
    display: flex;
    align-items: flex-start;
    gap: 10px;
}
.avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background-size: cover;
    background-position: center;
    flex-shrink: 0;
}
.message-content {
    flex-grow: 1;
    max-width: 800px;
    word-wrap: break-word;
}
.username {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
}
.username-text {
    font-size: 1rem;
    font-weight: 500;
}
.timestamp {
    color: #999;
    font-size: 0.75rem;
}
.message-text {
    color: #dcddde;
    font-size: 0.9rem;
    line-height: 1.4;
}
</style>
</head>
<body>
{message_containers}
</body>
</html>
"""

MESSAGE_TEMPLATE = """
<div class="message-container">
    <div class="avatar" style="background-image: url('{avatar_url}')"></div>
    <div class="message-content">
        <div class="username">
            <span class="username-text" style="color: {color}">{username}</span>
            <span class="timestamp">{timestamp}</span>
        </div>
        <div class="message-text">{message}</div>
    </div>
</div>
"""

WELCOME_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Discord Message Image Generator API</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            line-height: 1.6;
        }
        code {
            background: #f4f4f4;
            padding: 2px 5px;
            border-radius: 3px;
        }
        pre {
            background: #f4f4f4;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }
    </style>
</head>
<body>
    <h1>Discord Message Image Generator API</h1>
    <p>Welcome to the Discord Message Image Generator API. Use this service to generate Discord-style message images.</p>
    
    <h2>Endpoints:</h2>
    <ul>
        <li><code>GET /</code> - This documentation page</li>
        <li><code>GET /health</code> - Health check endpoint</li>
        <li><code>POST /generate</code> - Generate Discord message image</li>
    </ul>

    <h2>Example Usage:</h2>
    <pre>
POST /generate
Content-Type: application/json

{
    "messages": [
        {
            "username": "User1",
            "message": "Hello, Discord!",
            "color": "#7289DA",
            "timestamp": "2024-12-24 12:00",
            "avatar_url": "https://example.com/avatar.png"
        }
    ]
}
    </pre>
</body>
</html>
"""

class ImageGenerator:
    def __init__(self):
        self.chrome_options = self._setup_chrome_options()
        
    @staticmethod
    def _setup_chrome_options() -> Options:
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        return options

    def generate(self, messages: List[Message]) -> bytes:
        message_containers = ""
        for msg in messages:
            message_containers += MESSAGE_TEMPLATE.format(
                avatar_url=msg.avatar_url or "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23666'/%3E%3C/svg%3E",
                color=msg.color,
                username=msg.username,
                timestamp=msg.timestamp,
                message=msg.message
            )
        
        html_content = HTML_BASE.format(message_containers=message_containers)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
            f.write(html_content)
            temp_path = f.name
        
        try:
            driver = webdriver.Chrome(options=self.chrome_options)
            driver.get(f'file://{temp_path}')
            
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(('tag name', 'body'))
            )
            
            body = driver.find_element('tag name', 'body')
            screenshot = body.screenshot_as_png
            
            return screenshot
        except WebDriverException as e:
            logger.error(f"WebDriver error: {str(e)}")
            raise
        finally:
            driver.quit()
            os.unlink(temp_path)

# Initialize Flask app
app = Flask(__name__)
app.config['ENV'] = Config.ENV
app.config['SECRET_KEY'] = Config.SECRET_KEY
CORS(app, origins=Config.ALLOWED_ORIGINS)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=[Config.RATE_LIMIT],
    storage_uri="memory://"
)

image_generator = ImageGenerator()

@app.errorhandler(Exception)
def handle_error(error):
    logger.error(f"Error occurred: {str(error)}", exc_info=True)
    return jsonify({
        'error': 'Internal server error',
        'message': str(error)
    }), 500

@app.route('/')
def index():
    return render_template_string(WELCOME_HTML)

@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    }), 200

@app.route('/generate', methods=['POST'])
@limiter.limit(Config.RATE_LIMIT)
def generate_image():
    try:
        data = request.get_json()
        if not data or 'messages' not in data:
            return jsonify({'error': 'Invalid request data'}), 400

        if len(data['messages']) > Config.MAX_MESSAGES:
            return jsonify({'error': f'Too many messages. Maximum allowed: {Config.MAX_MESSAGES}'}), 400

        messages = []
        for msg_data in data['messages']:
            try:
                message = Message(
                    username=msg_data['username'],
                    message=msg_data['message'],
                    color=msg_data.get('color', '#ffffff'),
                    timestamp=msg_data.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M')),
                    avatar_url=msg_data.get('avatar_url', '')
                )
                message.validate()
                messages.append(message)
            except (KeyError, ValueError) as e:
                return jsonify({'error': f'Invalid message data: {str(e)}'}), 400

        screenshot = image_generator.generate(messages)

        return send_file(
            BytesIO(screenshot),
            mimetype='image/png',
            as_attachment=True,
            download_name='discord_messages.png'
        )

    except Exception as e:
        logger.error(f"Error generating image: {str(e)}", exc_info=True)
        return jsonify({'error': 'Failed to generate image'}), 500

def create_app():
    return app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    if Config.ENV == 'production':
        serve(app, host='0.0.0.0', port=port)
    else:
        app.run(host='0.0.0.0', port=port, debug=True)
