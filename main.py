import os
import json
import logging
from typing import List, Dict, Any
from datetime import datetime
from dataclasses import dataclass
import tempfile
from pathlib import Path
import asyncio
from playwright.async_api import async_playwright
from io import BytesIO

from flask import Flask, request, send_file, jsonify, render_template_string
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
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
<meta charset="UTF-8">
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
    white-space: pre-wrap;
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

class ImageGenerator:
    def __init__(self):
        self.playwright = None
        self.browser = None
        
    async def initialize(self):
        if not self.playwright:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.firefox.launch()

    async def cleanup(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def generate(self, messages: List[Message]) -> bytes:
        await self.initialize()
        
        message_containers = ""
        for msg in messages:
            safe_message = msg.message.replace('"', '&quot;').replace("'", "&#39;")
            message_containers += MESSAGE_TEMPLATE.format(
                avatar_url=msg.avatar_url or "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23666'/%3E%3C/svg%3E",
                color=msg.color,
                username=msg.username,
                timestamp=msg.timestamp,
                message=safe_message
            )
        
        html_content = HTML_BASE.format(message_containers=message_containers)
        
        async with self.browser.new_context(viewport={'width': 1920, 'height': 1080}) as context:
            page = await context.new_page()
            await page.set_content(html_content)
            
            # Wait for any images to load
            await page.wait_for_load_state('networkidle')
            
            # Get the body element and its dimensions
            body = await page.query_selector('body')
            box = await body.bounding_box()
            
            # Take screenshot of the body element
            screenshot = await body.screenshot(type='png')
            return screenshot

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

# Create a single ImageGenerator instance
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
    return jsonify({
        'status': 'ok',
        'endpoints': {
            '/': 'API information',
            '/health': 'Health check endpoint',
            '/generate': 'Generate Discord-style message images (POST)'
        }
    })

@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    }), 200

@app.route('/generate', methods=['POST'])
@limiter.limit(Config.RATE_LIMIT)
async def generate_image():
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

        screenshot = await image_generator.generate(messages)

        return send_file(
            BytesIO(screenshot),
            mimetype='image/png',
            as_attachment=True,
            download_name='discord_messages.png'
        )

    except Exception as e:
        logger.error(f"Error generating image: {str(e)}", exc_info=True)
        return jsonify({'error': 'Failed to generate image'}), 500

@app.before_first_request
async def setup_image_generator():
    await image_generator.initialize()

@app.teardown_appcontext
async def cleanup_image_generator(exception):
    await image_generator.cleanup()

def create_app():
    return app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    if Config.ENV == 'production':
        serve(app, host='0.0.0.0', port=port)
    else:
        app.run(host='0.0.0.0', port=port, debug=True)
