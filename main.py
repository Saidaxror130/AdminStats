import logging
import requests
import os
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
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

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_MINUTES", "10")) * 60

# Антиспам: максимум запросов за окно времени
RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "10"))        # макс запросов
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # за N секунд
# Алерт если один юзер ищет много РАЗНЫХ табельных
SUSPICIOUS_DIFF_IDS = int(os.getenv("SUSPICIOUS_DIFF_IDS", "5"))

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен ⚠️")
if not API_KEY:
    raise ValueError("GOOGLE_API_KEY не установлен ⚠️")
if not REGISTRY_ID:
    raise ValueError("REGISTRY_SPREADSHEET_ID не установлен ⚠️")
if not ADMIN_ID:
    raise ValueError("ADMIN_BOT_ID не установлен ⚠️")


# ================= TIMEZONE =================

TZ_TASHKENT = timezone(timedelta(hours=5))

def now_tashkent() -> datetime:
    """Возвращает текущее время по Ташкенту."""
    return datetime.now(tz=TZ_TASHKENT)

def fmt_dt(dt: datetime) -> str:
    """Форматирует дату/время: дд.мм.гггг чч:мм:сс"""
    return dt.strftime("%d.%m.%Y %H:%M:%S")


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
        error_text = (
            f"🚨 Ошибка Google API\n\nURL:\n{api_url}\n\n"
            f"Status:\n{e.response.status_code}\n\nОтвет:\n{e.response.text}"
        )
        logging.error(error_text)
        send_admin_message(error_text)
        return []

    except Exception as e:
        error_text = f"🚨 Ошибка загрузки таблицы\n\nURL:\n{api_url}\n\nОшибка:\n{e}"
        logging.error(error_text)
        send_admin_message(error_text)
        return []


def load_records(api_url: str):
    values = load_sheet_values(api_url)
    if not values:
        logging.warning("⚠️ Таблица пустая или не загрузилась")
        return []
    headers = values[0]
    return [dict(zip(headers, row)) for row in values[1:]]


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
# _cache = {
#     "admin": { "<spreadsheet_id>": [record, ...], ... },
#     "mfu":   { "<spreadsheet_id>": [record, ...], ... },
# }

_cache: dict = {"admin": {}, "mfu": {}}
_cache_lock = threading.Lock()
_last_refresh: datetime | None = None
_cache_stats: dict = {
    "total_admin": 0,
    "total_mfu": 0,
    "sheet_count": 0,
    "errors": 0,
}


def build_role_url(spreadsheet_id: str, role: str):
    sheet_name = "Администраторы" if role == "admin" else "МФУ"
    return (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        f"/values/{sheet_name}!A2:Z1000?key={API_KEY}"
    )


def refresh_cache(notify_admin: bool = True):
    global _last_refresh, _cache_stats

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
                if records:
                    new_cache[role][spreadsheet_id] = records
                else:
                    # Защита: не затираем старые данные если пришло 0 записей
                    with _cache_lock:
                        old = _cache[role].get(spreadsheet_id)
                    if old:
                        new_cache[role][spreadsheet_id] = old
                        logging.warning(
                            f"⚠️ {spreadsheet_id} ({role}) вернул 0 записей — оставлены старые данные"
                        )
            except Exception as e:
                errors += 1
                logging.error(f"Ошибка загрузки {spreadsheet_id} ({role}): {e}")

    total_admin = sum(len(v) for v in new_cache["admin"].values())
    total_mfu = sum(len(v) for v in new_cache["mfu"].values())

    with _cache_lock:
        _cache["admin"] = new_cache["admin"]
        _cache["mfu"] = new_cache["mfu"]
        _last_refresh = now_tashkent()
        _cache_stats = {
            "total_admin": total_admin,
            "total_mfu": total_mfu,
            "sheet_count": len(sheet_ids),
            "errors": errors,
        }

    msg = (
        f"✅ Кэш обновлён в {fmt_dt(_last_refresh)}\n"
        f"Таблиц: {len(sheet_ids)} | Ошибок: {errors}\n"
        f"Записей Админ: {total_admin} | МФУ: {total_mfu}"
    )
    logging.info(msg)
    if notify_admin:
        send_admin_message(msg)


def _cache_refresh_loop():
    while True:
        try:
            refresh_cache()
        except Exception as e:
            logging.error(f"Критическая ошибка в цикле обновления кэша: {e}")
            send_admin_message(f"🚨 Критическая ошибка обновления кэша: {e}")
        threading.Event().wait(CACHE_TTL_SECONDS)


def start_cache_refresh_thread():
    t = threading.Thread(target=_cache_refresh_loop, daemon=True)
    t.start()
    logging.info("🚀 Фоновый поток обновления кэша запущен")


# ================= RATE LIMIT + LOGS =================

# Временные метки запросов каждого юзера для антиспама
_rate_data: dict = defaultdict(deque)
_rate_lock = threading.Lock()

