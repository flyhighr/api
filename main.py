from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

app = FastAPI(title="Discord Archive API")

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB Setup
MONGODB_URL = "mongodb+srv://flyhigh:Shekhar9330@cluster0.0dqoh.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = AsyncIOMotorClient(MONGODB_URL)
db = client.discord_archives

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

# Routes
@app.post("/conversations/")
async def create_conversation(conversation: Conversation):
    conversation_dict = conversation.model_dump()
    await db.conversations.insert_one(conversation_dict)
    return {"conversation_id": conversation.conversation_id}

@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    conversation = await db.conversations.find_one({"conversation_id": conversation_id})
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Convert ObjectId to string
    conversation["_id"] = str(conversation["_id"])
    
    # Sort messages by timestamp
    conversation["messages"].sort(key=lambda x: x["timestamp"])
    
    return conversation

@app.get("/conversations/{conversation_id}/share-url")
async def get_share_url(conversation_id: str):
    conversation = await db.conversations.find_one({"conversation_id": conversation_id})
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    base_url = "https://flyhighr.github.io/archive/"
    share_url = f"{base_url}?id={conversation_id}"
    
    await db.conversations.update_one(
        {"conversation_id": conversation_id},
        {"$set": {"share_url": share_url}}
    )
    
    return {"share_url": share_url}

@app.get("/conversations")
async def list_conversations(
    guild_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    limit: int = 10,
    skip: int = 0
):
    query = {}
    if guild_id:
        query["guild_id"] = guild_id
    if channel_id:
        query["channel_id"] = channel_id

    conversations = await db.conversations.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)
    
    for conv in conversations:
        conv["_id"] = str(conv["_id"])
    
    return conversations

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
