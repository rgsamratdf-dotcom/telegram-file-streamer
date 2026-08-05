import os
import sqlite3
import secrets
import asyncio
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pyrogram import Client, filters
from pyrogram.types import Message

load_dotenv()

# ==================== Environment Variables ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_ID"))
RENDER_URL = os.getenv("RENDER_URL").rstrip("/")

# ==================== Database ====================
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

# ==================== Pyrogram Bot ====================
bot = Client(
    "TelegramFileStoreBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ==================== FastAPI App ====================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== Bot Handlers ====================
@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    await message.reply_text(
        "হ্যালো! আমি Video Stream Bot।\n\n"
        "চ্যানেলে কোনো ভিডিও আপলোড করলে আমি তোমাকে Direct Stream লিংক দিয়ে দিব।"
    )

@bot.on_message(filters.chat(CHANNEL_ID) & (filters.video | filters.document))
async def handle_channel_post(client: Client, message: Message):
    media = message.video or message.document
    if not media:
        return

    # শুধু ভিডিও ফাইল নেব
    if media.mime_type and not media.mime_type.startswith("video/"):
        return

    unique_id = secrets.token_hex(6)
    file_id = media.file_id
    file_size = media.file_size or 0
    mime_type = media.mime_type or "video/mp4"

    cursor.execute(
        "INSERT INTO streams (unique_id, file_id, file_size, mime_type) VALUES (?, ?, ?, ?)",
        (unique_id, file_id, file_size, mime_type)
    )
    conn.commit()

    stream_link = f"{RENDER_URL}/stream/{unique_id}.mp4"

    # তোমাকে DM-এ লিংক পাঠাবে
    try:
        await bot.send_message(
            OWNER_ID,
            f"✅ নতুন ভিডিও সেভ হয়েছে!\n\n"
            f"🔗 Direct Stream Link:\n`{stream_link}`\n\n"
            f"এই লিংক Blogger-এ বসিয়ে স্ট্রিম করতে পারবে।"
        )
    except Exception as e:
        print(f"DM পাঠাতে সমস্যা: {e}")

    print(f"[SUCCESS] Link created: {stream_link}")

# ==================== Streaming Function ====================
async def media_streamer(file_id: str, offset: int = 0):
    async for chunk in bot.stream_media(file_id, offset=offset):
        yield chunk

# ==================== FastAPI Routes ====================
@app.get("/ping")
async def ping():
    return {"status": "alive", "message": "Bot is running"}

@app.get("/stream/{unique_id}.mp4")
async def stream_video(unique_id: str, request: Request):
    cursor.execute("SELECT file_id, file_size, mime_type FROM streams WHERE unique_id = ?", (unique_id,))
    data = cursor.fetchone()

    if not data:
        raise HTTPException(status_code=404, detail="File not found")

    file_id, file_size, mime_type = data
    range_header = request.headers.get("range")

    if range_header:
        bytes_range = range_header.replace("bytes=", "").split("-")
        start = int(bytes_range[0])
        end = int(bytes_range[1]) if bytes_range[1] else file_size - 1
        length = end - start + 1

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": mime_type,
        }
        offset = start // (1024 * 1024)
        return StreamingResponse(
            media_streamer(file_id, offset=offset),
            status_code=206,
            headers=headers
        )
    else:
        headers = {
            "Content-Length": str(file_size),
            "Content-Type": mime_type,
            "Accept-Ranges": "bytes",
        }
        return StreamingResponse(
            media_streamer(file_id, offset=0),
            headers=headers
        )

# ==================== Start Everything ====================
async def start_services():
    await bot.start()
    print("Bot started successfully!")
    import uvicorn
    config = uvicorn.Config(app, host="0.0.0.0", port=10000)
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(start_services())
