"""
Rate limiting для защиты от спама.
"""

import threading
from collections import defaultdict, deque
from datetime import timedelta
from config import RATE_LIMIT_MAX, RATE_LIMIT_WINDOW
from utils.helpers import now_tashkent


_rate_data: dict = defaultdict(deque)
_rate_lock = threading.Lock()


def check_rate_limit(user_id: int) -> bool:
    """
    Проверяет не превышен ли лимит запросов для пользователя.

    Returns:
        True если лимит НЕ превышен, False если превышен
    """
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
