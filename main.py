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

# ================= LOGGING =================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ================= ENV =================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("GOOGLE_API_KEY")
REGISTRY_ID = os.getenv("REGISTRY_SPREADSHEET_ID")
ADMIN_ID = os.getenv("ADMIN_BOT_ID")

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен ⚠️")
if not API_KEY:
    raise ValueError("GOOGLE_API_KEY не установлен ⚠️")
if not REGISTRY_ID:
    raise ValueError("REGISTRY_SPREADSHEET_ID не установлен ⚠️")
if not ADMIN_ID:
    raise ValueError("ADMIN_BOT_ID не установлен ⚠️")

# ================= ADMIN ALERT =================

def send_admin_message(text):

    try:

        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

        requests.post(
            url,
            json={
                "chat_id": ADMIN_ID,
                "text": text
            },
            timeout=10
        )

    except Exception as e:
        logging.error(f"Не удалось отправить сообщение админу: {e}")


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

        response = requests.get(api_url, timeout=15)
        response.raise_for_status()

        data = response.json()

        return data.get("values", [])

    except requests.exceptions.HTTPError as e:

        error_text = f"""
🚨 Ошибка Google API

URL:
{api_url}

Status:
{e.response.status_code}

Ответ:
{e.response.text}
"""

        logging.error(error_text)
        send_admin_message(error_text)

        return []

    except Exception as e:

        error_text = f"""
🚨 Ошибка загрузки таблицы

URL:
{api_url}

Ошибка:
{e}
"""

        logging.error(error_text)
        send_admin_message(error_text)

        return []


def load_records(api_url: str):

    values = load_sheet_values(api_url)

    if not values:

        msg = "⚠️ Таблица пустая или не загрузилась"

        logging.warning(msg)
        send_admin_message(msg)

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

    logging.info(f"Загружено {len(ids)} spreadsheet_id из реестра")

    return ids


SHEET_IDS = get_registry_ids(REGISTRY_ID)


# ================= SEARCH =================

def build_role_url(spreadsheet_id: str, role: str):

    sheet_name = "Администраторы" if role == "admin" else "МФУ"

    return (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        f"/values/{sheet_name}!A2:Z1000?key={API_KEY}"
    )


def get_employee_data(employee_id, records):

    employee_id = normalize_id(employee_id)

    for row in records:

        table_id = normalize_id(row.get("Табельный номер", ""))

        if table_id == employee_id:

            logging.info(
                f"🎉Успешно найден сотрудник {employee_id} в таблице, {row.get('ПВЗ', 'N/A')} ({row.get('ФИО', 'N/A')})"
            )

            return {
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

    return None


def find_employee_across_sheets(employee_id: str, role: str):

    logging.info(f"🔍Начинаем поиск {employee_id}")

    if not SHEET_IDS:

        logging.error("Реестр таблиц пустой")
        send_admin_message("🚨 Реестр таблиц пустой")

        return None

    for spreadsheet_id in SHEET_IDS:

        try:

            api_url = build_role_url(spreadsheet_id, role)

            records = load_records(api_url)

            if not records:
                continue

            data = get_employee_data(employee_id, records)

            if data:
                return data

        except Exception as e:

            error = f"""
🚨 Ошибка проверки таблицы

Spreadsheet:
{spreadsheet_id}

Ошибка:
{e}
"""

            logging.error(error)
            send_admin_message(error)

    logging.warning(f"{employee_id} не найден ни в одной таблице❌")

    return None


# ================= STATES =================

SELECT_ROLE, ENTER_ID = range(2)


# ================= HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [InlineKeyboardButton("Админ", callback_data="admin")],
        [InlineKeyboardButton("МФУ", callback_data="mfu")],
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

    try:

        employee_id = normalize_id(update.message.text)

        role = context.user_data.get("role")

        data = find_employee_across_sheets(employee_id, role)

        if data:

            if role == "admin":

                text = f"""ФИО: {data['fio']}
*ПВЗ:* {data['pvz']}

*Факт часов:* {data['fact']} ⏱️

*Кол. открытых лимитов:* {data['open_limits']} ☑️
*План по лимитам:* {data['plan_limits']} 📋
*Выполнение плана:* {data['execution']}

*Виртуальные карты:* {data['virtual_cards']} 💷
*Пластиковые карты:* {data['plastic_cards']} 💳

*ВЧЛ:* {data['vchl']}

Выберите должность для нового поиска:"""
            else:

                text = f"""ФИО: {data['fio']}
*ПВЗ:* {data['pvz']}

*Факт часов:* {data['fact']} ⏱️

*ВИРТУАЛЬНЫЕ карты:* {data['virtual_cards']} 💷
*ПЛАСТИКОВЫЕ карты:* {data['plastic_cards']} 💳

*ВЧЛ:* {data['vchl']}

Выберите должность для нового поиска:"""
                
            keyboard = [
                [InlineKeyboardButton("Админ", callback_data="admin")],
                [InlineKeyboardButton("МФУ", callback_data="mfu")],
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                text, parse_mode="Markdown", reply_markup=reply_markup
            )

            return SELECT_ROLE

        else:

            await update.message.reply_text(
                "❌ Табельный номер не найден. \n\nВведите табельный номер:"
            )

            return ENTER_ID

    except Exception as e:

        error = f"""
🚨 Ошибка обработки запроса

User:
{update.effective_user.id}

Сообщение:
{update.message.text}

Ошибка:
{e}
"""

        logging.error(error)
        send_admin_message(error)

        await update.message.reply_text("Произошла ошибка!. \n\nПопробуйте снова. /start")

        return SELECT_ROLE


# ================= GLOBAL ERROR =================

async def error_handler(update, context):

    error = f"""
🚨 GLOBAL ERROR

Update:
{update}

Error:
{context.error}
"""

    logging.error(error)
    send_admin_message(error)


# ================= MAIN =================

if __name__ == "__main__":

    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_ROLE: [CallbackQueryHandler(select_role)],
            ENTER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_id)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    application.add_handler(conv_handler)

    application.add_error_handler(error_handler)

    send_admin_message("🤖 Бот запущен")

    application.run_polling()
