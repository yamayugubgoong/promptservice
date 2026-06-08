import os
import json
import logging
import asyncio
import httpx
from anthropic import AsyncAnthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from dotenv import load_dotenv

load_dotenv()

# --- Config ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "0"))  # group สำหรับ broadcast
USERS_FILE = "known_users.json"

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Clients ---
claude_client = AsyncAnthropic(api_key=CLAUDE_API_KEY)

# --- State ---
user_state: dict[int, str] = {}


# ─────────────────────────────────────────
# Known Users (persistent)
# ─────────────────────────────────────────

def load_known_users() -> set[int]:
    """โหลด user_ids จาก file"""
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_known_users(users: set[int]):
    """บันทึก user_ids ลง file"""
    with open(USERS_FILE, "w") as f:
        json.dump(list(users), f)

known_users: set[int] = load_known_users()


# ─────────────────────────────────────────
# Broadcast
# ─────────────────────────────────────────

async def broadcast(app, message: str):
    """ส่งข้อความไปทุกที่ — admin, group, และ user ทุกคน"""
    targets = set()

    # admin
    if ADMIN_CHAT_ID:
        targets.add(ADMIN_CHAT_ID)

    # group
    if GROUP_CHAT_ID:
        targets.add(GROUP_CHAT_ID)

    # user ทุกคนที่เคย /start
    targets.update(known_users)

    for chat_id in targets:
        try:
            await app.bot.send_message(chat_id=chat_id, text=message)
            await asyncio.sleep(0.05)  # หลีกเลี่ยง rate limit
        except Exception as e:
            logger.warning(f"Broadcast failed for {chat_id}: {e}")


async def notify_admin(app, message: str):
    """ส่งแค่ admin คนเดียว (สำหรับ error ที่ไม่ต้องบอกทุกคน)"""
    if ADMIN_CHAT_ID:
        try:
            await app.bot.send_message(chat_id=ADMIN_CHAT_ID, text=message)
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")


# ─────────────────────────────────────────
# Startup / Error
# ─────────────────────────────────────────

async def on_startup(app):
    await notify_admin(app, "✅ Bot เริ่มทำงานแล้ว")


async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception: {context.error}")
    await notify_admin(
        context.application,
        f"🚨 Bot Error!\n\n{type(context.error).__name__}: {str(context.error)[:300]}"
    )


# ─────────────────────────────────────────
# AI Functions
# ─────────────────────────────────────────

async def call_perplexity(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "sonar",
        "messages": [{"role": "user", "content": prompt}],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.perplexity.ai/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


async def call_claude(prompt: str) -> str:
    message = await claude_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ─────────────────────────────────────────
# Keyboards
# ─────────────────────────────────────────

def choose_ai_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Perplexity", callback_data="ai:perplexity"),
            InlineKeyboardButton("🤖 Claude", callback_data="ai:claude"),
        ]
    ])


def next_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 ส่งต่อ Perplexity", callback_data="ai:perplexity"),
            InlineKeyboardButton("🤖 ส่งต่อ Claude", callback_data="ai:claude"),
        ],
        [InlineKeyboardButton("✅ จบ", callback_data="ai:done")],
    ])


# ─────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    # บันทึก user ลง file
    if user_id not in known_users:
        known_users.add(user_id)
        save_known_users(known_users)
        logger.info(f"New user: {user_id} @{update.message.from_user.username}")

    await update.message.reply_text(
        "👋 สวัสดี!\n\nพิมพ์ prompt ได้เลย แล้วเลือกว่าจะส่งให้ AI ไหน\n"
        "จากนั้นเลือกได้ว่าจะส่ง output ต่อให้ใครอีก หรือจบเลย\n\n"
        "พิมพ์ /help เพื่อดูคำสั่งทั้งหมด"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 วิธีใช้งาน\n\n"
        "1. พิมพ์ prompt ที่ต้องการ\n"
        "2. เลือกว่าจะให้ Perplexity หรือ Claude ตอบ\n"
        "3. พอได้คำตอบแล้ว เลือกส่งต่อให้ AI อีกตัว หรือกด จบ\n\n"
        "คำสั่ง:\n"
        "/help — แสดงวิธีใช้งาน\n"
        "/clear — ล้าง prompt ปัจจุบัน เริ่มใหม่ได้เลย\n"
        "/retry — ส่ง prompt เดิมซ้ำอีกครั้ง\n"
        "/ping — ทดสอบว่า AI ทุกตัวพร้อมใช้งานไหม"
    )


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in user_state:
        user_state.pop(user_id)
        await update.message.reply_text("🧹 ล้างแล้ว พิมพ์ prompt ใหม่ได้เลย")
    else:
        await update.message.reply_text("ไม่มี prompt ค้างอยู่ พิมพ์ได้เลย")


