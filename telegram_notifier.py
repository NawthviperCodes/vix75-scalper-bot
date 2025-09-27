# telegram_notifier.py
import requests

from dotenv import load_dotenv
import os

load_dotenv()  # read .env file if present

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
# CHAT_ID = "@nawthviper_hub"

# -------------------------------
# Quiet-mode settings
# -------------------------------
# Only messages starting with one of these prefixes will be sent
ALLOWED_PREFIXES = ("📥", "✅", "❌", "🔄", "📢")
# Set to True to reduce chatter (recommended when hitting Telegram rate limits)
QUIET_MODE = True


def send_telegram_message(message: str):
    """
    Sends a Telegram message.  When QUIET_MODE is True,
    only high-priority messages (matching ALLOWED_PREFIXES)
    are actually sent to Telegram.
    """
    if QUIET_MODE:
        if not message.startswith(ALLOWED_PREFIXES):
            # Low-priority message; skip sending
            print("[Telegram] Quiet mode: skipped message.")
            return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"[Telegram ERROR] {response.text}")
        else:
            print("[Telegram] Message sent.")
    except Exception as e:
        print(f"[Telegram ERROR] {e}")
