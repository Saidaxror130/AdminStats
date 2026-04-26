"""
Кэш ролей пользователей на время сессии (живёт в памяти, сбрасывается при рестарте бота).
При /start роль всегда сбрасывается — пользователь выбирает заново.
"""

_user_roles: dict[int, str] = {}


def get_role(user_id: int) -> str | None:
    return _user_roles.get(user_id)


def set_role(user_id: int, role: str) -> None:
    _user_roles[user_id] = role


def clear_role(user_id: int) -> None:
    _user_roles.pop(user_id, None)
