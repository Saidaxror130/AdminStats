import os

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("GOOGLE_API_KEY")
REGISTRY_ID = os.getenv("REGISTRY_SPREADSHEET_ID")
ADMIN_ID = os.getenv("ADMIN_BOT_ID")

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_MINUTES", "10")) * 60
RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "10"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))
SUSPICIOUS_DIFF_IDS = int(os.getenv("SUSPICIOUS_DIFF_IDS", "5"))

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен ⚠️")
if not API_KEY:
    raise ValueError("GOOGLE_API_KEY не установлен ⚠️")
if not REGISTRY_ID:
    raise ValueError("REGISTRY_SPREADSHEET_ID не установлен ⚠️")
if not ADMIN_ID:
    raise ValueError("ADMIN_BOT_ID не установлен ⚠️")
