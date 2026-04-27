from datetime import datetime, timedelta, timezone
import re

TZ_TASHKENT = timezone(timedelta(hours=5))


def now_tashkent() -> datetime:
    """Возвращает текущее время по Ташкенту."""
    return datetime.now(tz=TZ_TASHKENT)


def fmt_dt(dt: datetime) -> str:
    """Форматирует дату/время: дд.мм.гггг чч:мм"""
    return dt.strftime("%d.%m.%Y | %H:%M")


def normalize_id(value) -> str:
    if value is None:
        return ""
    return (
        str(value)
        .replace(",", "")
        .replace(" ", "")
        .replace("\xa0", "")
        .strip()
    )


def normalize_pvz(pvz_name: str) -> str:
    """
    Нормализует название ПВЗ к единому формату.

    Примеры:
        "Таш-5" -> "ТАШ-5"
        "tash-5" -> "ТАШ-5"
        "ТАШКЕНТ-5" -> "ТАШ-5"
        "Сам-12" -> "САМ-12"
        "samarkand-12" -> "САМ-12"

    Returns:
        Нормализованное название в формате "КОД-НОМЕР" или исходную строку
    """
    if not pvz_name:
        return ""

    # Убираем лишние пробелы и приводим к верхнему регистру
    pvz = pvz_name.strip().upper()

    # Словарь замен для разных вариантов написания городов
    city_replacements = {
        "ТАШКЕНТ": "ТАШ",
        "TASHKENT": "ТАШ",
        "TASH": "ТАШ",
        "ТАШ": "ТАШ",
        "ТАSH": "ТАШ",

        "САМАРКАНД": "САМ",
        "SAMARKAND": "САМ",
        "SAMAR": "САМ",
        "SAM": "САМ",
        "САМ": "САМ",

        "БУХАРА": "БУХ",
        "BUKHARA": "БУХ",
        "BUKH": "БУХ",
        "BUH": "БУХ",
        "БУХ": "БУХ",

        "АНДИЖАН": "АНД",
        "ANDIJAN": "АНД",
        "ANDI": "АНД",
        "AND": "АНД",
        "АНД": "АНД",

        "НАМАНГАН": "НАМ",
        "NAMANGAN": "НАМ",
        "NAMA": "НАМ",
        "NAM": "НАМ",
        "НАМ": "НАМ",

        "ФЕРГАНА": "ФЕР",
        "FERGANA": "ФЕР",
        "FERG": "ФЕР",
        "FER": "ФЕР",
        "ФЕР": "ФЕР",

        "ХИВА": "ХИВ",
        "KHIVA": "ХИВ",
        "XIVA": "ХИВ",
        "HIV": "ХИВ",
        "ХИВ": "ХИВ",

        "НУКУС": "НУК",
        "NUKUS": "НУК",
        "NUK": "НУК",
        "НУК": "НУК",
    }

    # Ищем паттерн: буквы + дефис/пробел + цифры
    match = re.match(r'^([А-ЯA-Z]+)[\s\-]*(\d+)$', pvz)

    if match:
        city_part = match.group(1)
        number_part = match.group(2)

        # Заменяем город на короткий код
        normalized_city = city_replacements.get(city_part, city_part[:3])

        return f"{normalized_city}-{number_part}"

    # Если не подошел паттерн, возвращаем как есть
    return pvz


def extract_pvz_number(pvz_name: str) -> str:
    """
    Извлекает только номер из названия ПВЗ.

    Примеры:
        "ТАШ-5" -> "5"
        "САМ-12" -> "12"
        "Ташкент-5" -> "5"

    Returns:
        Номер ПВЗ или пустую строку
    """
    match = re.search(r'(\d+)', pvz_name)
    return match.group(1) if match else ""

