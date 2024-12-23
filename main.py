import os
import json
import logging
from typing import List, Dict, Any, Tuple
from datetime import datetime
from dataclasses import dataclass
import tempfile
from pathlib import Path
import asyncio
from io import BytesIO
import aiohttp
from PIL import Image, ImageDraw, ImageFont
import textwrap

from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from hypercorn.config import Config as HyperConfig
from hypercorn.asyncio import serve as hypercorn_serve
from asgiref.wsgi import WsgiToAsgi

# Configuration
class Config:
    RATE_LIMIT = os.getenv('RATE_LIMIT', '100 per hour')
    MAX_MESSAGES = int(os.getenv('MAX_MESSAGES', 50))
    MAX_MESSAGE_LENGTH = int(os.getenv('MAX_MESSAGE_LENGTH', 2000))
    ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', '*').split(',')
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    ENV = os.getenv('FLASK_ENV', 'production')
    SECRET_KEY = os.getenv('SECRET_KEY', os.urandom(24))
    
    # Image generation config
    FONT_SIZE = 14
    USERNAME_FONT_SIZE = 16
    TIMESTAMP_FONT_SIZE = 12
    MESSAGE_PADDING = 20
    AVATAR_SIZE = 40
    MESSAGE_SPACING = 16
    MAX_WIDTH = 800
    BACKGROUND_COLOR = (32, 34, 37)  # Discord dark theme
    TEXT_COLOR = (220, 221, 222)     # Discord message text color
    TIMESTAMP_COLOR = (114, 118, 125) # Discord timestamp color

# Set up logging
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
            
    def get_color_rgb(self) -> Tuple[int, int, int]:
        color = self.color.lstrip('#')
        return tuple(int(color[i:i+2], 16) for i in (0, 2, 4))

