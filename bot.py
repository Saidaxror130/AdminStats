# import sys
# import os
# sys.path.insert(0, os.path.dirname(__file__))

import logging
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler,
)

from config import TOKEN, CACHE_TTL_SECONDS, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW
from cache import start_cache_refresh_thread, send_admin_message
from handlers.admin import cmd_refresh, cmd_status, cmd_logs
from handlers.user import start, select_role, enter_id, SELECT_ROLE, ENTER_ID

# ================= LOGGING =================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)


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

    # Админские команды
    application.add_handler(CommandHandler("refresh", cmd_refresh))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("logs", cmd_logs))

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_ROLE: [CallbackQueryHandler(select_role)],
            ENTER_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_id),
                CallbackQueryHandler(select_role, pattern="^new_search$"),
                CallbackQueryHandler(select_role, pattern="^share_card$"),
            ],
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
