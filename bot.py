import os
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from google import genai
from google.genai import types

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Global dictionary to maintain chat history per Telegram user/chat
CHAT_HISTORIES = {}
MAX_HISTORY_MESSAGES = 20  # Retains up to 10 back-and-forth turns per chat

# --- 1. Flask Keep-Alive Server for Render ---
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

# --- 2. System Instructions Loader (skill.md + references + Mode Routing Protocol) ---
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

# --- 3. Safety Settings (BLOCK_NONE for visual/art analysis) ---
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    CHAT_HISTORIES[chat_id] = []
    await update.message.reply_text(
        "Send me text, images, video clips, or audio files, and I will format them into a MiniMax H3 prompt.\n\n"
        "💡 Commands:\n"
        "/reset or /new — Clear chat memory to start a fresh project."
    )

async def reset_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    CHAT_HISTORIES[chat_id] = []
    await update.message.reply_text("🔄 Conversation memory cleared! Ready for a new prompt request.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    chat_id = update.effective_chat.id
    if chat_id not in CHAT_HISTORIES:
        CHAT_HISTORIES[chat_id] = []

    await message.reply_chat_action(action="typing")
    current_parts = []

    media_obj = None
    mime_type = None

    # Handle media types
    if message.photo:
        media_obj = message.photo[-1]
        mime_type = "image/jpeg"
    elif message.video:
        media_obj = message.video
        mime_type = message.video.mime_type or "video/mp4"
    elif message.video_note:
        media_obj = message.video_note
        mime_type = "video/mp4"
    elif message.audio:
        media_obj = message.audio
        mime_type = message.audio.mime_type or "audio/mpeg"
    elif message.voice:
        media_obj = message.voice
        mime_type = message.voice.mime_type or "audio/ogg"

    # Download byte stream for attached media
    if media_obj:
        file_info = await context.bot.get_file(media_obj.file_id)
        media_bytes = await file_info.download_as_bytearray()
        current_parts.append(
            types.Part.from_bytes(
                data=bytes(media_bytes),
                mime_type=mime_type
            )
        )

    # Process text or caption
    user_text = message.text or message.caption or (
        "Analyze this media input objectively and generate a MiniMax H3 prompt." if media_obj else ""
    )
    if user_text:
        current_parts.append(types.Part.from_text(text=user_text))

    if not current_parts:
        await message.reply_text("Please send text, an image, a video, or an audio file.")
        return

    # Add current turn to session history
    user_content = types.Content(role="user", parts=current_parts)
    CHAT_HISTORIES[chat_id].append(user_content)

    # Trim history buffer to prevent token overflow
    if len(CHAT_HISTORIES[chat_id]) > MAX_HISTORY_MESSAGES:
        CHAT_HISTORIES[chat_id] = CHAT_HISTORIES[chat_id][-MAX_HISTORY_MESSAGES:]

    try:
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTIONS,
            safety_settings=SAFETY_SETTINGS,
        )

        # Primary attempt with gemini-3.6-flash, fallback to gemini-2.0-flash on quota limit
        try:
            response = ai_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=CHAT_HISTORIES[chat_id],
                config=config,
            )
        except Exception as api_err:
            err_str = str(api_err)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                logging.warning("Gemini 3.6 Flash quota reached. Falling back to Gemini 2.0 Flash...")
                response = ai_client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=CHAT_HISTORIES[chat_id],
                    config=config,
                )
            else:
                raise api_err

        if response.text:
            model_content = types.Content(
                role="model",
                parts=[types.Part.from_text(text=response.text)]
            )
            CHAT_HISTORIES[chat_id].append(model_content)
            await message.reply_text(response.text)
        else:
            await message.reply_text("⚠️ No text output returned by the model.")

    except Exception as e:
        # Revert memory stack on API error
        if CHAT_HISTORIES[chat_id]:
            CHAT_HISTORIES[chat_id].pop()
        logging.error(f"Error generating content: {e}")
        await message.reply_text(f"⚠️ Error processing request: {e}")

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

    logging.info("Bot starting with full multimodal support, chat memory, mode routing, automatic model fallback, and keep-alive...")
    app.run_polling()

if __name__ == "__main__":
    main()