class ImageGenerator:
    def __init__(self):
        # Load fonts
        self.font_path = os.path.join(os.path.dirname(__file__), 'fonts', 'Roboto-Regular.ttf')
        self.font_bold_path = os.path.join(os.path.dirname(__file__), 'fonts', 'Roboto-Bold.ttf')
        
        # Create fonts directory if it doesn't exist
        os.makedirs(os.path.dirname(self.font_path), exist_ok=True)
        
        # Download fonts if they don't exist
        if not os.path.exists(self.font_path):
            self._download_fonts()
            
        self.font = ImageFont.truetype(self.font_path, Config.FONT_SIZE)
        self.username_font = ImageFont.truetype(self.font_bold_path, Config.USERNAME_FONT_SIZE)
        self.timestamp_font = ImageFont.truetype(self.font_path, Config.TIMESTAMP_FONT_SIZE)
        
        # Create default avatar
        self.default_avatar = self._create_default_avatar()
        
    def _create_default_avatar(self) -> Image.Image:
        """Create a default avatar image"""
        avatar = Image.new('RGB', (Config.AVATAR_SIZE, Config.AVATAR_SIZE), (102, 102, 102))
        return avatar
        
    async def _download_fonts(self):
        """Download required fonts"""
        async with aiohttp.ClientSession() as session:
            # Download Roboto Regular
            async with session.get('https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Regular.ttf') as resp:
                with open(self.font_path, 'wb') as f:
                    f.write(await resp.read())
                    
            # Download Roboto Bold
            async with session.get('https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Bold.ttf') as resp:
                with open(self.font_bold_path, 'wb') as f:
                    f.write(await resp.read())
    
    async def _get_avatar(self, avatar_url: str) -> Image.Image:
        """Fetch and process avatar image"""
        if not avatar_url:
            return self.default_avatar
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(avatar_url) as response:
                    if response.status == 200:
                        data = await response.read()
                        avatar = Image.open(BytesIO(data))
                        avatar = avatar.convert('RGB')
                        avatar = avatar.resize((Config.AVATAR_SIZE, Config.AVATAR_SIZE), Image.Resampling.LANCZOS)
                        return avatar
                    else:
                        return self.default_avatar
        except Exception as e:
            logger.error(f"Error fetching avatar: {str(e)}")
            return self.default_avatar
            
    def _wrap_text(self, text: str, draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
        """Wrap text to fit within maximum width"""
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            width = draw.textlength(test_line, font=font)
            
            if width <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
                
        if current_line:
            lines.append(' '.join(current_line))
            
        return lines
        
    async def generate(self, messages: List[Message]) -> bytes:
        """Generate image from messages"""
        try:
            # Calculate total height needed
            total_height = Config.MESSAGE_PADDING
            message_heights = []
            
            # Create a temporary image for text measurements
            temp_img = Image.new('RGB', (1, 1))
            draw = ImageDraw.Draw(temp_img)
            
            for message in messages:
                # Calculate wrapped text height
                wrapped_lines = self._wrap_text(
                    message.message, 
                    draw, 
                    self.font,
                    Config.MAX_WIDTH - Config.MESSAGE_PADDING * 2 - Config.AVATAR_SIZE - Config.MESSAGE_SPACING
                )
                
                message_height = (
                    Config.USERNAME_FONT_SIZE +  # Username height
                    len(wrapped_lines) * (Config.FONT_SIZE + 4) +  # Message text height
                    Config.MESSAGE_SPACING  # Spacing
                )
                
                message_heights.append(message_height)
                total_height += message_height
                
            # Create final image
            img = Image.new('RGB', (Config.MAX_WIDTH, total_height), Config.BACKGROUND_COLOR)
            draw = ImageDraw.Draw(img)
            
            # Current Y position for drawing
            current_y = Config.MESSAGE_PADDING
            
            # Draw messages
            for i, message in enumerate(messages):
                # Get avatar
                avatar = await self._get_avatar(message.avatar_url)
                
                # Paste avatar
                img.paste(avatar, (Config.MESSAGE_PADDING, current_y))
                
                # Draw username
                username_x = Config.MESSAGE_PADDING + Config.AVATAR_SIZE + Config.MESSAGE_SPACING
                draw.text(
                    (username_x, current_y),
                    message.username,
                    font=self.username_font,
                    fill=message.get_color_rgb()
                )
                
                # Draw timestamp
                timestamp_width = draw.textlength(message.timestamp, font=self.timestamp_font)
                draw.text(
                    (username_x + draw.textlength(message.username, font=self.username_font) + 10, current_y + 4),
                    message.timestamp,
                    font=self.timestamp_font,
                    fill=Config.TIMESTAMP_COLOR
                )
                
                # Draw message text
                wrapped_lines = self._wrap_text(
                    message.message,
                    draw,
                    self.font,
                    Config.MAX_WIDTH - Config.MESSAGE_PADDING * 2 - Config.AVATAR_SIZE - Config.MESSAGE_SPACING
                )
                
                text_y = current_y + Config.USERNAME_FONT_SIZE + 4
                for line in wrapped_lines:
                    draw.text(
                        (username_x, text_y),
                        line,
                        font=self.font,
                        fill=Config.TEXT_COLOR
                    )
                    text_y += Config.FONT_SIZE + 4
                
                current_y += message_heights[i]
            
            # Convert to bytes
            img_byte_arr = BytesIO()
            img.save(img_byte_arr, format='PNG', optimize=True)
            img_byte_arr.seek(0)
            
            return img_byte_arr.getvalue()
            
        except Exception as e:
            logger.error(f"Error generating image: {str(e)}", exc_info=True)
            raise

def create_app():
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
    
    # Create image generator instance
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
            return jsonify({'error': 'Failed to generate image', 'details': str(e)}), 500
            
    return app

async def run_app():
    app = create_app()
    asgi_app = WsgiToAsgi(app)
    config = HyperConfig()
    config.bind = [f"0.0.0.0:{int(os.environ.get('PORT', 8080))}"]
    await hypercorn_serve(asgi_app, config)

if __name__ == '__main__':
    asyncio.run(run_app())
