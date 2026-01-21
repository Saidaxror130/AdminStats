import logging
import requests
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Токен бота - читается из переменной окружения
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    raise ValueError('TELEGRAM_BOT_TOKEN не установлен. Добавьте TELEGRAM_BOT_TOKEN в .env файл.')

# Настройка Google Sheets API - читается из переменной окружения
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
API_KEY = os.getenv('GOOGLE_API_KEY')
if not SPREADSHEET_ID:
    raise ValueError('SPREADSHEET_ID не установлен. Добавьте SPREADSHEET_ID в .env файл.')
if not API_KEY:
    raise ValueError('GOOGLE_API_KEY не установлен. Добавьте GOOGLE_API_KEY в .env файл.')

def load_records(api_url):
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        data = response.json()
        values = data.get('values', [])
        if values:
            headers = values[0]
            records = [dict(zip(headers, row)) for row in values[1:]]
            logging.info(f"Загружено {len(records)} записей из {api_url.split('values/')[1].split('!')[0]}.")
            return records
        else:
            return []
    except Exception as e:
        logging.error(f"Не удалось загрузить данные: {e}")
        return []


# Загрузка Заголовка
API_URL_INFO = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/Администраторы!B1:Z1?key={API_KEY}"
info_records = load_records(API_URL_INFO)

# Загрузка данных для Администраторов
API_URL_ADMIN = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/Администраторы!A2:Z1000?key={API_KEY}"

# Загрузка данных для МФУ
API_URL_MFU = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/МФУ!A2:Z1000?key={API_KEY}"

def get_records_by_role(role: str):
    if role == "admin":
        return load_records(API_URL_ADMIN)
    elif role == "mfu":
        return load_records(API_URL_MFU)
    return []


# Состояния разговора
SELECT_ROLE, ENTER_ID = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Админ", callback_data="admin")],
        [InlineKeyboardButton("МФУ (Менеджер финансовых услуг)", callback_data="mfu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Привет! Я бот для просмотра показателей сотрудников.\n\nВыберите вашу должность:",
        reply_markup=reply_markup
    )
    return SELECT_ROLE

async def select_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    role = query.data
    context.user_data['role'] = role
    await query.edit_message_text("Введите табельный номер:")
    return ENTER_ID

async def enter_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        employee_id = update.message.text.strip().replace(',', '')
        role = context.user_data.get('role')
        logging.info(f"Введен ID: {employee_id}, Роль: {role}")
        if role == "admin":
            records = get_records_by_role(role)
            data = get_employee_data(employee_id, records)
            if data:
                text = f'''*{info_records[0] if info_records else ''}*

*ФИО:* {data['fio']}
*ПВЗ:* {data['pvz']}

*Факт часов:* {data['fact']}

*Кол. открытых лимитов:* {data['open_limits']}
*План по лимитам:* {data['plan_limits']}
*Выполнение плана:* {data['execution']}

*Оформленные виртуальные карты:* {data['virtual_cards']}
*Оформленные пластиковые карты:* {data['plastic_cards']}

*ВЧЛ:* {data['vchl']}

Выберите должность для нового поиска:'''
                keyboard = [
                    [InlineKeyboardButton("Админ", callback_data="admin")],
                    [InlineKeyboardButton("МФУ (Менеджер финансовых услуг)", callback_data="mfu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)
                return SELECT_ROLE
            else:
                text = 'Данные не найдены. Введите табельный номер:'
                await update.message.reply_text(text, parse_mode='Markdown')
                return ENTER_ID
        elif role == "mfu":
            records = get_records_by_role(role)
            data = get_employee_data(employee_id, records)
            logging.info(f"Найдены данные для МФУ: {data is not None}")
            if data:
                text = f'''*{info_records[0] if info_records else ''}*

*ФИО:* {data['fio']}
*ПВЗ:* {data['pvz']}

*Факт часов:* {data['fact']}

*Оформленные виртуальные карты:* {data['virtual_cards']}
*Оформленные пластиковые карты:* {data['plastic_cards']}

*ВЧЛ:* {data['vchl']}

Выберите должность для нового поиска:'''
                keyboard = [
                    [InlineKeyboardButton("Админ", callback_data="admin")],
                    [InlineKeyboardButton("МФУ (Менеджер финансовых услуг)", callback_data="mfu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)
                return SELECT_ROLE
            else:
                text = 'Данные не найдены. Введите табельный номер:'
                await update.message.reply_text(text, parse_mode='Markdown')
                return ENTER_ID
        else:
            text = "Ошибка роли."
        await update.message.reply_text(text, parse_mode='Markdown')
        return SELECT_ROLE
    except Exception as e:
        logging.error(f"Ошибка в enter_id: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте снова.")
        return SELECT_ROLE

def get_employee_data(employee_id, records):
    if not records:
        return None
    for row in records:
        table_id = str(row.get('Табельный номер', '')).replace(',', '')
        if table_id == employee_id:
            return {
                'fio': row.get('ФИО', 'N/A'),
                'pvz': row.get('ПВЗ', 'N/A'),
                'fact': row.get('Факт', 'N/A'),
                'open_limits': row.get('Открыто Лимитов', 'N/A'),
                'plan_limits': row.get('План по лимитам', 'N/A'),
                'execution': row.get('Выполнение плана по лимитам', 'N/A'),
                'virtual_cards': row.get(' 📱Оформленно виртуальных карт', 'N/A'),
                'plastic_cards': row.get('💷Оформленно пластиковых карт', 'N/A'),
                'vchl': row.get('ВЧЛ', 'N/A')
            }
    return None

if __name__ == '__main__':
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SELECT_ROLE: [CallbackQueryHandler(select_role)],
            ENTER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_id)],
        },
        fallbacks=[CommandHandler('start', start)],
    )

    application.add_handler(conv_handler)


    application.run_polling()
