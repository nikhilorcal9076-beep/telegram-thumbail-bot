import os
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Credentials from Environment Variables (set in Render Dashboard)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7566739138:AAEXf7azvE8FH9W0cQnFZpytbmGxc-p2_Bc")
API_ID = int(os.environ.get("API_ID", "2040"))  # Default telegram public test ID or set your own from my.telegram.org
API_HASH = os.environ.get("API_HASH", "b18441a1ff607e10a989891a5462e627")
FLOOD_SLEEP_DELAY = float(os.environ.get("FLOOD_SLEEP_DELAY", "0.8"))

# Initialize Pyrogram Bot Client
bot = Client(
    "thumb_changer_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# In-memory user state
USER_THUMBNAILS = {}
USER_QUEUES = {}
PROCESSING_WORKERS = {}

os.makedirs("thumbnails", exist_ok=True)

@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    user_name = message.from_user.first_name or "User"
    text = (
        f"👋 **नमस्ते {user_name}!**\n\n"
        "मैं **Telegram Batch Video Thumbnail Changer Bot** हूँ।\n\n"
        "⚡ **इस्तेमाल करने का तरीका:**\n"
        "1️⃣ सबसे पहले मुझे कोई भी **Photo** भेजें जिसे आप थंबनेल बनाना चाहते हैं।\n"
        "2️⃣ इसके बाद जितने भी **Videos** फॉरवर्ड (Forward) करेंगे, सब में वो थंबनेल अपने-आप लग जाएगा!\n"
        "3️⃣ बिना वीडियो डाउनलोड किए तुरंत `file_id` से प्रोसेस होता है (0 MB डाटा खर्च)!\n\n"
        "🛠 **कमांड्स:**\n"
        "• /viewthumb - वर्तमान थंबनेल देखें\n"
        "• /delthumb - थंबनेल हटाएं\n"
        "• /status - कतार स्थिति देखें"
    )
    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🖼️ थंबनेल देखें", callback_data="view_thumb"),
             InlineKeyboardButton("🗑️ थंबनेल हटाएं", callback_data="del_thumb")]
        ])
    )

@bot.on_message(filters.photo & filters.private)
async def save_thumbnail_handler(client: Client, message: Message):
    user_id = message.from_user.id
    status_msg = await message.reply_text("⏳ थंबनेल डाउनलोड व सेव किया जा रहा है...")
    thumb_path = f"thumbnails/thumb_{user_id}.jpg"
    await message.download(file_name=thumb_path)
    USER_THUMBNAILS[user_id] = thumb_path

    await status_msg.edit_text(
        "✅ **कस्टम थंबनेल सेट हो गया!**\n\n"
        "अब आप जितने भी वीडियो यहाँ **Forward** करेंगे, उन सभी में यह थंबनेल लगकर तुरंत वापस आ जाएगा।"
    )

@bot.on_message(filters.command("viewthumb") & filters.private)
async def view_thumbnail_handler(client: Client, message: Message):
    user_id = message.from_user.id
    thumb_path = USER_THUMBNAILS.get(user_id) or f"thumbnails/thumb_{user_id}.jpg"
    if os.path.exists(thumb_path):
        await message.reply_photo(photo=thumb_path, caption="🖼️ यह आपका वर्तमान कस्टम थंबनेल है।")
    else:
        await message.reply_text("⚠️ आपने अभी तक कोई थंबनेल सेट नहीं किया है! पहले मुझे कोई फोटो भेजें।")

@bot.on_message(filters.command("delthumb") & filters.private)
async def delete_thumbnail_handler(client: Client, message: Message):
    user_id = message.from_user.id
    thumb_path = USER_THUMBNAILS.get(user_id) or f"thumbnails/thumb_{user_id}.jpg"
    if os.path.exists(thumb_path):
        os.remove(thumb_path)
        USER_THUMBNAILS.pop(user_id, None)
        await message.reply_text("🗑️ कस्टम थंबनेल हटा दिया गया है।")
    else:
        await message.reply_text("⚠️ हटाने के लिए कोई थंबनेल नहीं मिला।")

@bot.on_message(filters.command("status") & filters.private)
async def status_handler(client: Client, message: Message):
    user_id = message.from_user.id
    queue = USER_QUEUES.get(user_id)
    count = queue.qsize() if queue else 0
    is_busy = PROCESSING_WORKERS.get(user_id, False)
    status_text = "प्रक्रिया चालू है (Processing)" if is_busy else "खाली (Idle)"
    await message.reply_text(f"📊 **कतार स्थिति:**\n• कतार में वीडियो: {count}\n• वर्तमान स्थिति: {status_text}")

async def process_user_video_queue(user_id: int):
    queue = USER_QUEUES[user_id]
    PROCESSING_WORKERS[user_id] = True

    while not queue.empty():
        msg = await queue.get()
        thumb_path = USER_THUMBNAILS.get(user_id) or f"thumbnails/thumb_{user_id}.jpg"
        
        video = msg.video
        caption = msg.caption or ""

        sent = False
        retries = 0
        while not sent and retries < 3:
            try:
                # Re-send video via existing Telegram file_id with the new thumbnail!
                await bot.send_video(
                    chat_id=user_id,
                    video=video.file_id,
                    caption=caption,
                    thumb=thumb_path if os.path.exists(thumb_path) else None,
                    duration=video.duration,
                    width=video.width,
                    height=video.height,
                    supports_streaming=True
                )
                sent = True
                # Safe FloodWait sleep
                await asyncio.sleep(FLOOD_SLEEP_DELAY)
            except FloodWait as e:
                logger.warning(f"FloodWait encountered: sleeping for {e.value} seconds")
                await asyncio.sleep(e.value + 1)
                retries += 1
            except Exception as err:
                logger.error(f"Error processing video for user {user_id}: {err}")
                await bot.send_message(user_id, f"⚠️ वीडियो प्रोसेस करने में त्रुटि: {err}")
                break

        queue.task_done()

    PROCESSING_WORKERS[user_id] = False

@bot.on_message(filters.video & filters.private)
async def video_forward_handler(client: Client, message: Message):
    user_id = message.from_user.id
    thumb_path = USER_THUMBNAILS.get(user_id) or f"thumbnails/thumb_{user_id}.jpg"

    if not os.path.exists(thumb_path):
        await message.reply_text(
            "⚠️ **कोई थंबनेल सेट नहीं है!**\n\n"
            "कृपया पहले मुझे वह फोटो भेजें जिसे आप थंबनेल बनाना चाहते हैं, फिर वीडियो फॉरवर्ड करें।"
        )
        return

    if user_id not in USER_QUEUES:
        USER_QUEUES[user_id] = asyncio.Queue()

    await USER_QUEUES[user_id].put(message)
    queue_size = USER_QUEUES[user_id].qsize()

    if not PROCESSING_WORKERS.get(user_id, False):
        asyncio.create_task(process_user_video_queue(user_id))
        await message.reply_text(f"⚡ वीडियो कतार में जोड़ा गया! कुल कतार: {queue_size}")

if __name__ == "__main__":
    logger.info("🚀 Starting Telegram Thumbnail Bot on Render...")
    bot.run()
