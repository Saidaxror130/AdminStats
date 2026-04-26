from datetime import datetime, timedelta, timezone

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
