from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = "YOUR_NEW_BOT_TOKEN"  # Use your bot token here

# Whitelist of authorized user IDs (your friends)
AUTHORIZED_USERS = {123456789, 987654321}  # Replace with actual Telegram user IDs

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text(
            "🚫 You are not authorized to use this bot.\n"
            "Please contact the bot owner for access."
        )
        return
    await update.message.reply_text(f"✅ Welcome, authorized user!\nUse /help for commands.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("🚫 Unauthorized access.")
        return
    await update.message.reply_text(
        "Available commands:\n"
        "/status - Show bot status\n"
        "/summary - Get daily trading summary"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("🚫 Unauthorized access.")
        return
    # Here you can add real status info
    await update.message.reply_text("🤖 Bot is running fine!")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USERS:
        # Optionally ignore or warn unauthorized users
        return
    await update.message.reply_text("❓ Sorry, I didn't understand that command.")

def send_message_to_authorized_users(application, text):
    for user_id in AUTHORIZED_USERS:
        application.bot.send_message(chat_id=user_id, text=text)

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("Bot is running...")
    app.run_polling()
