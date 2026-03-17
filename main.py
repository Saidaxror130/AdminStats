import logging
import requests
import os
import threading
from datetime import datetime
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

CACHE_TTL_SECONDS = 10 * 60  # 10 минут

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
            json={"chat_id": ADMIN_ID, "text": text},
            timeout=10,
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
        logging.warning("⚠️ Таблица пустая или не загрузилась")
        return []
    headers = values[0]
    records = [dict(zip(headers, row)) for row in values[1:]]
    return records


# ================= REGISTRY =================

def get_registry_ids(registry_spreadsheet_id: str):
    api_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{registry_spreadsheet_id}"
        f"/values/A2:A?key={API_KEY}"
    )
    values = load_sheet_values(api_url)
    ids = [row[0].strip() for row in values if row and row[0]]
    logging.info(f"Загружено {len(ids)} spreadsheet_id из реестра")
    return ids


# ================= CACHE =================
#
# Структура кэша:
#   _cache = {
#       "admin": {
#           "<spreadsheet_id>": [record, record, ...],
#           ...
#       },
#       "mfu": {
#           "<spreadsheet_id>": [record, record, ...],
#           ...
#       },
#   }
#
# Кэш обновляется в фоновом потоке каждые CACHE_TTL_SECONDS секунд.
# Поиск сотрудника идёт только по данным из кэша — без запросов к Google.

_cache: dict = {"admin": {}, "mfu": {}}
_cache_lock = threading.Lock()
_last_refresh: datetime | None = None


def build_role_url(spreadsheet_id: str, role: str):
    sheet_name = "Администраторы" if role == "admin" else "МФУ"
    return (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        f"/values/{sheet_name}!A2:Z1000?key={API_KEY}"
    )


def refresh_cache():
    """Загружает все таблицы из реестра и сохраняет данные в _cache."""
    global _last_refresh

    logging.info("🔄 Начинаем обновление кэша...")

    sheet_ids = get_registry_ids(REGISTRY_ID)

    if not sheet_ids:
        send_admin_message("🚨 Реестр таблиц пустой — кэш не обновлён")
        return

    new_cache: dict = {"admin": {}, "mfu": {}}
    errors = 0

    for spreadsheet_id in sheet_ids:
        for role in ("admin", "mfu"):
            try:
                api_url = build_role_url(spreadsheet_id, role)
                records = load_records(api_url)
                new_cache[role][spreadsheet_id] = records
            except Exception as e:
                errors += 1
                logging.error(f"Ошибка загрузки {spreadsheet_id} ({role}): {e}")

    with _cache_lock:
        _cache["admin"] = new_cache["admin"]
        _cache["mfu"] = new_cache["mfu"]
        _last_refresh = datetime.now()

    total_admin = sum(len(v) for v in new_cache["admin"].values())
    total_mfu = sum(len(v) for v in new_cache["mfu"].values())

    msg = (
        f"✅ Кэш обновлён в {_last_refresh.strftime('%H:%M:%S')}\n"
        f"Таблиц: {len(sheet_ids)} | Ошибок: {errors}\n"
        f"Записей Админ: {total_admin} | МФУ: {total_mfu}"
    )
    logging.info(msg)
    send_admin_message(msg)


def _cache_refresh_loop():
    """Бесконечный цикл обновления кэша в фоновом потоке."""
    while True:
        try:
            refresh_cache()
        except Exception as e:
            logging.error(f"Критическая ошибка в цикле обновления кэша: {e}")
            send_admin_message(f"🚨 Критическая ошибка обновления кэша: {e}")

        # Ждём CACHE_TTL_SECONDS и запускаем снова
        threading.Event().wait(CACHE_TTL_SECONDS)


def start_cache_refresh_thread():
    t = threading.Thread(target=_cache_refresh_loop, daemon=True)
    t.start()
    logging.info("🚀 Фоновый поток обновления кэша запущен")


# ================= SEARCH =================

