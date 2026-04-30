"""
Команда /pvz для поиска всех сотрудников конкретного ПВЗ.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from utils.cache_manager import search_employees_by_pvz, find_employee_in_cache
from utils.helpers import fmt_dt, normalize_pvz
from utils.cache_manager import get_last_refresh

# ================= STATES =================
ENTER_PVZ, SELECT_EMPLOYEE_PVZ = range(2)


# ================= FORMATTERS =================

def format_employee_short(emp: dict) -> str:
    """Форматирует краткую информацию о сотруднике для списка."""
    role_emoji = "👔" if emp["role"] == "admin" else "🖨"
    return (
        f"{role_emoji} <b>{emp['fio']}</b>\n"
        f"   ID: <code>{emp['employee_id']}</code> | "
        f"Факт: {emp['fact']} | ВЧЛ: {emp['vchl']}"
    )


def format_employee_full(data: dict, role: str) -> str:
    """Форматирует полную информацию о сотруднике."""
    if role == "admin":
        return (
            f"👤  <b>{data['fio']}</b>\n"
            f"🏢  <b>ПВЗ:</b> {data['pvz']}\n"
            f"🆔  <b>Табельный:</b> <code>{data['employee_id']}</code>\n"
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
    else:
        return (
            f"👤  <b>{data['fio']}</b>\n"
            f"🏢  <b>ПВЗ:</b> {data['pvz']}\n"
            f"🆔  <b>Табельный:</b> <code>{data['employee_id']}</code>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"⏱  <b>Факт часов:</b>  {data['fact']}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"💳  <b>Карты</b>\n"
            f"   Виртуальные:  {data['virtual_cards']}\n"
            f"   Пластиковые:  {data['plastic_cards']}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"🎥  <b>ВЧЛ:</b>  {data['vchl']}"
        )


# ================= HANDLERS =================

async def cmd_pvz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало поиска сотрудников по ПВЗ."""
    await update.message.reply_text(
        "🏢 <b>Поиск по ПВЗ</b>\n\n"
        "Введи название ПВЗ:\n"
        "<i>(например: ТАШ-5, Таш-5, tash-5, Самарканд-12)</i>",
        parse_mode="HTML"
    )
    return ENTER_PVZ


async def enter_pvz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка введенного названия ПВЗ и показ результатов."""
    pvz_query = update.message.text.strip()

    if not pvz_query:
        await update.message.reply_text("❌ Пустое сообщение.\n\nВведи название ПВЗ:")
        return ENTER_PVZ

    if len(pvz_query) < 2:
        await update.message.reply_text("❌ Слишком короткий запрос.\n\nВведи минимум 2 символа:")
        return ENTER_PVZ

    # Нормализуем для отображения
    normalized = normalize_pvz(pvz_query)

    results = search_employees_by_pvz(pvz_query)

    if not results:
        last_refresh = get_last_refresh()
        if last_refresh:
            note = f"🕐 Данные актуальны на: {fmt_dt(last_refresh)}"
        else:
            note = "⏳ Кэш ещё загружается"

        await update.message.reply_text(
            f"❌ Сотрудники ПВЗ '<b>{normalized}</b>' не найдены.\n\n{note}",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    # Ограничиваем до 30 результатов
    if len(results) > 30:
        await update.message.reply_text(
            f"⚠️ Найдено {len(results)} сотрудников — слишком много для отображения.\n\n"
            f"Показываю первых 30:"
        )
        results = results[:30]

    # Сохраняем результаты в context
    context.user_data["pvz_results"] = results
    context.user_data["pvz_name"] = normalized

    # Формируем список и кнопки
    text_lines = [
        f"🏢 <b>ПВЗ: {normalized}</b>\n",
        f"👥 Найдено сотрудников: <b>{len(results)}</b>\n"
    ]

    # Группируем по ролям
    admins = [e for e in results if e["role"] == "admin"]
    mfu = [e for e in results if e["role"] == "mfu"]

    if admins:
        text_lines.append(f"\n👔 <b>Администраторы ({len(admins)}):</b>")
        for idx, emp in enumerate(admins, 1):
            text_lines.append(f"{idx}. {format_employee_short(emp)}")

    if mfu:
        text_lines.append(f"\n🖨 <b>МФУ ({len(mfu)}):</b>")
        for idx, emp in enumerate(mfu, len(admins) + 1):
            text_lines.append(f"{idx}. {format_employee_short(emp)}")

    # Создаем кнопки (по 5 в ряд)
    buttons = []
    for idx in range(len(results)):
        if idx % 5 == 0:
            buttons.append([])
        buttons[-1].append(InlineKeyboardButton(str(idx + 1), callback_data=f"pvz_{idx}"))

    # Добавляем кнопку отмены
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_pvz")])

    keyboard = InlineKeyboardMarkup(buttons)

    # Отправляем сообщение (может быть длинным, разбиваем если нужно)
    full_text = "\n".join(text_lines) + "\n\n👇 Выбери сотрудника для подробной информации:"

    if len(full_text) > 4000:
        # Telegram лимит 4096 символов, отправляем по частям
        await update.message.reply_text(
            "\n".join(text_lines[:len(text_lines)//2]),
            parse_mode="HTML"
        )
        await update.message.reply_text(
            "\n".join(text_lines[len(text_lines)//2:]) + "\n\n👇 Выбери сотрудника:",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            full_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    return SELECT_EMPLOYEE_PVZ


async def select_employee_pvz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора сотрудника из списка ПВЗ."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_pvz":
        await query.edit_message_text("❌ Поиск отменен.")
        return ConversationHandler.END

    # Извлекаем индекс
    try:
        idx = int(query.data.split("_")[1])
        results = context.user_data.get("pvz_results", [])

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

        logging.info(f"PVZ search: {selected['fio']} ({employee_id}) - {selected['pvz']}")

    except Exception as e:
        logging.error(f"Ошибка при выборе сотрудника из ПВЗ: {e}")
        await query.answer("❌ Произошла ошибка", show_alert=True)

    return ConversationHandler.END