async def cmd_retry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    last = user_state.get(user_id)

    if not last:
        await update.message.reply_text("❌ ไม่มี prompt ก่อนหน้า พิมพ์ใหม่ได้เลย")
        return

    preview = last[:120] + "..." if len(last) > 120 else last
    await update.message.reply_text(
        f"🔁 ส่งซ้ำ:\n{preview}\n\nส่งให้ใคร?",
        reply_markup=choose_ai_keyboard(),
    )


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔄 กำลังทดสอบ AI ทุกตัว...")
    results = {}

    try:
        await call_perplexity("reply with only the word: pong")
        results["Perplexity"] = "✅ OK"
    except Exception as e:
        results["Perplexity"] = f"❌ {str(e)[:80]}"

    try:
        await call_claude("reply with only the word: pong")
        results["Claude"] = "✅ OK"
    except Exception as e:
        results["Claude"] = f"❌ {str(e)[:80]}"

    report = "\n".join([f"{ai}: {status}" for ai, status in results.items()])
    await msg.edit_text(f"🏓 Ping Results:\n\n{report}")


async def cmd_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin เท่านั้น — broadcast ข้อความถึงทุกคน"""
    user_id = update.message.from_user.id

    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ คำสั่งนี้ใช้ได้เฉพาะ admin")
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Usage: /announce ข้อความที่จะส่ง")
        return

    await update.message.reply_text(f"📢 กำลัง broadcast...")
    await broadcast(context.application, f"📢 ประกาศ:\n\n{text}")
    await update.message.reply_text(f"✅ ส่งถึง {len(known_users)} user แล้ว")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    prompt = update.message.text

    user_state[user_id] = prompt
    logger.info(f"[{user_id}] @{update.message.from_user.username} prompt: {prompt[:80]}")

    preview = prompt[:120] + "..." if len(prompt) > 120 else prompt
    await update.message.reply_text(
        f"📝 *Prompt:*\n{preview}\n\nส่งให้ใคร?",
        reply_markup=choose_ai_keyboard(),
        parse_mode="Markdown",
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    action = query.data

    if action == "ai:done":
        await query.edit_message_text("✅ จบแล้ว! พิมพ์ prompt ใหม่ได้เลย")
        user_state.pop(user_id, None)
        return

    current_input = user_state.get(user_id)
    if not current_input:
        await query.edit_message_text("❌ หมด context แล้ว กรุณาพิมพ์ prompt ใหม่")
        return

    ai_name = "Perplexity" if action == "ai:perplexity" else "Claude"
    await query.edit_message_text(f"⏳ กำลังส่งให้ {ai_name}...")

    try:
        if ai_name == "Perplexity":
            result = await call_perplexity(current_input)
        else:
            result = await call_claude(current_input)

        user_state[user_id] = result
        logger.info(f"[{user_id}] {ai_name} responded ({len(result)} chars)")

        chunks = [result[i:i+3800] for i in range(0, len(result), 3800)]
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            suffix = f"\n\n_(ส่วนที่ {i+1}/{len(chunks)})_" if len(chunks) > 1 else ""
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"✨ *ผลจาก {ai_name}:*\n\n{chunk}{suffix}",
                reply_markup=next_action_keyboard() if is_last else None,
                parse_mode="Markdown",
            )

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ API Error ({e.response.status_code}): {e.response.text[:200]}",
        )
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ เกิดข้อผิดพลาด: {str(e)}",
        )


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(on_startup).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("retry", cmd_retry))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("announce", cmd_announce))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(error_handler)

    logger.info("🤖 Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