# Лог последних 200 запросов
_request_log: deque = deque(maxlen=200)
_log_lock = threading.Lock()

# Сет разных табельных которые искал юзер (для алерта подозрительных)
_user_searched_ids: dict = defaultdict(set)


def log_request(user_id: int, username: str, employee_id: str, role: str, found: bool):
    entry = {
        "time": fmt_dt(now_tashkent()),
        "user_id": user_id,
        "username": username or "—",
        "employee_id": employee_id,
        "role": role,
        "found": found,
    }
    with _log_lock:
        _request_log.append(entry)

    # Проверка на подозрительную активность
    _user_searched_ids[user_id].add(employee_id)
    if len(_user_searched_ids[user_id]) >= SUSPICIOUS_DIFF_IDS:
        send_admin_message(
            f"⚠️ Подозрительная активность!\n\n"
            f"Пользователь: @{username} (ID: {user_id})\n"
            f"Искал {len(_user_searched_ids[user_id])} разных табельных:\n"
            f"{', '.join(_user_searched_ids[user_id])}"
        )
        # Сбрасываем чтобы не спамить алертами
        _user_searched_ids[user_id] = set()


def check_rate_limit(user_id: int) -> bool:
    """Возвращает True если лимит НЕ превышен."""
    now = now_tashkent()
    window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)

    with _rate_lock:
        dq = _rate_data[user_id]
        while dq and dq[0] < window_start:
            dq.popleft()
        if len(dq) >= RATE_LIMIT_MAX:
            return False
        dq.append(now)
        return True


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


# ================= ADMIN CHECK =================

def is_admin(update: Update) -> bool:
    return str(update.effective_user.id) == str(ADMIN_ID)


# ================= STATES =================

SELECT_ROLE, ENTER_ID = range(2)


# ================= ADMIN COMMANDS =================

