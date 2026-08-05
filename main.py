import os
import sqlite3
import secrets
import asyncio
import nest_asyncio
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pyrogram import Client, filters
from pyrogram.types import Message

nest_asyncio.apply()
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
RENDER_URL = os.getenv("RENDER_URL")

# SQLite Database Setup
conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS streams (
        unique_id TEXT PRIMARY KEY,
        file_id TEXT NOT NULL,
        file_size INTEGER,
        mime_type TEXT
    )
""")
conn.commit()

# Telegram Pyrogram Client
bot = Client("TelegramFileStoreBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# FastAPI Application
app = FastAPI()

# Blogger-এ ভিডিও ব্লক হওয়া ঠেকাতে CORS সেটআপ
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- TELEGRAM BOT EVENT -----------------

@bot.on_message(filters.chat(CHANNEL_ID) & (filters.video | filters.document))
async def handle_channel_post(client: Client, message: Message):
    media = message.video or message.document
    if not media:
        return

    unique_id = secrets.token_hex(4)
    file_id = media.file_id
    file_size = media.file_size
    mime_type = media.mime_type or "video/mp4"

    cursor.execute(
        "INSERT INTO streams (unique_id, file_id, file_size, mime_type) VALUES (?, ?, ?, ?)",
        (unique_id, file_id, file_size, mime_type)
    )
    conn.commit()

    stream_link = f"{RENDER_URL}/stream/{unique_id}.mp4"
    print(f"[SUCCESS] New Stream Link Created for Blogger: {stream_link}")

# ----------------- FASTAPI ROUTES -----------------

@app.get("/ping")
async def ping():
    return {"status": "alive", "message": "Bot is running perfectly!"}

async def media_streamer(file_id: str, offset: int, limit: int):
    async for chunk in bot.stream_media(file_id, offset=offset, limit=limit):
        yield chunk

@app.get("/stream/{unique_id}.mp4")
async def stream_video(unique_id: str, request: Request):
    cursor.execute("SELECT file_id, file_size, mime_type FROM streams WHERE unique_id = ?", (unique_id,))
    data = cursor.fetchone()

    if not data:
        raise HTTPException(status_code=404, detail="File not found")

    file_id, file_size, mime_type = data
    range_header = request.headers.get("range")

    if range_header:
        bytes_type, bytes_range = range_header.split("=")
        start_str, end_str = bytes_range.split("-")
        start = int(start_str)
        end = int(end_str) if end_str else file_size - 1
        length = end - start + 1

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": mime_type,
            "Access-Control-Allow-Origin": "*",
        }

        offset = start // (1024 * 1024)
        return StreamingResponse(
            media_streamer(file_id, offset=offset, limit=length),
            status_code=206,
            headers=headers
        )
    else:
        headers = {
            "Content-Length": str(file_size),
            "Content-Type": mime_type,
            "Accept-Ranges": "bytes",
            "Access-Control-Allow-Origin": "*",
        }
        return StreamingResponse(
            media_streamer(file_id, offset=0, limit=file_size),
            headers=headers
        )

# ----------------- APP RUNNER -----------------

async def start_services():
    import uvicorn
    await bot.start()
    config = uvicorn.Config(app=app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_services())
