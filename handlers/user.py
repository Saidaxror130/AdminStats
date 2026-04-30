import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.cache_manager import find_employee_in_cache, get_last_refresh
from utils.rate_limiter import check_rate_limit
from utils.request_logger import log_request, clear_user_searches
from utils.admin_notifier import send_admin_message
from utils.helpers import fmt_dt, normalize_id
from session_cache import get_role, set_role, clear_role
from utils.card_generator import generate_card

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

def search_keyboard():
    """Клавиатура с кнопкой отмены при вводе табельного."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌  Отмена", callback_data="cancel_search")],
    ])


# ================= FORMATTERS =================

def format_card_admin(data: dict) -> str:
    return (
        f"👤  <b>{data['fio']}</b>\n"
        f"🏢  <b>ПВЗ:</b> {data['pvz']}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"⏱  <b>Факт часов:</b>  {data['fact']}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📊  <b>Лимиты</b>\n"
        f"   Открыто:       {data['open_limits']}\n"
        f"   План:           {data['plan_limits']}\n"
        f"   Выполнение:  {data['execution']}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"💳  <b>Карты</b>\n"
        f"   Виртуальные:  {data['virtual_cards']}\n"
        f"   Пластиковые:  {data['plastic_cards']}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🎥  <b>ВЧЛ:</b>  {data['vchl']}"
    )


def format_card_mfu(data: dict) -> str:
    return (
        f"👤  <b>{data['fio']}</b>\n"
        f"🏢  <b>ПВЗ:</b> {data['pvz']}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"⏱  <b>Факт часов:</b>  {data['fact']}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"💳  <b>Карты</b>\n"
        f"   Виртуальные:  {data['virtual_cards']}\n"
        f"   Пластиковые:  {data['plastic_cards']}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🎥  <b>ВЧЛ:</b>  {data['vchl']}"
    )


# ================= VALIDATION =================

def validate_employee_id(text: str) -> tuple[bool, str]:
    cleaned = text.strip().replace(" ", "").replace("\xa0", "")

    if not cleaned:
        return False, "❌ Пустое сообщение.\n\nВведи табельный номер (3-6 цифр):"

    if not cleaned.isdigit():
        non_digits = [ch for ch in cleaned if not ch.isdigit()]
        example = "".join(non_digits[:3])
        return False, (
            f"❌ Табельный номер — это только цифры.\n"
            f"Лишние символы: <code>{example}</code>\n\n"
            f"Попробуй ещё раз:"
        )

    if len(cleaned) < 3:
        return False, f"❌ Слишком короткий: <b>{len(cleaned)} цифры</b>.\nНужно от 3 до 6 цифр.\n\nПопробуй ещё раз:"

    if len(cleaned) > 6:
        return False, f"❌ Слишком длинный: <b>{len(cleaned)} цифр</b>.\nМаксимум 6 цифр.\n\nПопробуй ещё раз:"

    return True, ""


# ================= HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    clear_user_searches(user.id)
    clear_role(user.id)

    last_refresh = get_last_refresh()
    if last_refresh:
        status_line = f"🟢 Данные обновлены: {fmt_dt(last_refresh)}"
    else:
        status_line = "🟡 Данные загружаются, подождите немного..."

    name = user.first_name or "друг"

    await update.message.reply_text(
        f"Привет, {name}! 👋\n\n"
        f"Я помогу узнать твои рабочие показатели:\n"
        f"• Факт часов\n"
        f"• Карты (виртуальные и пластиковые)\n"
        f"• Лимиты\n"
        f"• ВЧЛ\n\n"
        f"{status_line}\n\n"
        f"<b>Выбери свою должность:</b>",
        reply_markup=role_keyboard(),
        parse_mode="HTML"
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
            await query.answer("⚠️ Данные устарели, сделай новый поиск.", show_alert=True)
            return SELECT_ROLE
        await query.answer("⏳ Генерирую карточку...")
        try:
            png_bytes = generate_card(employee, role)
            await query.message.reply_photo(
                photo=png_bytes,
                caption=f"📊 {employee.get('fio', '')} · {employee.get('pvz', '')}",
            )
        except Exception as e:
            logging.error(f"Ошибка генерации карточки: {e}")
            await query.answer("❌ Не удалось создать карточку.", show_alert=True)
        return SELECT_ROLE

    # ── Новый поиск ─────────────────────────────────────────────────────────
    if data == "new_search":
        role = get_role(query.from_user.id)
        if not role:
            await query.edit_message_text(
                "⚠️ Сессия устарела.\n\nНажми /start чтобы начать заново."
            )
            return SELECT_ROLE
        role_label = "Администратор" if role == "admin" else "МФУ"
        await query.edit_message_text(
            f"🔍 <b>Поиск ({role_label})</b>\n\n"
            f"Введи свой табельный номер (3-6 цифр):",
            parse_mode="HTML",
            reply_markup=search_keyboard()
        )
        return ENTER_ID

    # ── Отмена поиска ───────────────────────────────────────────────────────
    if data == "cancel_search":
        await query.edit_message_text(
            "❌ Поиск отменен.\n\nНажми /start чтобы начать заново."
        )
        return ConversationHandler.END

    role = data
    set_role(query.from_user.id, role)
    context.user_data["role"] = role

    role_label = "Администратор" if role == "admin" else "МФУ"
    await query.edit_message_text(
        f"🔍 <b>Поиск ({role_label})</b>\n\n"
        f"Введи свой табельный номер (3-6 цифр):",
        parse_mode="HTML",
        reply_markup=search_keyboard()
    )
    return ENTER_ID


async def enter_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        user_text = update.message.text.strip()

        if not check_rate_limit(user.id):
            await update.message.reply_text(
                "⏱ Слишком много запросов.\n\nПодожди немного и попробуй снова.",
                reply_markup=search_keyboard()
            )
            return ENTER_ID

        ok, err_msg = validate_employee_id(user_text)
        if not ok:
            await update.message.reply_text(err_msg, parse_mode="HTML", reply_markup=search_keyboard())
            return ENTER_ID

        employee_id = normalize_id(user_text)
        role = get_role(user.id) or context.user_data.get("role")

        if not role:
            await update.message.reply_text(
                "⚠️ Не удалось определить роль.\n\nНажми /start чтобы начать заново."
            )
            return SELECT_ROLE

        data = find_employee_in_cache(employee_id, role)

        log_request(
            user_id=user.id,
            username=user.username,
            employee_id=employee_id,
            role=role,
            found=data is not None,
            alert_callback=send_admin_message,
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
            last_refresh = get_last_refresh()
            if last_refresh is None:
                note = "⏳ Кэш ещё загружается — попробуй через минуту."
            else:
                note = f"🕐 Данные актуальны на: {fmt_dt(last_refresh)}"

            await update.message.reply_text(
                f"❌ Табельный <code>{employee_id}</code> не найден.\n\n"
                f"{note}\n\n"
                f"Проверь номер и попробуй ещё раз:",
                parse_mode="HTML",
                reply_markup=search_keyboard()
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
            "⚠️ Что-то пошло не так.\n\nПопробуй ещё раз или нажми /start"
        )
        return SELECT_ROLE
