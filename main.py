from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime
import logging
import asyncio
from contextlib import asynccontextmanager
import signal
import sys
from logging.handlers import RotatingFileHandler
import aiohttp
import time
from functools import wraps
import os

# Configure logging with rotating file handler
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            'app.log',
            maxBytes=1024*1024,  # 1MB
            backupCount=5
        ),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Enhanced Models with modern Pydantic configuration
class BaseModelWithConfig(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        populate_by_name=True,
        from_attributes=True
    )

class ReactionUser(BaseModelWithConfig):
    id: str
    name: str
    avatar_url: str

class Reaction(BaseModelWithConfig):
    emoji: str
    count: int
    users: List[ReactionUser]

class Attachment(BaseModelWithConfig):
    url: str
    filename: str
    content_type: str
    size: int

class ReplyReference(BaseModelWithConfig):
    message_id: str
    author: str
    content: str

class Message(BaseModelWithConfig):
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

class Conversation(BaseModelWithConfig):
    conversation_id: str
    messages: List[Message]
    share_url: Optional[str] = None
    created_at: datetime
    guild_id: str
    channel_id: str

# Database connection management with retry mechanism
class Database:
    client: Optional[AsyncIOMotorClient] = None
    db = None
    MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://flyhigh:Shekhar9330@cluster0.0dqoh.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
    MAX_RETRIES = 3
    RETRY_DELAY = 5

    @classmethod
    async def connect_db(cls):
        retries = 0
        while retries < cls.MAX_RETRIES:
            try:
                logger.info(f"Connecting to MongoDB (attempt {retries + 1}/{cls.MAX_RETRIES})...")
                cls.client = AsyncIOMotorClient(
                    cls.MONGO_URI,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=10000
                )
                cls.db = cls.client.discord_archives
                # Fixed: Use client.admin.command instead of db.admin.command
                await cls.client.admin.command('ping')
                logger.info("Successfully connected to MongoDB")
                return
            except Exception as e:
                retries += 1
                if retries == cls.MAX_RETRIES:
                    logger.error(f"Failed to connect to MongoDB after {cls.MAX_RETRIES} attempts: {e}")
                    raise
                logger.warning(f"Failed to connect to MongoDB (attempt {retries}): {e}")
                await asyncio.sleep(cls.RETRY_DELAY)

    @classmethod
    async def close_db(cls):
        if cls.client:
            logger.info("Closing MongoDB connection...")
            cls.client.close()
            logger.info("MongoDB connection closed")

class SelfPingService:
    def __init__(self, url: str = "https://api-v9ww.onrender.com/health", interval: int = 840):
        self.url = url
        self.interval = interval
        self.session: Optional[aiohttp.ClientSession] = None
        self.is_running = False
        self.last_ping_time = 0
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        if self._task is not None:
            return

        self.is_running = True
        self.session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        while self.is_running:
            try:
                current_time = time.time()
                if current_time - self.last_ping_time >= self.interval:
                    async with self.session.get(self.url) as response:
                        if response.status == 200:
                            logger.info("Self-ping successful")
                            self.last_ping_time = current_time
                        else:
                            logger.warning(f"Self-ping failed with status {response.status}")
            except Exception as e:
                logger.error(f"Self-ping error: {e}")
            await asyncio.sleep(60)

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        
        if self.session:
            await self.session.close()

# FastAPI app initialization with lifespan
app = FastAPI(
    title="Discord Archive API",
    description="API for managing Discord conversation archives",
    version="1.1.0",
    lifespan=lifespan
)

# Performance monitoring decorator
def monitor_performance():
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                execution_time = time.time() - start_time
                logger.info(f"{func.__name__} executed in {execution_time:.2f} seconds")
        return wrapper
    return decorator

# Lifecycle management
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize services
    ping_service = SelfPingService()
    
    # Startup
    await Database.connect_db()
    await ping_service.start()
    
    # Handle shutdown signals
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}")
        asyncio.create_task(shutdown())

    async def shutdown():
        logger.info("Initiating graceful shutdown...")
        await ping_service.stop()
        await Database.close_db()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        yield
    finally:
        # Cleanup
        await ping_service.stop()
        await Database.close_db()

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enhanced error handling middleware
@app.middleware("http")
async def error_handling_middleware(request, call_next):
    try:
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        return response
    except Exception as e:
        logger.error(f"Unhandled error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

# Enhanced routes with performance monitoring
@app.post("/conversations/")
@monitor_performance()
async def create_conversation(conversation: Conversation):
    try:
        conversation_dict = conversation.model_dump()
        result = await Database.db.conversations.insert_one(conversation_dict)
        logger.info(f"Created conversation: {conversation.conversation_id}")
        return {"conversation_id": conversation.conversation_id, "inserted_id": str(result.inserted_id)}
    except Exception as e:
        logger.error(f"Error creating conversation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create conversation")

@app.get("/conversations/{conversation_id}")
@monitor_performance()
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
        logger.error(f"Error retrieving conversation {conversation_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve conversation")

@app.get("/conversations/{conversation_id}/share-url")
@monitor_performance()
async def get_share_url(conversation_id: str):
    try:
        conversation = await Database.db.conversations.find_one({"conversation_id": conversation_id})
        if not conversation:
            logger.warning(f"Conversation not found: {conversation_id}")
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        base_url = os.getenv("BASE_URL", "https://flyhighr.github.io/archive/")
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
        logger.error(f"Error generating share URL for conversation {conversation_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate share URL")

@app.get("/conversations")
@monitor_performance()
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

        total_count = await Database.db.conversations.count_documents(query)
        conversations = await Database.db.conversations.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)
        
        for conv in conversations:
            conv["_id"] = str(conv["_id"])
        
        return {
            "conversations": conversations,
            "total": total_count,
            "page": skip // limit + 1,
            "pages": (total_count + limit - 1) // limit
        }
    except Exception as e:
        logger.error(f"Error listing conversations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list conversations")

@app.get("/health")
@monitor_performance()
async def health_check():
    try:
        # Fixed: Use client.admin.command instead of db.admin.command
        await Database.client.admin.command('ping')
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow(),
            "version": "1.1.0"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Service unhealthy")

# Environment variables
PORT = int(os.getenv("PORT", 10000))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        workers=1,
        log_level="info"
    )
