# main.py
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
import asyncio
from contextlib import asynccontextmanager
import signal
import sys
from logging.handlers import RotatingFileHandler
import aiohttp
import time
import os

# Enhanced logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('api.log', maxBytes=10000000, backupCount=5),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Configuration
class Config:
    MONGODB_URI = "mongodb+srv://flyhigh:Shekhar9330@cluster0.0dqoh.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
    API_URL = "https://api-v9ww.onrender.com"
    PING_INTERVAL = 840
    MONGODB_TIMEOUT = 5000
    MONGODB_CONNECT_TIMEOUT = 10000
    PORT = int(os.getenv("PORT", "10000"))

# Data Models
class ReactionUser(BaseModel):
    id: str
    name: str
    avatar_url: str
    model_config = ConfigDict(frozen=True)

class Reaction(BaseModel):
    emoji: str
    count: int
    users: List[ReactionUser]
    model_config = ConfigDict(frozen=True)

class Attachment(BaseModel):
    url: str
    filename: str
    content_type: str
    size: int
    model_config = ConfigDict(frozen=True)

class ReplyReference(BaseModel):
    message_id: str
    author: str
    content: str
    model_config = ConfigDict(frozen=True)

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
    model_config = ConfigDict(frozen=True)

class Conversation(BaseModel):
    conversation_id: str
    messages: List[Message]
    share_url: Optional[str] = None
    created_at: datetime
    guild_id: str
    channel_id: str
    model_config = ConfigDict(frozen=True)

# Database Management
class Database:
    client: Optional[AsyncIOMotorClient] = None
    db = None
    _retry_attempts = 3
    _retry_delay = 1

    @classmethod
    async def connect_db(cls):
        if cls.client:
            return

        for attempt in range(cls._retry_attempts):
            try:
                logger.info(f"Connecting to MongoDB (attempt {attempt + 1}/{cls._retry_attempts})...")
                cls.client = AsyncIOMotorClient(
                    Config.MONGODB_URI,
                    serverSelectionTimeoutMS=Config.MONGODB_TIMEOUT,
                    connectTimeoutMS=Config.MONGODB_CONNECT_TIMEOUT,
                    maxPoolSize=50
                )
                cls.db = cls.client.discord_archives
                await cls.client.admin.command('ping')
                logger.info("Successfully connected to MongoDB")
                return
            except Exception as e:
                logger.error(f"MongoDB connection attempt {attempt + 1} failed: {e}")
                if cls.client:
                    cls.client.close()
                    cls.client = None
                if attempt == cls._retry_attempts - 1:
                    raise
                await asyncio.sleep(cls._retry_delay)

    @classmethod
    async def close_db(cls):
        if cls.client:
            cls.client.close()
            cls.client = None
            logger.info("MongoDB connection closed")

    @classmethod
    async def get_db(cls):
        if not cls.client:
            await cls.connect_db()
        return cls.db

# Performance Monitoring
def measure_performance(func):
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            execution_time = time.time() - start_time
            logger.info(f"{func.__name__} executed in {execution_time:.2f} seconds")
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"{func.__name__} failed after {execution_time:.2f} seconds: {str(e)}")
            raise
    return wrapper

# Health Check Service
class PingService:
    def __init__(self, url: str, interval: int):
        self.url = url
        self.interval = interval
        self.session: Optional[aiohttp.ClientSession] = None
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        self.session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._ping_loop())
        logger.info(f"Started ping service for {self.url}")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self.session:
            await self.session.close()
        logger.info("Stopped ping service")

    async def _ping_loop(self):
        while True:
            try:
                async with self.session.get(f"{self.url}/health") as response:
                    if response.status == 200:
                        logger.info("Self-ping successful")
                    else:
                        logger.warning(f"Self-ping failed with status {response.status}")
            except Exception as e:
                logger.error(f"Error during self-ping: {e}")
            await asyncio.sleep(self.interval)

# Application Lifecycle Management
@asynccontextmanager
async def lifespan(app: FastAPI):
    ping_service = PingService(Config.API_URL, Config.PING_INTERVAL)
    
    # Startup
    await Database.connect_db()
    await ping_service.start()
    
    yield
    
    # Shutdown
    await ping_service.stop()
    await Database.close_db()

# FastAPI Application
app = FastAPI(
    title="Discord Archive API",
    description="API for archiving and retrieving Discord conversations",
    version="1.1.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request Tracking Middleware
@app.middleware("http")
async def request_tracking_middleware(request: Request, call_next):
    request_id = f"{time.time()}-{id(request)}"
    logger.info(f"Request {request_id}: {request.method} {request.url}")
    try:
        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time
        logger.info(f"Request {request_id} completed in {duration:.2f}s")
        return response
    except Exception as e:
        logger.error(f"Request {request_id} failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

# API Routes
@app.post("/conversations/")
@measure_performance
async def create_conversation(conversation: Conversation):
    try:
        db = await Database.get_db()
        conversation_dict = conversation.model_dump()
        await db.conversations.insert_one(conversation_dict)
        logger.info(f"Created conversation: {conversation.conversation_id}")
        return {"conversation_id": conversation.conversation_id, "status": "success"}
    except Exception as e:
        logger.error(f"Error creating conversation: {e}")
        raise HTTPException(status_code=500, detail="Failed to create conversation")

@app.get("/conversations/{conversation_id}")
@measure_performance
async def get_conversation(conversation_id: str):
    try:
        db = await Database.get_db()
        conversation = await db.conversations.find_one({"conversation_id": conversation_id})
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation["_id"] = str(conversation["_id"])
        return conversation
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve conversation")

@app.get("/conversations")
@measure_performance
async def list_conversations(
    guild_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    limit: int = 10,
    skip: int = 0
):
    try:
        db = await Database.get_db()
        query = {}
        if guild_id:
            query["guild_id"] = guild_id
        if channel_id:
            query["channel_id"] = channel_id

        conversations = await db.conversations.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)
        
        for conv in conversations:
            conv["_id"] = str(conv["_id"])
        
        return conversations
    except Exception as e:
        logger.error(f"Error listing conversations: {e}")
        raise HTTPException(status_code=500, detail="Failed to list conversations")

@app.get("/health")
async def health_check():
    try:
        db = await Database.get_db()
        await db.admin.command('ping')
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.1.0"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

# Application Entry Point
if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=Config.PORT,
        workers=4,
        log_level="info"
    )
