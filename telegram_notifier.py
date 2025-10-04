# telegram_notifier.py
import requests
from dotenv import load_dotenv
import os
import time

load_dotenv()  # read .env file if present

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
# CHAT_ID = "@nawthviper_hub"

# -------------------------------
# Quiet-mode settings
# -------------------------------
ALLOWED_PREFIXES = ("📥", "✅", "❌", "🔄", "📢")
QUIET_MODE = True

# -------------------------------
# Telegram retry settings
# -------------------------------
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


def send_telegram_message(message: str):
    """
    Sends a Telegram message with retry support.
    QUIET_MODE skips low-priority messages.
    """
    if QUIET_MODE and not message.startswith(ALLOWED_PREFIXES):
        print("[Telegram] Quiet mode: skipped message.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                print("[Telegram] Message sent.")
                return True
            else:
                print(f"[Telegram ERROR] Status {response.status_code}: {response.text}")
        except requests.RequestException as e:
            print(f"[Telegram ERROR] Attempt {attempt}: {e}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)
        else:
            print("[Telegram ERROR] Max retries reached. Skipping message.")
            return False
