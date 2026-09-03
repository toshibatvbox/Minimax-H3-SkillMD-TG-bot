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

# --- Flask Keep-Alive Server ---
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

# --- System Instructions Loading ---
def load_system_instructions():
    instructions = []
    
    # Load primary skill.md
    if os.path.exists("skill.md"):
        with open("skill.md", "r", encoding="utf-8") as f:
            instructions.append(f.read())
            
    # Load split reference files under Option B
    for ref_file in ["references/base-en.txt", "references/ref-en.txt"]:
        if os.path.exists(ref_file):
            with open(ref_file, "r", encoding="utf-8") as f:
                instructions.append(f.read())
                
    if not instructions:
        logging.warning("No instruction files found!")
        
    return "\n\n---\n\n".join(instructions)

SYSTEM_INSTRUCTIONS = load_system_instructions()
ai_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# --- Relaxed Safety Settings for Visual & Art Reading ---
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
    await update.message.reply_text(
        "Send me your draft prompt, video details, or an image with instructions, and I will format it into a MiniMax H3 prompt."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_chat_action(action="typing")

    contents = []

    # Handle attached image
    if update.message.photo:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        image_part = types.Part.from_bytes(
            data=bytes(photo_bytes),
            mime_type="image/jpeg"
        )
        contents.append(image_part)
        
        user_text = update.message.caption or (
            "Analyze this artwork objectively (composition, subject, aesthetic) "
            "and generate a MiniMax H3 prompt."
        )
        contents.append(user_text)
    else:
        # Handle text message
        contents.append(update.message.text)

    try:
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTIONS,
            safety_settings=SAFETY_SETTINGS,
        )

        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=config,
        )
        await update.message.reply_text(response.text)
    except Exception as e:
        logging.error(f"Error generating content: {e}")
        await update.message.reply_text("An error occurred while processing your request.")

def main():
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set.")

    # Start Flask background server for Render uptime check
    keep_alive()

    app = ApplicationBuilder().token(telegram_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_message))

    logging.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
