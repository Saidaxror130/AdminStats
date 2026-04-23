import logging
import threading
from collections import defaultdict, deque
from datetime import timedelta

from config import (
    API_KEY, REGISTRY_ID, TOKEN, ADMIN_ID,
    CACHE_TTL_SECONDS, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW, SUSPICIOUS_DIFF_IDS,
)
from utils.helpers import now_tashkent, fmt_dt, normalize_id
from utils.sheets import (
    load_records, get_registry_ids, build_role_url, send_admin_message_raw,
)


# ================= ADMIN ALERT =================

def send_admin_message(text: str):
    send_admin_message_raw(TOKEN, ADMIN_ID, text)


# ================= CACHE =================
#
# _cache = {
#     "admin": { "<spreadsheet_id>": [record, ...], ... },
#     "mfu":   { "<spreadsheet_id>": [record, ...], ... },
# }

_cache: dict = {"admin": {}, "mfu": {}}
_cache_lock = threading.Lock()
_last_refresh = None
_cache_stats: dict = {
    "total_admin": 0,
    "total_mfu": 0,
    "sheet_count": 0,
    "errors": 0,
}


def refresh_cache(notify_admin: bool = True):
    global _last_refresh, _cache_stats

    logging.info("🔄 Начинаем обновление кэша...")

    sheet_ids = get_registry_ids(REGISTRY_ID, TOKEN, ADMIN_ID)

    if not sheet_ids:
        send_admin_message("🚨 Реестр таблиц пустой — кэш не обновлён")
        return

    new_cache: dict = {"admin": {}, "mfu": {}}
    errors = 0

    for spreadsheet_id in sheet_ids:
        for role in ("admin", "mfu"):
            try:
                api_url = build_role_url(spreadsheet_id, role)
                records = load_records(api_url, TOKEN, ADMIN_ID)
                if records:
                    new_cache[role][spreadsheet_id] = records
                else:
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

_rate_data: dict = defaultdict(deque)
_rate_lock = threading.Lock()

_request_log: deque = deque(maxlen=200)
_log_lock = threading.Lock()

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

    _user_searched_ids[user_id].add(employee_id)
    if len(_user_searched_ids[user_id]) >= SUSPICIOUS_DIFF_IDS:
        send_admin_message(
            f"⚠️ Подозрительная активность!\n\n"
            f"Пользователь: @{username} (ID: {user_id})\n"
            f"Искал {len(_user_searched_ids[user_id])} разных табельных:\n"
            f"{', '.join(_user_searched_ids[user_id])}"
        )
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

def get_employee_data(employee_id: str, records: list):
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
