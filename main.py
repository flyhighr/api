from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
import asyncio
from contextlib import asynccontextmanager
import signal
import sys
from logging.handlers import RotatingFileHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('api.log', maxBytes=10000000, backupCount=5),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Models
class ReactionUser(BaseModel):
    id: str
    name: str
    avatar_url: str

class Reaction(BaseModel):
    emoji: str
    count: int
    users: List[ReactionUser]

class Attachment(BaseModel):
    url: str
    filename: str
    content_type: str
    size: int

class ReplyReference(BaseModel):
    message_id: str
    author: str
    content: str

class Message(BaseModel):
    content: str
    author: str
    author_nickname: Optional[str] = None
    avatar_url: str
    timestamp: datetime
    edited_timestamp: Optional[datetime] = None
    message_id: str
    reply_to: Optional[ReplyReference] = None
    reactions: List[Reaction] = Field(default_factory=list)
    attachments: List[Attachment] = Field(default_factory=list)

class Conversation(BaseModel):
    conversation_id: str
    messages: List[Message]
    share_url: Optional[str] = None
    created_at: datetime
    guild_id: str
    channel_id: str

# Database connection management
class Database:
    client: Optional[AsyncIOMotorClient] = None
    db = None

    @classmethod
    async def connect_db(cls):
        try:
            logger.info("Connecting to MongoDB...")
            cls.client = AsyncIOMotorClient(
                "mongodb+srv://flyhigh:Shekhar9330@cluster0.0dqoh.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0",
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=10000
            )
            cls.db = cls.client.discord_archives
            await cls.client.admin.command('ping')
            logger.info("Successfully connected to MongoDB")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    @classmethod
    async def close_db(cls):
        if cls.client:
            logger.info("Closing MongoDB connection...")
            cls.client.close()
            logger.info("MongoDB connection closed")

# Lifecycle management
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await Database.connect_db()
    
    # Handle shutdown signals
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}")
        asyncio.create_task(shutdown())

    async def shutdown():
        logger.info("Initiating graceful shutdown...")
        await Database.close_db()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    yield
    
    # Cleanup
    await Database.close_db()

# FastAPI app initialization
app = FastAPI(
    title="Discord Archive API",
    lifespan=lifespan
)

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Error handling middleware
@app.middleware("http")
async def error_handling_middleware(request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        logger.error(f"Unhandled error: {str(e)}")
        return HTTPException(status_code=500, detail="Internal server error")

# Routes with error handling and logging
@app.post("/conversations/")
async def create_conversation(conversation: Conversation):
    try:
        conversation_dict = conversation.model_dump()
        await Database.db.conversations.insert_one(conversation_dict)
        logger.info(f"Created conversation: {conversation.conversation_id}")
        return {"conversation_id": conversation.conversation_id}
    except Exception as e:
        logger.error(f"Error creating conversation: {e}")
        raise HTTPException(status_code=500, detail="Failed to create conversation")

@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    try:
        conversation = await Database.db.conversations.find_one({"conversation_id": conversation_id})
        if not conversation:
            logger.warning(f"Conversation not found: {conversation_id}")
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        conversation["_id"] = str(conversation["_id"])
        conversation["messages"].sort(key=lambda x: x["timestamp"])
        
        return conversation
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve conversation")

@app.get("/conversations/{conversation_id}/share-url")
async def get_share_url(conversation_id: str):
    try:
        conversation = await Database.db.conversations.find_one({"conversation_id": conversation_id})
        if not conversation:
            logger.warning(f"Conversation not found: {conversation_id}")
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        base_url = "https://flyhighr.github.io/archive/"
        share_url = f"{base_url}?id={conversation_id}"
        
        await Database.db.conversations.update_one(
            {"conversation_id": conversation_id},
            {"$set": {"share_url": share_url}}
        )
        
        logger.info(f"Generated share URL for conversation: {conversation_id}")
        return {"share_url": share_url}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating share URL for conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate share URL")

@app.get("/conversations")
async def list_conversations(
    guild_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    limit: int = 10,
    skip: int = 0
):
    try:
        query = {}
        if guild_id:
            query["guild_id"] = guild_id
        if channel_id:
            query["channel_id"] = channel_id

        conversations = await Database.db.conversations.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)
        
        for conv in conversations:
            conv["_id"] = str(conv["_id"])
        
        return conversations
    except Exception as e:
        logger.error(f"Error listing conversations: {e}")
        raise HTTPException(status_code=500, detail="Failed to list conversations")

# Health check endpoint
@app.get("/health")
async def health_check():
    try:
        await Database.db.admin.command('ping')
        return {"status": "healthy"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        workers=4,
        log_level="info",
        timeout_keep_alive=65
)
