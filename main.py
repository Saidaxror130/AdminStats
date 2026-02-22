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

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен")
if not API_KEY:
    raise ValueError("GOOGLE_API_KEY не установлен")
if not REGISTRY_ID:
    raise ValueError("REGISTRY_SPREADSHEET_ID не установлен")

# ================= HELPERS =================

def load_sheet_values(api_url: str):
    try:
        response = requests.get(api_url, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data.get("values", [])
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP ошибка {e.response.status_code}: {e.response.text}")
        return []
    except Exception as e:
        logging.error(f"Ошибка загрузки {api_url}: {e}")
        return []


def load_records(api_url: str):
    values = load_sheet_values(api_url)
    if not values:
        logging.warning("Таблица пуста!")
        return []

    headers = values[0]
    logging.debug(f"Headers: {headers}")
    records = []
    for i, row in enumerate(values[1:], 1):
        record = dict(zip(headers, row))
        records.append(record)
        if i <= 2:  # Логируем первые 2 строки для дебага
            logging.debug(f"Row {i}: {record}")
    
    logging.info(f"Загружено {len(records)} записей из таблицы")
    return records


# ================= REGISTRY =================

def get_registry_ids(registry_spreadsheet_id: str):
    """
    Читает таблицу-реестр и возвращает список spreadsheet_id из колонки A.
    """
    api_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{registry_spreadsheet_id}"
        f"/values/A2:A?key={API_KEY}"
    )

    logging.info(f"Запрос к API: {api_url[:100]}...")
    values = load_sheet_values(api_url)
    logging.info(f"Полученные значения: {values}")

    ids = []
    for row in values:
        if row and row[0]:
            ids.append(row[0].strip())

    logging.info(f"Загружено {len(ids)} spreadsheet_id из реестра")
    if not ids:
        logging.warning("⚠️ ВНИМАНИЕ: Реестр пустой! Проверьте REGISTRY_SPREADSHEET_ID и доступ к Google Sheets")
    return ids


# Загружаем список территорий один раз
SHEET_IDS = get_registry_ids(REGISTRY_ID)


# ================= SEARCH =================

def build_role_url(spreadsheet_id: str, role: str):
    sheet_name = "Администраторы" if role == "admin" else "МФУ"

    return (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        f"/values/{sheet_name}!A2:Z1000?key={API_KEY}"
    )


def get_employee_data(employee_id, records):
    if not records:
        logging.warning(f"Records пусто для поиска {employee_id}")
        return None

    for i, row in enumerate(records[:3]):  # Логируем первые 3 строки
        logging.debug(f"Проверяем row {i}: keys={list(row.keys())}")
    
    for row in records:
        table_id = str(row.get("Табельный номер", "")).replace(",", "")
        if table_id == employee_id:
            logging.info(f"✅ Найдена инф. для сотрудника {employee_id}")
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
    """
    Один loop по территориям.
    Внутри выбирается нужный лист по роли.
    """
    logging.info(f"Начинаем поиск {employee_id} в роли {role}. SHEET_IDS={SHEET_IDS}")
    
    if not SHEET_IDS:
        logging.error("❌ SHEET_IDS пустой! Реестр не загружена")
        return None
    
    for idx, spreadsheet_id in enumerate(SHEET_IDS, 1):
        try:
            api_url = build_role_url(spreadsheet_id, role)
            logging.info(f"[{idx}/{len(SHEET_IDS)}] Проверяем таблицу {spreadsheet_id[:20]}... ({role})")

            records = load_records(api_url)
            if not records:
                logging.warning(f"  Таблица {spreadsheet_id[:20]}... пустая")
                continue
            
            data = get_employee_data(employee_id, records)

            if data:
                logging.info(f"🎉 Найден сотрудник в {spreadsheet_id[:20]}...")
                return data  # ✅ BREAK
            else:
                logging.debug(f"  {employee_id} не найдена в этой таблице")

        except Exception as e:
            logging.error(f"Ошибка при проверке {spreadsheet_id}: {e}", exc_info=True)
            continue

    logging.warning(f"❌ {employee_id} не найдена ни в одной таблице")
    return None


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
    try:
        employee_id = update.message.text.strip().replace(",", "")
        role = context.user_data.get("role")

        logging.info(f"Поиск ID: {employee_id}, роль: {role}")

        data = find_employee_across_sheets(employee_id, role)

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

*ВЧЛ:* {data['vchl']}

Выберите должность для нового поиска:"""
            else:
                text = f"""*ФИО:* {data['fio']}
*ПВЗ:* {data['pvz']}

*Факт часов:* {data['fact']}

*Оформленные виртуальные карты:* {data['virtual_cards']}
*Оформленные пластиковые карты:* {data['plastic_cards']}

*ВЧЛ:* {data['vchl']}

Выберите должность для нового поиска:"""

            keyboard = [
                [InlineKeyboardButton("Админ", callback_data="admin")],
                [InlineKeyboardButton("МФУ (Менеджер финансовых услуг)", callback_data="mfu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                text, parse_mode="Markdown", reply_markup=reply_markup
            )
            return SELECT_ROLE

        else:
            await update.message.reply_text(
                "❌ Табельный номер не найден (Ошибка 404). Введите табельный номер:"
            )
            return ENTER_ID

    except Exception as e:
        logging.error(f"Ошибка в enter_id: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте снова.")
        return SELECT_ROLE


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

    application.run_polling()
