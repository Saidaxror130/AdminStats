import logging
import requests
from config import API_KEY
from .admin_notifier import send_admin_message


def load_sheet_values(api_url: str, token: str = None, admin_id: str = None) -> list:
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
        send_admin_message(error_text)
        return []

    except Exception as e:
        error_text = f"🚨 Ошибка загрузки таблицы\n\nURL:\n{api_url}\n\nОшибка:\n{e}"
        logging.error(error_text)
        send_admin_message(error_text)
        return []


def load_records(api_url: str, token: str = None, admin_id: str = None) -> list:
    values = load_sheet_values(api_url)
    if not values:
        logging.warning("⚠️ Таблица пустая или не загрузилась")
        return []
    headers = values[0]
    return [dict(zip(headers, row)) for row in values[1:]]


def get_registry_ids(registry_spreadsheet_id: str, token: str = None, admin_id: str = None) -> list:
    api_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{registry_spreadsheet_id}"
        f"/values/A2:A?key={API_KEY}"
    )
    values = load_sheet_values(api_url)
    ids = [row[0].strip() for row in values if row and row[0]]
    logging.info(f"Загружено {len(ids)} spreadsheet_id из реестра")
    return ids


def build_role_url(spreadsheet_id: str, role: str) -> str:
    sheet_name = "Администраторы" if role == "admin" else "МФУ"
    return (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        f"/values/{sheet_name}!A2:Z1000?key={API_KEY}"
    )
