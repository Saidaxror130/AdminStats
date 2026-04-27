"""
Управление кэшем данных из Google Sheets.
"""

import logging
import threading
from config import REGISTRY_ID, TOKEN, ADMIN_ID, CACHE_TTL_SECONDS
from utils.helpers import now_tashkent
from utils.sheets import get_registry_ids, build_role_url, load_records


_cache: dict = {"admin": {}, "mfu": {}}
_cache_lock = threading.Lock()
_last_refresh = None
_cache_stats: dict = {
    "total_admin": 0,
    "total_mfu": 0,
    "sheet_count": 0,
    "errors": 0,
}


def get_cache_stats() -> dict:
    """Возвращает статистику кэша."""
    with _cache_lock:
        return dict(_cache_stats)


def get_last_refresh():
    """Возвращает время последнего обновления кэша."""
    return _last_refresh


def refresh_cache(notify_callback=None):
    """
    Обновляет кэш из Google Sheets.

    Args:
        notify_callback: функция для отправки уведомлений (принимает текст сообщения)
    """
    global _last_refresh, _cache_stats

    logging.info("🔄 Начинаем обновление кэша...")

    sheet_ids = get_registry_ids(REGISTRY_ID)

    if not sheet_ids:
        msg = "🚨 Реестр таблиц пустой — кэш не обновлён"
        if notify_callback:
            notify_callback(msg)
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

    from utils.helpers import fmt_dt
    msg = (
        f"✅ Кэш обновлён в {fmt_dt(_last_refresh)}\n"
        f"Таблиц: {len(sheet_ids)} | Ошибок: {errors}\n"
        f"Записей Админ: {total_admin} | МФУ: {total_mfu}"
    )
    logging.info(msg)
    if notify_callback:
        notify_callback(msg)


def start_cache_refresh_loop(notify_callback=None):
    """Запускает фоновый поток обновления кэша."""
    def _loop():
        while True:
            try:
                refresh_cache(notify_callback)
            except Exception as e:
                logging.error(f"Критическая ошибка в цикле обновления кэша: {e}")
                if notify_callback:
                    notify_callback(f"🚨 Критическая ошибка обновления кэша: {e}")
            threading.Event().wait(CACHE_TTL_SECONDS)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    logging.info("🚀 Фоновый поток обновления кэша запущен")


def find_employee_in_cache(employee_id: str, role: str):
    """
    Ищет сотрудника в кэше по табельному номеру и роли.

    Returns:
        dict с данными сотрудника или None если не найден
    """
    from utils.helpers import normalize_id

    logging.info(f"🔍 Поиск {employee_id} (роль: {role}) в кэше")

    with _cache_lock:
        sheets_data = dict(_cache.get(role, {}))

    if not sheets_data:
        logging.warning("Кэш пустой — данные ещё не загружены")
        return None

    employee_id = normalize_id(employee_id)

    for spreadsheet_id, records in sheets_data.items():
        data = _get_employee_data(employee_id, records)
        if data:
            return data

    logging.warning(f"❌ {employee_id} (роль: {role}) не найден в кэше")
    return None


def _get_employee_data(employee_id: str, records: list):
    """Извлекает данные сотрудника из списка записей."""
    from utils.helpers import normalize_id

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
                "employee_id": table_id,
            }
    return None


def search_employees_by_name(search_query: str) -> list:
    """
    Ищет сотрудников по частичному совпадению ФИО.

    Args:
        search_query: строка для поиска (имя или фамилия)

    Returns:
        список словарей с данными найденных сотрудников
        [{"fio": "...", "employee_id": "...", "pvz": "...", "role": "admin/mfu"}, ...]
    """
    from utils.helpers import normalize_id

    search_query = search_query.strip().upper()
    if not search_query:
        return []

    logging.info(f"🔍 Поиск сотрудников по запросу: {search_query}")

    results = []

    with _cache_lock:
        cache_copy = {"admin": dict(_cache["admin"]), "mfu": dict(_cache["mfu"])}

    for role in ("admin", "mfu"):
        for spreadsheet_id, records in cache_copy[role].items():
            for row in records:
                fio = row.get("ФИО", "").upper()
                if search_query in fio:
                    employee_id = normalize_id(row.get("Табельный номер", ""))
                    results.append({
                        "fio": row.get("ФИО", "N/A"),
                        "employee_id": employee_id,
                        "pvz": row.get("ПВЗ", "N/A"),
                        "role": role,
                    })

    logging.info(f"✅ Найдено {len(results)} сотрудников")
    return results


def search_employees_by_pvz(pvz_query: str) -> list:
    """
    Ищет всех сотрудников конкретного ПВЗ по точному совпадению номера.

    Args:
        pvz_query: название ПВЗ (например: "ТАШ-5", "Таш-5", "tash-5")

    Returns:
        список словарей с данными найденных сотрудников
        [{"fio": "...", "employee_id": "...", "pvz": "...", "role": "admin/mfu"}, ...]
    """
    from utils.helpers import normalize_id, normalize_pvz, extract_pvz_number

    if not pvz_query:
        return []

    # Нормализуем запрос
    normalized_query = normalize_pvz(pvz_query)
    query_number = extract_pvz_number(normalized_query)

    if not query_number:
        logging.warning(f"Не удалось извлечь номер из запроса: {pvz_query}")
        return []

    logging.info(f"🔍 Поиск сотрудников ПВЗ: {normalized_query} (номер: {query_number})")

    results = []

    with _cache_lock:
        cache_copy = {"admin": dict(_cache["admin"]), "mfu": dict(_cache["mfu"])}

    for role in ("admin", "mfu"):
        for spreadsheet_id, records in cache_copy[role].items():
            for row in records:
                pvz_name = row.get("ПВЗ", "")
                if not pvz_name:
                    continue

                # Нормализуем ПВЗ из таблицы
                normalized_pvz = normalize_pvz(pvz_name)
                pvz_number = extract_pvz_number(normalized_pvz)

                # Сравниваем только номера (точное совпадение)
                if pvz_number == query_number:
                    employee_id = normalize_id(row.get("Табельный номер", ""))
                    results.append({
                        "fio": row.get("ФИО", "N/A"),
                        "employee_id": employee_id,
                        "pvz": pvz_name,  # Оригинальное название из таблицы
                        "pvz_normalized": normalized_pvz,
                        "role": role,
                        "fact": row.get("Факт", "N/A"),
                        "vchl": row.get("ВЧЛ", "N/A"),
                    })

    logging.info(f"✅ Найдено {len(results)} сотрудников в ПВЗ {normalized_query}")
    return results
