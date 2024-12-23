from flask import Flask, request, send_file
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import json
import os
from PIL import Image
from io import BytesIO

app = Flask(__name__)

HTML_TEMPLATE = """
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
}
.message-content {
    flex-grow: 1;
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

@app.route('/generate', methods=['POST'])
def generate_image():
    data = request.json
    messages = data['messages']
    
    # Generate HTML for all messages
    message_containers = ""
    for msg in messages:
        message_containers += MESSAGE_TEMPLATE.format(
            avatar_url=msg.get('avatar_url', ''),
            color=msg.get('color', '#ffffff'),
            username=msg.get('username', ''),
            timestamp=msg.get('timestamp', ''),
            message=msg.get('message', '')
        )
    
    # Complete HTML
    html_content = HTML_TEMPLATE.format(message_containers=message_containers)
    
    # Save temporary HTML file
    with open('temp.html', 'w') as f:
        f.write(html_content)
    
    # Setup Chrome options
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    
    # Generate screenshot
    driver = webdriver.Chrome(options=chrome_options)
    driver.get('file://' + os.path.abspath('temp.html'))
    
    # Wait for page to load
    driver.implicitly_wait(2)
    
    # Get body element and its size
    body = driver.find_element_by_tag_name('body')
    screenshot = body.screenshot_as_png
    
    driver.quit()
    os.remove('temp.html')
    
    return send_file(
        BytesIO(screenshot),
        mimetype='image/png'
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
