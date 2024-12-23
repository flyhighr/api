import os
import json
import logging
from typing import List, Dict, Any
from datetime import datetime
from dataclasses import dataclass
from io import BytesIO
import requests
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

class Config:
    RATE_LIMIT = os.getenv('RATE_LIMIT', '100 per hour')
    MAX_MESSAGES = int(os.getenv('MAX_MESSAGES', 50))
    MAX_MESSAGE_LENGTH = int(os.getenv('MAX_MESSAGE_LENGTH', 2000))
    ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', '*').split(',')
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    # Styling configurations
    FONT_SIZE = 16
    USERNAME_FONT_SIZE = 16
    TIMESTAMP_FONT_SIZE = 12
    PADDING = 16
    MESSAGE_SPACING = 8
    AVATAR_SIZE = 40
    MAX_WIDTH = 800
    BACKGROUND_COLOR = '#36393f'
    DEFAULT_TEXT_COLOR = '#dcddde'
    TIMESTAMP_COLOR = '#a3a6aa'
    USERNAME_SPACING = 8
    MESSAGE_TOP_PADDING = 2
    LINE_SPACING = 4

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

class ImageGenerator:
    def __init__(self):
        try:
            self.font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", Config.FONT_SIZE)
            self.username_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", Config.USERNAME_FONT_SIZE)
            self.timestamp_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", Config.TIMESTAMP_FONT_SIZE)
        except OSError:
            logger.warning("DejaVu Sans fonts not found, using default font")
            self.font = ImageFont.load_default()
            self.username_font = ImageFont.load_default()
            self.timestamp_font = ImageFont.load_default()

    def _get_avatar(self, avatar_url: str) -> Image.Image:
        try:
            if not avatar_url:
                avatar = Image.new('RGB', (Config.AVATAR_SIZE, Config.AVATAR_SIZE), '#7289da')
                draw = ImageDraw.Draw(avatar)
                draw.ellipse((0, 0, Config.AVATAR_SIZE, Config.AVATAR_SIZE), fill='#7289da')
                return avatar

            response = requests.get(avatar_url, timeout=5)
            avatar = Image.open(BytesIO(response.content))
            avatar = avatar.convert('RGBA')
            
            # Ensure square aspect ratio
            size = min(avatar.size)
            left = (avatar.width - size) // 2
            top = (avatar.height - size) // 2
            avatar = avatar.crop((left, top, left + size, top + size))
            
            # Resize to desired size
            avatar = avatar.resize((Config.AVATAR_SIZE, Config.AVATAR_SIZE), Image.Resampling.LANCZOS)
            
            # Create circular mask
            mask = Image.new('L', (Config.AVATAR_SIZE, Config.AVATAR_SIZE), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, Config.AVATAR_SIZE, Config.AVATAR_SIZE), fill=255)
            
            # Apply mask
            output = Image.new('RGBA', (Config.AVATAR_SIZE, Config.AVATAR_SIZE), (0, 0, 0, 0))
            output.paste(avatar, (0, 0))
            output.putalpha(mask)
            
            return output
        except Exception as e:
            logger.error(f"Error fetching avatar: {str(e)}")
            return Image.new('RGB', (Config.AVATAR_SIZE, Config.AVATAR_SIZE), '#7289da')

    def _wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            # Handle newlines in messages
            if '\n' in word:
                subwords = word.split('\n')
                for i, subword in enumerate(subwords):
                    if subword:
                        current_line.append(subword)
                        if i < len(subwords) - 1:
                            lines.append(' '.join(current_line))
                            current_line = []
                continue
                
            current_line.append(word)
            line_width = font.getlength(' '.join(current_line))
            if line_width > max_width:
                if len(current_line) == 1:
                    lines.append(current_line[0])
                    current_line = []
                else:
                    current_line.pop()
                    lines.append(' '.join(current_line))
                    current_line = [word]
        
        if current_line:
            lines.append(' '.join(current_line))
        return lines

    def generate(self, messages: List[Message]) -> bytes:
        # Calculate dimensions
        total_height = Config.PADDING
        message_heights = []
        
        for msg in messages:
            wrapped_text = self._wrap_text(
                msg.message,
                self.font,
                Config.MAX_WIDTH - Config.AVATAR_SIZE - Config.PADDING * 3
            )
            
            # Calculate message block height
            text_height = len(wrapped_text) * (self.font.size + Config.LINE_SPACING)
            header_height = max(Config.USERNAME_FONT_SIZE, Config.TIMESTAMP_FONT_SIZE)
            height = header_height + Config.MESSAGE_TOP_PADDING + text_height
            
            message_heights.append(height)
            total_height += height + Config.MESSAGE_SPACING

        total_height += Config.PADDING - Config.MESSAGE_SPACING

        # Create image
        img = Image.new('RGB', (Config.MAX_WIDTH, total_height), Config.BACKGROUND_COLOR)
        draw = ImageDraw.Draw(img)
        
        current_y = Config.PADDING
        
        for msg, height in zip(messages, message_heights):
            # Draw avatar
            avatar = self._get_avatar(msg.avatar_url)
            img.paste(avatar, (Config.PADDING, current_y), avatar if avatar.mode == 'RGBA' else None)
            
            # Draw username
            content_x = Config.PADDING * 2 + Config.AVATAR_SIZE
            username_width = self.username_font.getlength(msg.username)
            draw.text(
                (content_x, current_y),
                msg.username,
                font=self.username_font,
                fill=msg.color
            )
            
            # Draw timestamp
            timestamp_x = content_x + username_width + Config.USERNAME_SPACING
            draw.text(
                (timestamp_x, current_y + 2),
                msg.timestamp,
                font=self.timestamp_font,
                fill=Config.TIMESTAMP_COLOR
            )
            
            # Draw message
            wrapped_text = self._wrap_text(
                msg.message,
                self.font,
                Config.MAX_WIDTH - content_x - Config.PADDING
            )
            
            text_y = current_y + Config.USERNAME_FONT_SIZE + Config.MESSAGE_TOP_PADDING
            
            for line in wrapped_text:
                draw.text(
                    (content_x, text_y),
                    line,
                    font=self.font,
                    fill=Config.DEFAULT_TEXT_COLOR
                )
                text_y += self.font.size + Config.LINE_SPACING
            
            current_y += height + Config.MESSAGE_SPACING

        # Convert to PNG with optimization
        output = BytesIO()
        img.save(output, format='PNG', optimize=True)
        output.seek(0)
        return output.getvalue()

# Initialize Flask app
app = Flask(__name__)
CORS(app, origins=Config.ALLOWED_ORIGINS)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=[Config.RATE_LIMIT]
)

image_generator = ImageGenerator()

@app.route('/')
def index():
    return jsonify({
        'status': 'running',
        'version': '1.0.0',
        'endpoints': {
            '/': 'API documentation',
            '/health': 'Health check endpoint',
            '/generate': 'POST endpoint for generating Discord-style message images'
        }
    })

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy'}), 200

@app.route('/generate', methods=['POST'])
@limiter.limit(Config.RATE_LIMIT)
def generate_image():
    try:
        data = request.get_json()
        if not data or 'messages' not in data:
            return jsonify({'error': 'Invalid request data'}), 400

        if len(data['messages']) > Config.MAX_MESSAGES:
            return jsonify({
                'error': f'Too many messages. Maximum allowed: {Config.MAX_MESSAGES}'
            }), 400

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
