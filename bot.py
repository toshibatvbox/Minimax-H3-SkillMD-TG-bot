import os
import logging
import threading
import asyncio
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from google import genai
from google.genai import types

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

CHAT_HISTORIES = {}
MAX_HISTORY_MESSAGES = 20

# Active Media Storage per chat to prevent vision context decay on follow-up texts
LAST_MEDIA = {}
MEDIA_GROUPS = {}

# --- 1. Flask Keep-Alive Server ---
web_app = Flask('')

@web_app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()

# --- 2. System Instructions ---
MODE_ROUTING_PROTOCOL = """
=== CRITICAL MODE SELECTION DECISION TREE ===
You MUST strictly select the correct MiniMax H3 mode based on user inputs unless the user explicitly specifies otherwise:

1. DEFAULT IMAGE-TO-VIDEO (I2VA):
   - TRIGGER: User sends EXACTLY 1 Image + text prompt.
   - OUTPUT FORMAT: Must ONLY use Base Mode fields:
     integrated_multimodal_description: ...
     overall_soundscape: ...
     non_diegetic_music: ...
   - DO NOT include `subject_definitions`, `retention_analysis`, or `summary` unless the user explicitly requests "Ref2VA" or "Reference Mode".

2. FULL-REFERENCE MODE (Ref2VA):
   - TRIGGER: User explicitly types "ref", "Ref2VA", "reference mode", or provides multiple character reference photos.
   - OUTPUT FORMAT: Uses full reference fields (`subject_definitions`, `retention_analysis`, `detailed_description`, `overall_soundscape`, `non_diegetic_music`).

3. TEXT-TO-VIDEO (T2VA):
   - TRIGGER: User sends text only (0 images).
   - OUTPUT FORMAT: Uses standard Base Mode fields (`integrated_multimodal_description`, `overall_soundscape`, `non_diegetic_music`).

4. FIRST & LAST FRAME (FL2VA):
   - TRIGGER: User sends EXACTLY 2 images.
   - OUTPUT FORMAT: Must reference <Picture 1> at 0.00s as initial frame and <Picture 2> as final frame. Uses Base Mode fields (`integrated_multimodal_description`, `overall_soundscape`, `non_diegetic_music`).
=============================================
"""

def load_system_instructions():
    instructions = [MODE_ROUTING_PROTOCOL]
    if os.path.exists("skill.md"):
        with open("skill.md", "r", encoding="utf-8") as f:
            instructions.append(f.read())
            
    for ref_file in ["references/base-en.txt", "references/ref-en.txt"]:
        if os.path.exists(ref_file):
            with open(ref_file, "r", encoding="utf-8") as f:
                instructions.append(f.read())
                
    if not instructions:
        logging.warning("No instruction files found!")
        
    return "\n\n---\n\n".join(instructions)

SYSTEM_INSTRUCTIONS = load_system_instructions()
ai_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

SAFETY_SETTINGS = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
]

FALLBACK_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-pro"
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    CHAT_HISTORIES[chat_id] = []
    LAST_MEDIA[chat_id] = []
    await update.message.reply_text(
        "Send me text, images, video clips, or audio files, and I will format them into a MiniMax H3 prompt.\n\n"
        "💡 Commands:\n"
        "/reset or /new — Clear chat memory to start a fresh project."
    )

