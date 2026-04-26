import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from cache import (
    find_employee_in_cache, check_rate_limit, log_request,
    send_admin_message, _user_searched_ids,
)
from utils.helpers import fmt_dt, normalize_id
from session_cache import get_role, set_role, clear_role
from utils.card_generator import generate_card
import cache as c

# ================= STATES =================

SELECT_ROLE, ENTER_ID = range(2)


# ================= KEYBOARDS =================

def role_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👔  Администратор", callback_data="admin")],
        [InlineKeyboardButton("🖨  МФУ",           callback_data="mfu")],
    ])

def new_search_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍  Новый поиск", callback_data="new_search")],
        [InlineKeyboardButton("🖼  Поделиться карточкой", callback_data="share_card")],
    ])


# ================= FORMATTERS =================

def format_card_admin(data: dict) -> str:
    return (
        f"👤  <b>{data['fio']}</b>\n"
        f"🏢  <b>ПВЗ:</b> {data['pvz']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⏱  <b>Факт часов:</b>  {data['fact']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📊  <b>Лимиты</b>\n"
        f"   Открыто:       {data['open_limits']}\n"
        f"   План:           {data['plan_limits']}\n"
        f"   Выполнение:  {data['execution']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💳  <b>Карты</b>\n"
        f"   Виртуальные:  {data['virtual_cards']}\n"
        f"   Пластиковые:  {data['plastic_cards']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🎥  <b>ВЧЛ:</b>  {data['vchl']}"
    )


def format_card_mfu(data: dict) -> str:
    return (
        f"👤  <b>{data['fio']}</b>\n"
        f"🏢  <b>ПВЗ:</b> {data['pvz']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⏱  <b>Факт часов:</b>  {data['fact']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💳  <b>Карты</b>\n"
        f"   Виртуальные:  {data['virtual_cards']}\n"
        f"   Пластиковые:  {data['plastic_cards']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🎥  <b>ВЧЛ:</b>  {data['vchl']}"
    )


# ================= VALIDATION =================

def validate_employee_id(text: str) -> tuple[bool, str]:
    cleaned = text.strip().replace(" ", "").replace("\xa0", "")

    if not cleaned:
        return False, "Вы отправили пустое сообщение.\n\nВведите табельный номер (3–6 цифр):"

    if not cleaned.isdigit():
        non_digits = [ch for ch in cleaned if not ch.isdigit()]
        example = "".join(non_digits[:3])
        return False, (
            f"Табельный номер состоит только из цифр.\n"
            f"Лишние символы: <code>{example}</code>\n\n"
            f"Попробуйте ещё раз:"
        )

    if len(cleaned) < 3:
        return False, f"Слишком короткий номер: <b>{len(cleaned)} цифры</b>. Должно быть от 3 до 6.\n\nПопробуйте ещё раз:"

    if len(cleaned) > 6:
        return False, f"Слишком длинный номер: <b>{len(cleaned)} цифр</b>. Должно быть не более 6.\n\nПопробуйте ещё раз:"

    return True, ""


# ================= HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    _user_searched_ids[user.id] = set()
    clear_role(user.id)

    if c._last_refresh:
        status_line = f"🟢 Данные обновлены: {fmt_dt(c._last_refresh)}"
    else:
        status_line = "🟡 Данные загружаются, подождите немного..."

    name = user.first_name or "друг"

    await update.message.reply_text(
        f"Привет, {name}! 👋\n\n"
        f"Я помогу тебе быстро узнать свои рабочие показатели — "
        f"факт часов, карты, лимиты и ВЧЛ.\n\n"
        f"{status_line}\n\n"
        f"Выберите свою должность:",
        reply_markup=role_keyboard(),
    )
    return SELECT_ROLE


async def select_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    # ── Генерация и отправка карточки ───────────────────────────────────────
    if data == "share_card":
        employee = context.user_data.get("last_employee")
        role = get_role(query.from_user.id)
        if not employee or not role:
            await query.answer("Данные устарели, сделайте новый поиск.", show_alert=True)
            return SELECT_ROLE
        await query.answer("Генерирую карточку...")
        try:
            png_bytes = generate_card(employee, role)
            await query.message.reply_photo(
                photo=png_bytes,
                caption=f"📊 {employee.get('fio', '')} · {employee.get('pvz', '')}",
            )
        except Exception as e:
            logging.error(f"Ошибка генерации карточки: {e}")
            await query.answer("Не удалось создать карточку.", show_alert=True)
        return SELECT_ROLE

    # ── Новый поиск ─────────────────────────────────────────────────────────
    if data == "new_search":
        role = get_role(query.from_user.id)
        if not role:
            await query.edit_message_text(
                "Сессия устарела. Нажмите /start чтобы начать заново."
            )
            return SELECT_ROLE
        role_label = "Администратор" if role == "admin" else "МФУ"
        await query.edit_message_text(
            f"🔍 Поиск ({role_label})\n\nВведите табельный номер:"
        )
        return ENTER_ID

    role = data
    set_role(query.from_user.id, role)
    context.user_data["role"] = role

    role_label = "Администратор" if role == "admin" else "МФУ"
    await query.edit_message_text(
        f"🔍 Поиск ({role_label})\n\nВведите табельный номер:"
    )
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

        ok, err_msg = validate_employee_id(user_text)
        if not ok:
            await update.message.reply_text(err_msg, parse_mode="HTML")
            return ENTER_ID

        employee_id = normalize_id(user_text)
        role = get_role(user.id) or context.user_data.get("role")

        if not role:
            await update.message.reply_text(
                "Не удалось определить вашу роль. Нажмите /start чтобы начать заново."
            )
            return SELECT_ROLE

        data = find_employee_in_cache(employee_id, role)

        log_request(
            user_id=user.id,
            username=user.username,
            employee_id=employee_id,
            role=role,
            found=data is not None,
        )

        if data:
            # Сохраняем для генерации карточки
            context.user_data["last_employee"] = data

            text = format_card_admin(data) if role == "admin" else format_card_mfu(data)
            await update.message.reply_text(
                text,
                parse_mode="HTML",
                reply_markup=new_search_keyboard(),
            )
            return SELECT_ROLE

        else:
            if c._last_refresh is None:
                note = "⏳ Кэш ещё загружается — попробуйте через минуту."
            else:
                note = f"🕐 Данные актуальны на: {fmt_dt(c._last_refresh)}"

            await update.message.reply_text(
                f"❌ Табельный номер <code>{employee_id}</code> не найден.\n\n"
                f"{note}\n\n"
                f"Проверьте номер и попробуйте ещё раз:",
                parse_mode="HTML",
            )
            return ENTER_ID

    except Exception as e:
        error = (
            f"🚨 Ошибка обработки запроса\n\n"
            f"User: {update.effective_user.id}\n"
            f"Сообщение: {update.message.text}\n"
            f"Ошибка: {e}"
        )
        logging.error(error)
        send_admin_message(error)
        await update.message.reply_text(
            "Что-то пошло не так. Попробуйте ещё раз или нажмите /start"
        )
        return SELECT_ROLE