async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return

    await update.message.reply_text("🔄 Обновляю кэш, подождите...")

    t = threading.Thread(target=lambda: refresh_cache(notify_admin=False), daemon=True)
    t.start()
    t.join(timeout=120)

    if _last_refresh:
        s = _cache_stats
        await update.message.reply_text(
            f"✅ Кэш обновлён!\n\n"
            f"🕐 Время: {fmt_dt(_last_refresh)}\n"
            f"📋 Таблиц: {s['sheet_count']}\n"
            f"❌ Ошибок: {s['errors']}\n"
            f"👤 Записей Админ: {s['total_admin']}\n"
            f"🖨 Записей МФУ: {s['total_mfu']}"
        )
    else:
        await update.message.reply_text("⚠️ Что-то пошло не так при обновлении.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return

    s = _cache_stats

    if _last_refresh:
        age = now_tashkent() - _last_refresh
        minutes = int(age.total_seconds() // 60)
        seconds = int(age.total_seconds() % 60)
        age_str = f"{minutes} мин {seconds} сек назад"
        next_sec = CACHE_TTL_SECONDS - int(age.total_seconds())
        next_str = f"через ~{max(0, next_sec) // 60} мин"
    else:
        age_str = "ещё не обновлялся"
        next_str = "скоро"

    with _log_lock:
        log_copy = list(_request_log)

    unique_users = len(set(e["user_id"] for e in log_copy))
    total_requests = len(log_copy)
    found_count = sum(1 for e in log_copy if e["found"])

    await update.message.reply_text(
        f"📊 Статус бота\n\n"
        f"🗂 Кэш:\n"
        f"  • Последнее обновление: {age_str}\n"
        f"  • Следующее: {next_str}\n"
        f"  • Таблиц: {s['sheet_count']}\n"
        f"  • Записей Админ: {s['total_admin']}\n"
        f"  • Записей МФУ: {s['total_mfu']}\n"
        f"  • Ошибок при загрузке: {s['errors']}\n\n"
        f"👥 Активность (всего в логе):\n"
        f"  • Запросов: {total_requests}\n"
        f"  • Уникальных юзеров: {unique_users}\n"
        f"  • Найдено: {found_count} | Не найдено: {total_requests - found_count}\n\n"
        f"⚙️ Настройки:\n"
        f"  • Интервал кэша: {CACHE_TTL_SECONDS // 60} мин\n"
        f"  • Лимит запросов: {RATE_LIMIT_MAX} за {RATE_LIMIT_WINDOW} сек\n"
        f"  • Алерт подозрит.: {SUSPICIOUS_DIFF_IDS} разных номеров"
    )


async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return

    with _log_lock:
        log_copy = list(_request_log)

    if not log_copy:
        await update.message.reply_text("📭 Лог пустой — запросов ещё не было.")
        return

    last = log_copy[-20:]
    lines = []
    for e in reversed(last):
        status = "✅" if e["found"] else "❌"
        lines.append(
            f"{status} {e['time']} | @{e['username']} | "
            f"№{e['employee_id']} | {e['role']}"
        )

    await update.message.reply_text("📋 Последние запросы:\n\n" + "\n".join(lines))


# ================= USER HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сбрасываем счётчик подозрительных при новой сессии
    _user_searched_ids[update.effective_user.id] = set()

    keyboard = [
        [InlineKeyboardButton("Админ", callback_data="admin")],
        [InlineKeyboardButton("МФУ", callback_data="mfu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if _last_refresh:
        cache_info = f"\n\n🕐 Последнее обновление: {fmt_dt(_last_refresh)}"
    else:
        cache_info = "\n\n⏳ Данные загружаются..."

    await update.message.reply_text(
        f"Привет! Я бот для просмотра показателей сотрудников.{cache_info}\n\n"
        f"Выберите вашу должность:",
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
        user = update.effective_user
        user_text = update.message.text.strip()

        # Антиспам
        if not check_rate_limit(user.id):
            await update.message.reply_text(
                "⏱ Слишком много запросов. Подождите немного и попробуйте снова."
            )
            return ENTER_ID

        if not user_text.isdigit() or len(user_text) < 3 or len(user_text) > 6:
            await update.message.reply_text(
                "❌ Табельный номер должен содержать только цифры.\n\nВведите табельный номер:"
            )
            return ENTER_ID

        employee_id = normalize_id(user_text)
        role = context.user_data.get("role")

        data = find_employee_in_cache(employee_id, role)

        # Логируем запрос и проверяем подозрительность
        log_request(
            user_id=user.id,
            username=user.username,
            employee_id=employee_id,
            role=role,
            found=data is not None,
        )

        if data:
            if role == "admin":
                text = (
                    f"👤<b>ФИО:</b> {data['fio']}\n"
                    f"🏢<b>ПВЗ:</b> {data['pvz']}\n\n"
                    f"<b>Факт часов:</b> {data['fact']} ⏱️\n\n"
                    f"<b>Кол. открытых лимитов:</b> {data['open_limits']} 📊\n"
                    f"<b>План по лимитам:</b> {data['plan_limits']} 📋\n"
                    f"<b>Выполнение плана:</b> {data['execution']} 📈\n\n"
                    f"<b>Виртуальные карты:</b> {data['virtual_cards']} 💷\n"
                    f"<b>Пластиковые карты:</b> {data['plastic_cards']} 💳\n\n"
                    f"🎥<b>ВЧЛ:</b> {data['vchl']}\n\n"
                    f"<u><b>Выберите должность для нового поиска:</b></u>"
                )
            else:
                text = (
                    f"👤<b>ФИО:</b> {data['fio']}\n"
                    f"🏢<b>ПВЗ:</b> {data['pvz']}\n\n"
                    f"<b>Факт часов:</b> {data['fact']} ⏱️\n\n"
                    f"<b>ВИРТУАЛЬНЫЕ карты:</b> {data['virtual_cards']} 💷\n"
                    f"<b>ПЛАСТИКОВЫЕ карты:</b> {data['plastic_cards']} 💳\n\n"
                    f"🎥<b>ВЧЛ:</b> {data['vchl']}\n\n"
                    f"<u>Выберите должность для нового поиска:</u>"
                )

            keyboard = [
                [InlineKeyboardButton("Админ", callback_data="admin")],
                [InlineKeyboardButton("МФУ", callback_data="mfu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)
            return SELECT_ROLE

        else:
            if _last_refresh is None:
                note = "\n\n⏳ Кэш ещё загружается, попробуйте через минуту."
            else:
                note = f"\n\n🕐 Последнее обновление: {fmt_dt(_last_refresh)}"

            await update.message.reply_text(
                f"❌ Табельный номер не найден.{note}\n\nВведите табельный номер:"
            )
            return ENTER_ID

    except Exception as e:
        error = (
            f"🚨 Ошибка обработки запроса\n\n"
            f"User:\n{update.effective_user.id}\n\n"
            f"Сообщение:\n{update.message.text}\n\n"
            f"Ошибка:\n{e}"
        )
        logging.error(error)
        send_admin_message(error)
        await update.message.reply_text("Произошла ошибка!\n\nПопробуйте снова. /start")
        return SELECT_ROLE


# ================= GLOBAL ERROR =================

async def error_handler(update, context):
    if "terminated by other getUpdates request" in str(context.error):
        return
    error = f"🚨 GLOBAL ERROR\n\nUpdate:\n{update}\n\nError:\n{context.error}"
    logging.error(error)
    send_admin_message(error)


# ================= MAIN =================

if __name__ == "__main__":

    start_cache_refresh_thread()

    application = ApplicationBuilder().token(TOKEN).build()

    # Админские команды — работают всегда, вне ConversationHandler
    application.add_handler(CommandHandler("refresh", cmd_refresh))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("logs", cmd_logs))

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

    send_admin_message(
        f"🤖 Бот запущен\n"
        f"Интервал кэша: {CACHE_TTL_SECONDS // 60} мин\n"
        f"Лимит запросов: {RATE_LIMIT_MAX} за {RATE_LIMIT_WINDOW} сек"
    )

    application.run_polling()
