from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from typing import List, Optional
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
class Message(BaseModel):
    content: str
    author: str
    avatar_url: str
    timestamp: datetime
    message_id: str

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
    conversation_dict = conversation.model_dump()  # Updated from .dict()
    await db.conversations.insert_one(conversation_dict)
    return {"conversation_id": conversation.conversation_id}

@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    conversation = await db.conversations.find_one({"conversation_id": conversation_id})
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation["_id"] = str(conversation["_id"])
    return conversation

@app.get("/conversations/{conversation_id}/share-url")  # Changed from PATCH to GET
async def get_share_url(conversation_id: str):
    conversation = await db.conversations.find_one({"conversation_id": conversation_id})
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    base_url = "https://flyhighr.github.io/archive/view"  # Update this with your actual frontend URL
    share_url = f"{base_url}?id={conversation_id}"
    
    # Update the share URL in the database
    await db.conversations.update_one(
        {"conversation_id": conversation_id},
        {"$set": {"share_url": share_url}}
    )
    
    return {"share_url": share_url}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
