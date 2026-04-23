import threading
from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID, CACHE_TTL_SECONDS, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW, SUSPICIOUS_DIFF_IDS
from cache import (
    refresh_cache, _last_refresh, _cache_stats,
    _request_log, _log_lock,
)
from utils.helpers import now_tashkent, fmt_dt


def is_admin(update: Update) -> bool:
    return str(update.effective_user.id) == str(ADMIN_ID)


async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return

    await update.message.reply_text("🔄 Обновляю кэш, подождите...")

    t = threading.Thread(target=lambda: refresh_cache(notify_admin=False), daemon=True)
    t.start()
    t.join(timeout=120)

    import cache as c
    if c._last_refresh:
        s = c._cache_stats
        await update.message.reply_text(
            f"✅ Кэш обновлён!\n\n"
            f"🕐 Время: {fmt_dt(c._last_refresh)}\n"
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

    import cache as c
    s = c._cache_stats

    if c._last_refresh:
        age = now_tashkent() - c._last_refresh
        minutes = int(age.total_seconds() // 60)
        seconds = int(age.total_seconds() % 60)
        age_str = f"{minutes} мин {seconds} сек назад"
        next_sec = CACHE_TTL_SECONDS - int(age.total_seconds())
        next_str = f"через ~{max(0, next_sec) // 60} мин"
    else:
        age_str = "ещё не обновлялся"
        next_str = "скоро"

    with c._log_lock:
        log_copy = list(c._request_log)

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

    import cache as c
    with c._log_lock:
        log_copy = list(c._request_log)

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
