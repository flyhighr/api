const express = require('express');
const cors = require('cors');
const { z } = require('zod');
const app = express();

// Middleware
app.use(cors());
app.use(express.json());

// Advanced validation schemas
const ReactionSchema = z.object({
  emoji: z.string(),
  count: z.number().min(1).default(1),
  userHasReacted: z.boolean().default(false)
});

const AttachmentSchema = z.object({
  url: z.string().url(),
  type: z.enum(['image', 'video', 'file']),
  name: z.string().optional(),
  size: z.string().optional()
});

const EmbedSchema = z.object({
  title: z.string().optional(),
  description: z.string().optional(),
  url: z.string().url().optional(),
  color: z.string().regex(/^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$/).optional(),
  fields: z.array(z.object({
    name: z.string(),
    value: z.string(),
    inline: z.boolean().default(false)
  })).optional(),
  thumbnail: z.string().url().optional(),
  image: z.string().url().optional(),
  footer: z.object({
    text: z.string(),
    icon_url: z.string().url().optional()
  }).optional(),
  timestamp: z.string().optional()
});

const MessageSchema = z.object({
  id: z.string().optional(),
  username: z.string().min(1).max(32),
  content: z.string().min(1),
  timestamp: z.string().optional().default(() => 
    'Today at ' + new Date().toLocaleTimeString('en-US', { 
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
  replyTo: z.object({
    id: z.string(),
    username: z.string(),
    content: z.string(),
    jump: z.boolean().optional().default(false)
  }).optional(),
  thread: z.object({
    name: z.string(),
    messageCount: z.number(),
    lastReply: z.string().optional()
  }).optional()
});

const RequestSchema = z.object({
  messages: z.array(MessageSchema),
  channelName: z.string().optional(),
  threadName: z.string().optional()
});

// Enhanced CSS styles
const baseStyles = `
<style>
  body {
    margin: 0;
    padding: 16px;
    background-color: #0f0f0f;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
    line-height: 1.375rem;
    color: #dcddde;
  }

  .chat-container {
    max-width: 800px;
    margin: 0 auto;
  }

  .channel-name {
    color: #dcddde;
    font-size: 16px;
    font-weight: 600;
    padding: 8px 0;
    border-bottom: 1px solid #2f3136;
    margin-bottom: 16px;
  }

  .thread-container {
    margin-left: 32px;
    border-left: 2px solid #2f3136;
    padding-left: 16px;
  }

  .message {
    display: flex;
    gap: 16px;
    margin-bottom: 16px;
    padding: 2px 0;
    position: relative;
  }

  .message:hover {
    background-color: #1f2123;
  }

  .message.pinned::before {
    content: "📌";
    position: absolute;
    left: -20px;
    color: #b9bbbe;
  }

  .avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    overflow: hidden;
    background: linear-gradient(45deg, #2c1810, #421b10);
    flex-shrink: 0;
  }

  .avatar.app {
    background: white;
    padding: 4px;
  }

  .avatar img {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }

  .message-content {
    flex: 1;
    min-width: 0;
  }

  .message-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
  }

  .username {
    font-weight: 600;
    cursor: pointer;
  }

  .username:hover {
    text-decoration: underline;
  }

  .app-badge {
    background-color: #5865F2;
    color: white;
    padding: 0 4px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 500;
  }

  .timestamp {
    color: #72767d;
    font-size: 0.8rem;
  }

  .edited {
    color: #72767d;
    font-size: 0.8rem;
    font-style: italic;
  }

  .message-text {
    color: white;
    margin: 0;
    word-wrap: break-word;
  }

  .code {
    background-color: #2f3136;
    padding: 2px 6px;
    border-radius: 3px;
    font-family: monospace;
  }

  .phone-icon {
    color: #ed4245;
    margin-right: 4px;
  }

  .reply-container {
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    gap: 8px;
    color: #72767d;
    font-size: 0.9rem;
  }

  .reply-content {
    color: #72767d;
    text-decoration: none;
    cursor: pointer;
  }

  .reply-content:hover {
    color: #dcddde;
    text-decoration: underline;
  }

  .reactions {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 4px;
  }

  .reaction {
    background-color: #2f3136;
    border-radius: 4px;
    padding: 0 6px;
    font-size: 0.9rem;
    display: flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
  }

  .reaction.reacted {
    background-color: #3b3f46;
  }

  .attachments {
    margin-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .attachment {
    max-width: 400px;
    border-radius: 4px;
    overflow: hidden;
  }

  .attachment img {
    max-width: 100%;
    height: auto;
  }

  .file-attachment {
    background-color: #2f3136;
    padding: 8px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .embed {
    margin-top: 8px;
    border-left: 4px solid;
    background-color: #2f3136;
    border-radius: 4px;
    padding: 8px 16px;
    max-width: 520px;
  }

  .embed-title {
    color: #dcddde;
    font-size: 1rem;
    font-weight: 600;
    margin-bottom: 8px;
  }

  .embed-description {
    color: #dcddde;
    font-size: 0.9rem;
    margin-bottom: 8px;
  }

  .embed-fields {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    margin: 8px 0;
  }

  .embed-field {
    margin-bottom: 8px;
  }

  .embed-field-name {
    color: #dcddde;
    font-weight: 600;
    font-size: 0.9rem;
  }

  .embed-field-value {
    color: #dcddde;
    font-size: 0.9rem;
  }

  .embed-footer {
    color: #72767d;
    font-size: 0.8rem;
    margin-top: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .thread-indicator {
    margin-top: 8px;
    color: #72767d;
    font-size: 0.9rem;
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
  }

  .thread-indicator:hover {
    color: #dcddde;
  }
</style>
`;

// HTML generation functions
function generateReplyHTML(reply) {
  return `
    <div class="reply-container">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
        <path d="M10.8 4.8H7.2v1.6h3.6V4.8zm3.6 1.6h-2.4v1.6h2.4V6.4zm-6 3.2H6v1.6h2.4V9.6zm3.6 1.6H9.6v1.6h2.4v-1.6zm3.6-1.6h-2.4v1.6h2.4V9.6z"></path>
      </svg>
      <span>replying to</span>
      <a class="reply-content" href="#msg-${reply.id}">@${reply.username}</a>
    </div>
  `;
}

function generateReactionsHTML(reactions) {
  return reactions.map(reaction => `
    <div class="reaction ${reaction.userHasReacted ? 'reacted' : ''}">
      <span>${reaction.emoji}</span>
      <span>${reaction.count}</span>
    </div>
  `).join('');
}

function generateAttachmentsHTML(attachments) {
  return attachments.map(attachment => {
    if (attachment.type === 'image') {
      return `
        <div class="attachment">
          <img src="${attachment.url}" alt="${attachment.name || 'attachment'}">
        </div>
      `;
    } else {
      return `
        <div class="file-attachment">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M15.5 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V6.5L15.5 2z"></path>
          </svg>
          <span>${attachment.name}</span>
          ${attachment.size ? `<span class="file-size">${attachment.size}</span>` : ''}
        </div>
      `;
    }
  }).join('');
}

function generateEmbedHTML(embed) {
  let html = `<div class="embed" style="border-color: ${embed.color || '#2f3136'}">`;
  
  if (embed.title) {
    html += `<div class="embed-title">${embed.title}</div>`;
  }
  
  if (embed.description) {
    html += `<div class="embed-description">${embed.description}</div>`;
  }
  
  if (embed.fields?.length) {
    html += `<div class="embed-fields">`;
    embed.fields.forEach(field => {
      html += `
        <div class="embed-field ${field.inline ? 'inline' : ''}">
          <div class="embed-field-name">${field.name}</div>
          <div class="embed-field-value">${field.value}</div>
        </div>
      `;
    });
    html += `</div>`;
  }
  
  if (embed.image) {
    html += `<img src="${embed.image}" class="embed-image">`;
  }
  
  if (embed.footer) {
    html += `
      <div class="embed-footer">
        ${embed.footer.icon_url ? `<img src="${embed.footer.icon_url}" width="16" height="16">` : ''}
        ${embed.footer.text}
      </div>
    `;
  }
  
  html += `</div>`;
  return html;
}

function generateThreadHTML(thread) {
  return `
    <div class="thread-indicator">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
        <path d="M5.43 21l.12-.13.13-.12.59-.59 2.73-2.73.17-.17.12-.12.13-.13L4.71 12l-.59-.59-.12-.13-.13-.12L2.29 9.58l-.17-.17-.12-.12-.13-.13L.29 7.58l-.17-.17L0 7.29v14.14l.12-.13.13-.12.59-.59 2.73-2.73.17-.17.12-.12.13-.13 1.41 1.41z"></path>
      </svg>
      <span>${thread.name}</span>
      <span>${thread.messageCount} messages</span>
      ${thread.lastReply ? `<span>Last reply ${thread.lastReply}</span>` : ''}
    </div>
  `;
}

function generateMessageHTML(message) {
  const avatarContent = message.avatar 
    ? `<img src="${message.avatar}" alt="${message.username}">`
    : '';

  const appBadge = message.isApp 
    ? '<span class="app-badge">APP</span>' 
    : '';

  const messageContent = message.command
    ? `<span class="phone-icon">📞</span>${message.content}`
    : message.content;

  return `
    <div class="message ${message.pinned ? 'pinned' : ''}" ${message.id ? `id="msg-${message.id}"` : ''}>
      <div class="avatar ${message.isApp ? 'app' : ''}">
        ${avatarContent}
      </div>
      <div class="message-content">
        ${message.replyTo ? generateReplyHTML(message.replyTo) : ''}
        <div class="message-<div class="message-header">
          <span class="username" style="color: ${message.color}">${message.username}</span>
          ${appBadge}
          <span class="timestamp">${message.timestamp}</span>
          ${message.edited ? '<span class="edited">(edited)</span>' : ''}
        </div>
        <p class="message-text">${messageContent}</p>
        ${message.reactions ? `<div class="reactions">${generateReactionsHTML(message.reactions)}</div>` : ''}
        ${message.attachments ? `<div class="attachments">${generateAttachmentsHTML(message.attachments)}</div>` : ''}
        ${message.embeds ? message.embeds.map(embed => generateEmbedHTML(embed)).join('') : ''}
        ${message.thread ? generateThreadHTML(message.thread) : ''}
      </div>
    </div>
  `;
}

// Main route to generate Discord-like messages
app.post('/generate', async (req, res) => {
  try {
    // Validate input
    const { messages, channelName, threadName } = RequestSchema.parse(req.body);

    // Generate HTML
    const messagesHTML = messages.map(generateMessageHTML).join('');
    
    const fullHTML = `
      <!DOCTYPE html>
      <html>
      <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        ${baseStyles}
      </head>
      <body>
        <div class="chat-container">
          ${channelName ? `<div class="channel-name">${channelName}</div>` : ''}
          ${threadName ? `
            <div class="thread-container">
              <div class="thread-name">${threadName}</div>
              ${messagesHTML}
            </div>
          ` : messagesHTML}
        </div>
      </body>
      </html>
    `;

    res.send(fullHTML);
  } catch (error) {
    if (error instanceof z.ZodError) {
      res.status(400).json({
        error: 'Invalid input',
        details: error.errors
      });
    } else {
      console.error('Server error:', error);
      res.status(500).json({
        error: 'Internal server error'
      });
    }
  }
});

// Example usage endpoint
app.get('/example', (req, res) => {
  const examplePayload = {
    channelName: "general",
    messages: [
      {
        id: "1",
        username: "roo",
        content: "Hey everyone!",
        color: "#ff66ff",
        reactions: [
          { emoji: "👋", count: 3, userHasReacted: true }
        ]
      },
      {
        id: "2",
        username: "Payphone",
        content: "You're not on a call! Use p.call to start one.",
        isApp: true,
        command: true,
        embeds: [{
          title: "Call Status",
          description: "No active calls",
          color: "#ff0000"
        }]
      },
      {
        id: "3",
        username: "user123",
        content: "Let me try that",
        replyTo: {
          id: "2",
          username: "Payphone",
          content: "You're not on a call!"
        },
        thread: {
          name: "Call Discussion",
          messageCount: 5,
          lastReply: "2 minutes ago"
        }
      }
    ]
  };
  
  res.json(examplePayload);
});

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'healthy' });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});

module.exports = app;
