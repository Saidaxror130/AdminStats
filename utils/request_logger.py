"""
Логирование запросов пользователей и детекция подозрительной активности.
"""

import threading
from collections import defaultdict, deque
from config import SUSPICIOUS_DIFF_IDS
from utils.helpers import fmt_dt, now_tashkent


_request_log: deque = deque(maxlen=200)
_log_lock = threading.Lock()
_user_searched_ids: dict = defaultdict(set)


def log_request(user_id: int, username: str, employee_id: str, role: str, found: bool, alert_callback=None):
    """
    Логирует запрос пользователя и проверяет на подозрительную активность.

    Args:
        user_id: ID пользователя Telegram
        username: username пользователя
        employee_id: табельный номер
        role: роль (admin/mfu)
        found: найден ли сотрудник
        alert_callback: функция для отправки алертов (принимает текст сообщения)
    """
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
        if alert_callback:
            alert_callback(
                f"⚠️ Подозрительная активность!\n\n"
                f"Пользователь: @{username} (ID: {user_id})\n"
                f"Искал {len(_user_searched_ids[user_id])} разных табельных:\n"
                f"{', '.join(_user_searched_ids[user_id])}"
            )
        _user_searched_ids[user_id] = set()


def get_request_log() -> list:
    """Возвращает копию лога запросов."""
    with _log_lock:
        return list(_request_log)


def clear_user_searches(user_id: int):
    """Очищает историю поисков пользователя."""
    _user_searched_ids[user_id] = set()
