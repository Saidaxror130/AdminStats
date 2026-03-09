import logging
import requests
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("GOOGLE_API_KEY")
REGISTRY_ID = os.getenv("REGISTRY_SPREADSHEET_ID")

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен")
if not API_KEY:
    raise ValueError("GOOGLE_API_KEY не установлен")
if not REGISTRY_ID:
    raise ValueError("REGISTRY_SPREADSHEET_ID не установлен")

# ================= NORMALIZE =================

def normalize_id(value):
    if value is None:
        return ""
    return (
        str(value)
        .replace(",", "")
        .replace(" ", "")
        .replace("\xa0", "")
        .strip()
    )

# ================= HELPERS =================

def load_sheet_values(api_url: str):
    try:
        response = requests.get(api_url, timeout=20)
        response.raise_for_status()
        data = response.json()
        return data.get("values", [])
    except Exception as e:
        logging.error(f"Ошибка загрузки {api_url}: {e}")
        return []


def load_records(api_url: str):
    values = load_sheet_values(api_url)

    if not values:
        return []

    headers = values[0]

    records = []

    for row in values[1:]:
        record = dict(zip(headers, row))
        records.append(record)

    return records

# ================= REGISTRY =================

def get_registry_ids(registry_spreadsheet_id: str):

    api_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{registry_spreadsheet_id}"
        f"/values/A2:A?key={API_KEY}"
    )

    values = load_sheet_values(api_url)

    ids = []

    for row in values:
        if row and row[0]:
            ids.append(row[0].strip())

    logging.info(f"Загружено {len(ids)} таблиц территорий")

    return ids

SHEET_IDS = get_registry_ids(REGISTRY_ID)

# ================= CACHE =================

ADMIN_CACHE = {}
MFU_CACHE = {}


def build_role_url(spreadsheet_id: str, role: str):

    sheet_name = "Администраторы" if role == "admin" else "МФУ"

    return (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        f"/values/{sheet_name}!A1:Z1000?key={API_KEY}"
    )


def build_cache():

    logging.info("Обновляем кэш сотрудников...")

    ADMIN_CACHE.clear()
    MFU_CACHE.clear()

    for spreadsheet_id in SHEET_IDS:

        for role in ["admin", "mfu"]:

            api_url = build_role_url(spreadsheet_id, role)

            records = load_records(api_url)

            if not records:
                continue

            for row in records:

                emp_id = normalize_id(row.get("Табельный номер"))

                if not emp_id:
                    continue

                data = {
                    "fio": row.get("ФИО", "N/A"),
                    "pvz": row.get("ПВЗ", "N/A"),
                    "fact": row.get("Факт", "N/A"),
                    "open_limits": row.get("Открыто Лимитов", "N/A"),
                    "plan_limits": row.get("План по лимитам", "N/A"),
                    "execution": row.get("Выполнение плана по лимитам", "N/A"),
                    "virtual_cards": row.get(" 📱Оформленно виртуальных карт", "N/A"),
                    "plastic_cards": row.get("💷Оформленно пластиковых карт", "N/A"),
                    "vchl": row.get("ВЧЛ", "N/A"),
                }

                if role == "admin":
                    ADMIN_CACHE[emp_id] = data
                else:
                    MFU_CACHE[emp_id] = data

    logging.info(f"Админов в кэше: {len(ADMIN_CACHE)}")
    logging.info(f"МФУ в кэше: {len(MFU_CACHE)}")


# первая загрузка при запуске
build_cache()

# ================= STATES =================

SELECT_ROLE, ENTER_ID = range(2)

# ================= HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [InlineKeyboardButton("Админ", callback_data="admin")],
        [InlineKeyboardButton("МФУ (Менеджер финансовых услуг)", callback_data="mfu")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Привет! Я бот для просмотра показателей сотрудников.\n\nВыберите вашу должность:",
        reply_markup=reply_markup,
    )

    return SELECT_ROLE


async def select_role(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    role = query.data

    context.user_data["role"] = role

    await query.edit_message_text("Введите табельный номер:")

    return ENTER_ID


async def enter_id(update: Update, context: ContextTypes.DEFAULT_TYPE):

    employee_id = normalize_id(update.message.text)

    role = context.user_data.get("role")

    if role == "admin":
        data = ADMIN_CACHE.get(employee_id)
    else:
        data = MFU_CACHE.get(employee_id)

    if data:

        if role == "admin":

            text = f"""*ФИО:* {data['fio']}
*ПВЗ:* {data['pvz']}

*Факт часов:* {data['fact']}

*Кол. открытых лимитов:* {data['open_limits']}
*План по лимитам:* {data['plan_limits']}
*Выполнение плана:* {data['execution']}

*Оформленные виртуальные карты:* {data['virtual_cards']}
*Оформленные пластиковые карты:* {data['plastic_cards']}

*ВЧЛ:* {data['vchl']}"""

        else:

            text = f"""*ФИО:* {data['fio']}
*ПВЗ:* {data['pvz']}

*Факт часов:* {data['fact']}

*Оформленные виртуальные карты:* {data['virtual_cards']}
*Оформленные пластиковые карты:* {data['plastic_cards']}

*ВЧЛ:* {data['vchl']}"""

        keyboard = [
            [InlineKeyboardButton("Админ", callback_data="admin")],
            [InlineKeyboardButton("МФУ (Менеджер финансовых услуг)", callback_data="mfu")],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

        return SELECT_ROLE

    else:

        await update.message.reply_text(
            "❌ Табельный номер не найден. Попробуйте снова:"
        )

        return ENTER_ID

# ================= MAIN =================

if __name__ == "__main__":

    application = ApplicationBuilder().token(TOKEN).build()

    # автообновление кэша каждые 10 минут
    async def refresh_cache(context: ContextTypes.DEFAULT_TYPE):
        logging.info("Автообновление данных (10 минут)...")
        build_cache()

    application.job_queue.run_repeating(refresh_cache, interval=600, first=600)

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_ROLE: [CallbackQueryHandler(select_role)],
            ENTER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_id)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    application.add_handler(conv_handler)

    application.run_polling()