def get_employee_data(employee_id, records):
    employee_id = normalize_id(employee_id)
    for row in records:
        table_id = normalize_id(row.get("Табельный номер", ""))
        if table_id == employee_id:
            logging.info(
                f"🎉 Найден сотрудник {employee_id}: "
                f"{row.get('ПВЗ', 'N/A')} ({row.get('ФИО', 'N/A')})"
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


def find_employee_in_cache(employee_id: str, role: str):
    """Ищет сотрудника только в кэше — без единого запроса к Google."""

    logging.info(f"🔍 Поиск {employee_id} (роль: {role}) в кэше")

    with _cache_lock:
        sheets_data = dict(_cache.get(role, {}))

    if not sheets_data:
        logging.warning("Кэш пустой — данные ещё не загружены")
        return None

    for spreadsheet_id, records in sheets_data.items():
        data = get_employee_data(employee_id, records)
        if data:
            return data

    logging.warning(f"❌ {employee_id} (роль: {role}) не найден в кэше")
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

    # Показываем время последнего обновления кэша
    if _last_refresh:
        cache_info = f"\n\n🕐 Данные актуальны на: {_last_refresh.strftime('%H:%M:%S')}"
    else:
        cache_info = "\n\n⏳ Данные загружаются..."

    await update.message.reply_text(
        f"Привет! Я бот для просмотра показателей сотрудников.{cache_info}\n\nВыберите вашу должность:",
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
        user_text = update.message.text.strip()

        if not user_text.isdigit() or len(user_text) < 3 or len(user_text) > 6:
            await update.message.reply_text(
                "❌ Табельный номер должен содержать только цифры.\n\nВведите табельный номер:"
            )
            return ENTER_ID

        employee_id = normalize_id(user_text)
        role = context.user_data.get("role")

        # Поиск ТОЛЬКО в кэше — никаких запросов к Google здесь
        data = find_employee_in_cache(employee_id, role)

        if data:
            if role == "admin":
                text = f"""👤<b>ФИО:</b> {data['fio']}
🏢<b>ПВЗ:</b> {data['pvz']}

<b>Факт часов:</b> {data['fact']} ⏱️

<b>Кол. открытых лимитов:</b> {data['open_limits']} 📊
<b>План по лимитам:</b> {data['plan_limits']} 📋
<b>Выполнение плана:</b> {data['execution']} 📈

<b>Виртуальные карты:</b> {data['virtual_cards']} 💷
<b>Пластиковые карты:</b> {data['plastic_cards']} 💳

🎥<b>ВЧЛ:</b> {data['vchl']}

<u><b>Выберите должность для нового поиска:</b></u>"""
            else:
                text = f"""👤<b>ФИО:</b> {data['fio']}
🏢<b>ПВЗ:</b> {data['pvz']}

<b>Факт часов:</b> {data['fact']} ⏱️

<b>ВИРТУАЛЬНЫЕ карты:</b> {data['virtual_cards']} 💷
<b>ПЛАСТИКОВЫЕ карты:</b> {data['plastic_cards']} 💳

🎥<b>ВЧЛ:</b> {data['vchl']}

<u>Выберите должность для нового поиска:</u>"""

            keyboard = [
                [InlineKeyboardButton("Админ", callback_data="admin")],
                [InlineKeyboardButton("МФУ", callback_data="mfu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                text, parse_mode="HTML", reply_markup=reply_markup
            )
            return SELECT_ROLE

        else:
            # Если не нашли — уточняем, возможно кэш ещё не загружен
            if _last_refresh is None:
                note = "\n\n⏳ Кэш ещё загружается, попробуйте через минуту."
            else:
                note = f"\n\n🕐 Данные актуальны на: {_last_refresh.strftime('%H:%M:%S')}"

            await update.message.reply_text(
                f"❌ Табельный номер не найден.{note}\n\nВведите табельный номер:"
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

        await update.message.reply_text("Произошла ошибка!\n\nПопробуйте снова. /start")
        return SELECT_ROLE


# ================= GLOBAL ERROR =================

async def error_handler(update, context):
    if "terminated by other getUpdates request" in str(context.error):
        return

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

    # Запускаем фоновый поток кэша ДО старта бота
    # Первое обновление происходит сразу при запуске
    start_cache_refresh_thread()

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
