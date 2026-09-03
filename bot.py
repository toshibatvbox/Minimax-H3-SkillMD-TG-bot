import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from google import genai

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Load skill.md rules
def load_skill_instructions():
    try:
        with open("skill.md", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logging.warning("skill.md not found! System instructions will be empty.")
        return ""

SKILL_INSTRUCTIONS = load_skill_instructions()

# Initialize Gemini Client
# Expects GEMINI_API_KEY set in environment variables
ai_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me your draft prompt or video details, and I will format it into a MiniMax H3 prompt."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_prompt = update.message.text
    await update.message.reply_chat_action(action="typing")

    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=user_prompt,
            config={
                "system_instruction": SKILL_INSTRUCTIONS,
            }
        )
        await update.message.reply_text(response.text)
    except Exception as e:
        logging.error(f"Error generating content: {e}")
        await update.message.reply_text("An error occurred while generating the prompt. Check logs for details.")

def main():
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set.")

    app = ApplicationBuilder().token(telegram_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logging.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
