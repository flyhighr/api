from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uuid

app = FastAPI(title="Discord Archive API")

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update this with your frontend URL in production
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
@app.post("/conversations/", response_model=dict)
async def create_conversation(conversation: Conversation):
    conversation_dict = conversation.dict()
    await db.conversations.insert_one(conversation_dict)
    return {"conversation_id": conversation.conversation_id}

@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    conversation = await db.conversations.find_one({"conversation_id": conversation_id})
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation["_id"] = str(conversation["_id"])  # Convert ObjectId to string
    return conversation

@app.patch("/conversations/{conversation_id}/share-url")
async def update_share_url(conversation_id: str, share_url: str):
    result = await db.conversations.update_one(
        {"conversation_id": conversation_id},
        {"$set": {"share_url": share_url}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
