import logging
import requests
from config import API_KEY


def send_admin_message_raw(token: str, admin_id: str, text: str):
    """Низкоуровневая отправка сообщения админу через requests (используется до старта бота)."""
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": admin_id, "text": text}, timeout=10)
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение админу: {e}")


def load_sheet_values(api_url: str, token: str, admin_id: str) -> list:
    try:
        response = requests.get(api_url, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data.get("values", [])

    except requests.exceptions.HTTPError as e:
        error_text = (
            f"🚨 Ошибка Google API\n\nURL:\n{api_url}\n\n"
            f"Status:\n{e.response.status_code}\n\nОтвет:\n{e.response.text}"
        )
        logging.error(error_text)
        send_admin_message_raw(token, admin_id, error_text)
        return []

    except Exception as e:
        error_text = f"🚨 Ошибка загрузки таблицы\n\nURL:\n{api_url}\n\nОшибка:\n{e}"
        logging.error(error_text)
        send_admin_message_raw(token, admin_id, error_text)
        return []


def load_records(api_url: str, token: str, admin_id: str) -> list:
    values = load_sheet_values(api_url, token, admin_id)
    if not values:
        logging.warning("⚠️ Таблица пустая или не загрузилась")
        return []
    headers = values[0]
    return [dict(zip(headers, row)) for row in values[1:]]


def get_registry_ids(registry_spreadsheet_id: str, token: str, admin_id: str) -> list:
    api_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{registry_spreadsheet_id}"
        f"/values/A2:A?key={API_KEY}"
    )
    values = load_sheet_values(api_url, token, admin_id)
    ids = [row[0].strip() for row in values if row and row[0]]
    logging.info(f"Загружено {len(ids)} spreadsheet_id из реестра")
    return ids


def build_role_url(spreadsheet_id: str, role: str) -> str:
    sheet_name = "Администраторы" if role == "admin" else "МФУ"
    return (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        f"/values/{sheet_name}!A2:Z1000?key={API_KEY}"
    )
