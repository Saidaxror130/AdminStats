"""
Админская команда /asearch для поиска сотрудников по имени.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from config import ADMIN_ID
from utils.cache_manager import search_employees_by_name, find_employee_in_cache
from utils.helpers import fmt_dt
from utils.cache_manager import get_last_refresh

# ================= STATES =================
ENTER_NAME, SELECT_EMPLOYEE = range(2)


def is_admin(update: Update) -> bool:
    return str(update.effective_user.id) == str(ADMIN_ID)


# ================= FORMATTERS =================

def format_employee_full(data: dict, role: str) -> str:
    """Форматирует полную информацию о сотруднике с табельным номером."""
    if role == "admin":
        return (
            f"👤  <b>{data['fio']}</b>\n"
            f"🏢  <b>ПВЗ:</b> {data['pvz']}\n"
            f"🆔  <b>Табельный:</b> <code>{data['employee_id']}</code>\n"
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
    else:
        return (
            f"👤  <b>{data['fio']}</b>\n"
            f"🏢  <b>ПВЗ:</b> {data['pvz']}\n"
            f"🆔  <b>Табельный:</b> <code>{data['employee_id']}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏱  <b>Факт часов:</b>  {data['fact']}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💳  <b>Карты</b>\n"
            f"   Виртуальные:  {data['virtual_cards']}\n"
            f"   Пластиковые:  {data['plastic_cards']}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🎥  <b>ВЧЛ:</b>  {data['vchl']}"
        )


# ================= HANDLERS =================

async def cmd_asearch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало поиска сотрудника по имени."""
    if not is_admin(update):
        await update.message.reply_text("❌ Нет доступа к этой команде.")
        return ConversationHandler.END

    await update.message.reply_text(
        "🔍 <b>Поиск сотрудника по имени</b>\n\n"
        "Введи имя или фамилию:\n"
        "<i>(например: SAID, AKBAR, RUSTAM)</i>",
        parse_mode="HTML"
    )
    return ENTER_NAME


async def enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка введенного имени и показ результатов."""
    search_query = update.message.text.strip()

    if not search_query:
        await update.message.reply_text("❌ Пустое сообщение.\n\nВведи имя:")
        return ENTER_NAME

    if len(search_query) < 2:
        await update.message.reply_text("❌ Слишком короткий запрос.\n\nВведи минимум 2 символа:")
        return ENTER_NAME

    results = search_employees_by_name(search_query)

    if not results:
        last_refresh = get_last_refresh()
        if last_refresh:
            note = f"🕐 Данные актуальны на: {fmt_dt(last_refresh)}"
        else:
            note = "⏳ Кэш ещё загружается"

        await update.message.reply_text(
            f"❌ Сотрудники с именем '<b>{search_query}</b>' не найдены.\n\n{note}",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    # Ограничиваем до 20 результатов
    if len(results) > 20:
        await update.message.reply_text(
            f"⚠️ Найдено {len(results)} сотрудников — слишком много.\n\n"
            f"Уточни запрос для более точного поиска."
        )
        return ENTER_NAME

    # Сохраняем результаты в context
    context.user_data["search_results"] = results

    # Формируем список и кнопки
    text_lines = [f"✅ Найдено сотрудников: <b>{len(results)}</b>\n"]
    buttons = []

    for idx, emp in enumerate(results, 1):
        role_emoji = "👔" if emp["role"] == "admin" else "🖨"
        text_lines.append(
            f"{idx}. {role_emoji} <b>{emp['fio']}</b>\n"
            f"   ПВЗ: {emp['pvz']} | ID: <code>{emp['employee_id']}</code>"
        )
        # Создаем кнопки по 3 в ряд
        if (idx - 1) % 3 == 0:
            buttons.append([])
        buttons[-1].append(InlineKeyboardButton(str(idx), callback_data=f"emp_{idx-1}"))

    # Добавляем кнопку отмены
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])

    keyboard = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(
        "\n".join(text_lines) + "\n\n👇 Выберите сотрудника:",
        parse_mode="HTML",
        reply_markup=keyboard
    )

    return SELECT_EMPLOYEE


async def select_employee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора сотрудника из списка."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ Поиск отменен.")
        return ConversationHandler.END

    # Извлекаем индекс
    try:
        idx = int(query.data.split("_")[1])
        results = context.user_data.get("search_results", [])

        if idx >= len(results):
            await query.answer("❌ Ошибка: неверный индекс", show_alert=True)
            return ConversationHandler.END

        selected = results[idx]
        employee_id = selected["employee_id"]
        role = selected["role"]

        # Получаем полные данные
        data = find_employee_in_cache(employee_id, role)

        if not data:
            await query.edit_message_text(
                f"❌ Не удалось загрузить данные для сотрудника {selected['fio']}"
            )
            return ConversationHandler.END

        # Показываем полную статистику
        text = format_employee_full(data, role)
        await query.edit_message_text(text, parse_mode="HTML")

        logging.info(f"Admin search: {selected['fio']} ({employee_id}) - {role}")

    except Exception as e:
        logging.error(f"Ошибка при выборе сотрудника: {e}")
        await query.answer("❌ Произошла ошибка", show_alert=True)

    return ConversationHandler.END
