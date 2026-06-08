import os
import logging
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

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Clients ---
claude_client = AsyncAnthropic(api_key=CLAUDE_API_KEY)

# --- State (user_id -> last output) ---
# เก็บ output ล่าสุดของแต่ละ user เพื่อส่งต่อให้ AI ถัดไป
user_state: dict[int, str] = {}


# ─────────────────────────────────────────
# AI Functions
# ─────────────────────────────────────────

async def call_perplexity(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "llama-3.1-sonar-large-128k-online",
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
    """ปุ่มเลือก AI ครั้งแรก"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Perplexity", callback_data="ai:perplexity"),
            InlineKeyboardButton("🤖 Claude", callback_data="ai:claude"),
        ]
    ])


def next_action_keyboard() -> InlineKeyboardMarkup:
    """ปุ่มหลังได้ผลลัพธ์ — ส่งต่อหรือจบ"""
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
    await update.message.reply_text(
        "👋 สวัสดี!\n\nพิมพ์ prompt ได้เลย แล้วเลือกว่าจะส่งให้ AI ไหน\n"
        "จากนั้นเลือกได้ว่าจะส่ง output ต่อให้ใครอีก หรือจบเลย"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    prompt = update.message.text

    # เก็บ prompt เป็น input เริ่มต้น
    user_state[user_id] = prompt

    # Log
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
    action = query.data  # "ai:perplexity" | "ai:claude" | "ai:done"

    # จบ
    if action == "ai:done":
        await query.edit_message_text("✅ จบแล้ว! พิมพ์ prompt ใหม่ได้เลย")
        user_state.pop(user_id, None)
        return

    # ดึง input ปัจจุบัน
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

        # อัปเดต state เป็น output ล่าสุด (ใช้ส่งต่อรอบหน้า)
        user_state[user_id] = result

        # Log
        logger.info(f"[{user_id}] {ai_name} responded ({len(result)} chars)")

        # Telegram จำกัด 4096 ตัวอักษรต่อ message
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
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("🤖 Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
