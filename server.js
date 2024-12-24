const express = require('express');
const cors = require('cors');
const { z } = require('zod');
const puppeteer = require('puppeteer');
const { createCanvas, loadImage, registerFont } = require('canvas');
const path = require('path');
const emoji = require('node-emoji');
const hljs = require('highlight.js');
const app = express();

// Middleware
app.use(cors());
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true, limit: '50mb' }));

// Register fonts
const fontPath = path.join(__dirname, 'fonts');
registerFont(path.join(fontPath, 'Whitney-Light.ttf'), { family: 'Whitney', weight: '300' });
registerFont(path.join(fontPath, 'Whitney-Normal.ttf'), { family: 'Whitney', weight: '400' });
registerFont(path.join(fontPath, 'Whitney-Medium.ttf'), { family: 'Whitney', weight: '500' });
registerFont(path.join(fontPath, 'Whitney-Bold.ttf'), { family: 'Whitney', weight: '700' });
registerFont(path.join(fontPath, 'Whitney-Black.ttf'), { family: 'Whitney', weight: '900' });

// Enhanced validation schemas
const ReactionSchema = z.object({
  emoji: z.string(),
  count: z.number().min(1).default(1),
  userHasReacted: z.boolean().default(false)
});

const AttachmentSchema = z.object({
  url: z.string().url(),
  type: z.enum(['image', 'video', 'file', 'audio']),
  name: z.string().optional(),
  size: z.string().optional(),
  dimensions: z.object({
    width: z.number(),
    height: z.number()
  }).optional()
});

const CodeBlockSchema = z.object({
  language: z.string(),
  content: z.string(),
  highlight: z.array(z.number()).optional()
});

const EmbedFieldSchema = z.object({
  name: z.string(),
  value: z.string(),
  inline: z.boolean().default(false)
});

const EmbedSchema = z.object({
  title: z.string().optional(),
  description: z.string().optional(),
  url: z.string().url().optional(),
  color: z.string().regex(/^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$/).optional(),
  fields: z.array(EmbedFieldSchema).optional(),
  thumbnail: z.string().url().optional(),
  image: z.string().url().optional(),
  author: z.object({
    name: z.string(),
    url: z.string().url().optional(),
    icon_url: z.string().url().optional()
  }).optional(),
  footer: z.object({
    text: z.string(),
    icon_url: z.string().url().optional()
  }).optional(),
  timestamp: z.string().optional()
});

const MessageSchema = z.object({
  id: z.string().optional(),
  username: z.string().min(1).max(32),
  content: z.string(),
  timestamp: z.string().optional().default(() => 
    new Date().toLocaleString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    })
  ),
  color: z.string().regex(/^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$/).optional().default('#ff66ff'),
  isApp: z.boolean().optional().default(false),
  avatar: z.string().url().optional(),
  command: z.boolean().optional().default(false),
  edited: z.boolean().optional().default(false),
  pinned: z.boolean().optional().default(false),
  reactions: z.array(ReactionSchema).optional(),
  attachments: z.array(AttachmentSchema).optional(),
  embeds: z.array(EmbedSchema).optional(),
  codeBlocks: z.array(CodeBlockSchema).optional(),
  replyTo: z.object({
    id: z.string(),
    username: z.string(),
    content: z.string(),
    jump: z.boolean().optional().default(false)
  }).optional(),
  mentions: z.array(z.string()).optional(),
  roleColorOverrides: z.record(z.string()).optional()
});

const RequestSchema = z.object({
  messages: z.array(MessageSchema),
  channelName: z.string().optional(),
  theme: z.enum(['dark', 'light']).optional().default('dark'),
  renderMethod: z.enum(['canvas', 'puppeteer']).optional().default('puppeteer'),
  format: z.enum(['png', 'jpeg']).optional().default('png'),
  quality: z.number().min(0).max(1).optional().default(0.92),
  width: z.number().optional().default(800)
});

