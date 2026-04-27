"""
Отправка уведомлений администратору бота.
"""

import logging
import requests
from config import TOKEN, ADMIN_ID


def send_admin_message(text: str):
    """Отправляет сообщение администратору бота."""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": ADMIN_ID, "text": text}, timeout=10)
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение админу: {e}")