async def reset_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    CHAT_HISTORIES[chat_id] = []
    LAST_MEDIA[chat_id] = []
    await update.message.reply_text("🔄 Project state and media memory cleared!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    chat_id = update.effective_chat.id
    if chat_id not in CHAT_HISTORIES:
        CHAT_HISTORIES[chat_id] = []

    await message.reply_chat_action(action="typing")

    media_group_id = message.media_group_id
    new_media_parts = []

    # Handle multi-photo album uploads
    if media_group_id:
        if media_group_id not in MEDIA_GROUPS:
            MEDIA_GROUPS[media_group_id] = {
                "parts": [],
                "text": "",
                "lock": asyncio.Lock(),
                "processed": False
            }

        group = MEDIA_GROUPS[media_group_id]

        part = None
        if message.photo:
            file_info = await context.bot.get_file(message.photo[-1].file_id)
            media_bytes = await file_info.download_as_bytearray()
            part = types.Part.from_bytes(data=bytes(media_bytes), mime_type="image/jpeg")
        elif message.video:
            file_info = await context.bot.get_file(message.video.file_id)
            media_bytes = await file_info.download_as_bytearray()
            part = types.Part.from_bytes(data=bytes(media_bytes), mime_type=message.video.mime_type or "video/mp4")

        caption = message.text or message.caption

        async with group["lock"]:
            if part:
                group["parts"].append(part)
            if caption:
                group["text"] = caption

        await asyncio.sleep(2.0)

        async with group["lock"]:
            if group["processed"]:
                return
            group["processed"] = True

        group_data = MEDIA_GROUPS.pop(media_group_id, None)
        if not group_data or not group_data["parts"]:
            return

        new_media_parts = group_data["parts"]
        user_text = group_data["text"] or "Analyze these media inputs objectively and generate a MiniMax H3 prompt."

    else:
        part = None
        mime_type = None

        if message.photo:
            file_info = await context.bot.get_file(message.photo[-1].file_id)
            media_bytes = await file_info.download_as_bytearray()
            part = types.Part.from_bytes(data=bytes(media_bytes), mime_type="image/jpeg")
        elif message.video:
            file_info = await context.bot.get_file(message.video.file_id)
            media_bytes = await file_info.download_as_bytearray()
            part = types.Part.from_bytes(data=bytes(media_bytes), mime_type=message.video.mime_type or "video/mp4")
        elif message.video_note:
            file_info = await context.bot.get_file(message.video_note.file_id)
            media_bytes = await file_info.download_as_bytearray()
            part = types.Part.from_bytes(data=bytes(media_bytes), mime_type="video/mp4")

        if part:
            new_media_parts.append(part)

        user_text = message.text or message.caption or ""

    # Update active project media if new media was sent, else re-use active project media
    if new_media_parts:
        LAST_MEDIA[chat_id] = new_media_parts
        active_media = new_media_parts
    else:
        active_media = LAST_MEDIA.get(chat_id, [])

    if not active_media and not user_text:
        await message.reply_text("Please send text, an image, or a video.")
        return

    # Construct request payload with active media anchor + user prompt
    current_parts = list(active_media)
    if user_text:
        current_parts.append(types.Part.from_text(text=user_text))

    user_content = types.Content(role="user", parts=current_parts)
    CHAT_HISTORIES[chat_id].append(user_content)

    if len(CHAT_HISTORIES[chat_id]) > MAX_HISTORY_MESSAGES:
        CHAT_HISTORIES[chat_id] = CHAT_HISTORIES[chat_id][-MAX_HISTORY_MESSAGES:]

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTIONS,
        safety_settings=SAFETY_SETTINGS,
    )

    response = None
    last_error = None

    for model_name in FALLBACK_MODELS:
        try:
            response = ai_client.models.generate_content(
                model=model_name,
                contents=CHAT_HISTORIES[chat_id],
                config=config,
            )
            if response and response.text:
                logging.info(f"Generated response using {model_name}")
                break
        except Exception as api_err:
            last_error = api_err
            logging.warning(f"Model {model_name} failed: {api_err}")
            continue

    if response and response.text:
        model_content = types.Content(
            role="model",
            parts=[types.Part.from_text(text=response.text)]
        )
        CHAT_HISTORIES[chat_id].append(model_content)
        await message.reply_text(response.text)
    else:
        if CHAT_HISTORIES[chat_id]:
            CHAT_HISTORIES[chat_id].pop()
        logging.error(f"All models failed: {last_error}")
        await message.reply_text(f"⚠️ API Error: {last_error}")

def main():
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set.")

    keep_alive()

    app = ApplicationBuilder().token(telegram_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset_chat))
    app.add_handler(CommandHandler("new", reset_chat))

    media_filters = (
        filters.TEXT | 
        filters.PHOTO | 
        filters.VIDEO | 
        filters.VIDEO_NOTE | 
        filters.AUDIO | 
        filters.VOICE
    ) & ~filters.COMMAND

    app.add_handler(MessageHandler(media_filters, handle_message))

    logging.info("Bot running with media anchor retention...")
    app.run_polling()

if __name__ == "__main__":
    main()