// HTML Template Generation
function generateMessageHTML(message, theme) {
  const baseStyles = `
    /* Base styles omitted for brevity - include Discord-like CSS */
  `;
  
  const messageTemplate = `
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <style>${baseStyles}</style>
    </head>
    <body class="theme-${theme}">
      <div class="messages-container">
        ${generateMessageContent(message)}
      </div>
    </body>
    </html>
  `;
  
  return messageTemplate;
}

// Canvas Drawing Functions
async function drawMessageCanvas(canvas, message, startY) {
  const ctx = canvas.getContext('2d');
  let currentY = startY;
  
  // Draw avatar
  if (message.avatar) {
    await drawAvatar(ctx, message, 16, currentY);
  }
  
  // Draw username and timestamp
  currentY = await drawHeader(ctx, message, currentY);
  
  // Draw content
  currentY = await drawContent(ctx, message, currentY);
  
  // Draw attachments
  if (message.attachments?.length) {
    currentY = await drawAttachments(ctx, message.attachments, currentY);
  }
  
  // Draw embeds
  if (message.embeds?.length) {
    currentY = await drawEmbeds(ctx, message.embeds, currentY);
  }
  
  // Draw reactions
  if (message.reactions?.length) {
    currentY = await drawReactions(ctx, message.reactions, currentY);
  }
  
  return currentY;
}

// Puppeteer Rendering Function
async function generateImagePuppeteer(messages, options) {
  const browser = await puppeteer.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
    defaultViewport: {
      width: options.width,
      height: 800,
      deviceScaleFactor: 2
    }
  });
  
  const page = await browser.newPage();
  
  // Set content
  const html = generateMessageHTML(messages, options.theme);
  await page.setContent(html, { waitUntil: 'networkidle0' });
  
  // Get content height
  const height = await page.evaluate(() => {
    const body = document.body;
    const html = document.documentElement;
    return Math.max(
      body.scrollHeight,
      body.offsetHeight,
      html.clientHeight,
      html.scrollHeight,
      html.offsetHeight
    );
  });
  
  // Set viewport to match content
  await page.setViewport({
    width: options.width,
    height: height,
    deviceScaleFactor: 2
  });
  
  // Capture screenshot
  const buffer = await page.screenshot({
    type: options.format,
    quality: options.format === 'jpeg' ? options.quality * 100 : undefined,
    fullPage: true
  });
  
  await browser.close();
  return buffer;
}

// Main Generation Route
app.post('/generate', async (req, res) => {
  try {
    const options = RequestSchema.parse(req.body);
    let imageBuffer;
    
    if (options.renderMethod === 'puppeteer') {
      imageBuffer = await generateImagePuppeteer(options.messages, options);
    } else {
      imageBuffer = await generateImageCanvas(options.messages, options);
    }
    
    res.set('Content-Type', `image/${options.format}`);
    res.set('Cache-Control', 'public, max-age=31536000');
    res.send(imageBuffer);
    
  } catch (error) {
    console.error('Generation error:', error);
    
    if (error instanceof z.ZodError) {
      res.status(400).json({
        error: 'Invalid input',
        details: error.errors
      });
    } else {
      res.status(500).json({
        error: 'Internal server error',
        message: error.message
      });
    }
  }
});

// Cache control middleware
const cache = require('memory-cache');
app.use((req, res, next) => {
  const key = '__express__' + req.originalUrl || req.url;
  const cachedBody = cache.get(key);
  
  if (cachedBody) {
    res.send(cachedBody);
    return;
  }
  
  res.sendResponse = res.send;
  res.send = (body) => {
    cache.put(key, body, 300000); // Cache for 5 minutes
    res.sendResponse(body);
  };
  next();
});

// Error handling middleware
app.use((err, req, res, next) => {
  console.error(err.stack);
  res.status(500).json({
    error: 'Internal server error',
    message: process.env.NODE_ENV === 'development' ? err.message : 'An unexpected error occurred'
  });
});

// Start server
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});

module.exports = app;
