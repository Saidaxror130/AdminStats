from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from cache import (
    find_employee_in_cache, check_rate_limit, log_request,
    send_admin_message, _user_searched_ids,
)
from utils.helpers import fmt_dt, normalize_id
import cache as c

# ================= STATES =================

SELECT_ROLE, ENTER_ID = range(2)


# ================= HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _user_searched_ids[update.effective_user.id] = set()

    keyboard = [
        [InlineKeyboardButton("Админ", callback_data="admin")],
        [InlineKeyboardButton("МФУ", callback_data="mfu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if c._last_refresh:
        cache_info = f"\n\n🕐 Последнее обновление: {fmt_dt(c._last_refresh)}"
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
            if c._last_refresh is None:
                note = "\n\n⏳ Кэш ещё загружается, попробуйте через минуту."
            else:
                note = f"\n\n🕐 Последнее обновление: {fmt_dt(c._last_refresh)}"

            await update.message.reply_text(
                f"❌ Табельный номер не найден.{note}\n\nВведите табельный номер:"
            )
            return ENTER_ID

    except Exception as e:
        import logging
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
