"""
Генерация PNG-карточки сотрудника через Pillow.
Возвращает bytes — готово для отправки через bot.send_photo().
"""

import io
from PIL import Image, ImageDraw, ImageFont

# ── Пути к шрифтам ──────────────────────────────────────────────────────────
import os as _os
_FONT_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "assets", "fonts")
_FONT_REG  = _os.path.join(_FONT_DIR, "DejaVuSans.ttf")
_FONT_BOLD = _os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")

# ── Палитра ─────────────────────────────────────────────────────────────────
_BG      = (15,  17,  26)
_SURFACE = (24,  28,  42)
_ACCENT  = (99, 145, 255)
_DIVIDER = (38,  44,  64)
_WHITE   = (240, 244, 255)
_MUTED   = (130, 140, 170)
_SUCCESS = ( 72, 199, 142)
_WARN    = (255, 190,  80)
_BADGE   = ( 30,  36,  60)

_W   = 680
_PAD = 40


def _fnt(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    path = _FONT_BOLD if bold else _FONT_REG
    return ImageFont.truetype(path, size)


def _rrect(draw: ImageDraw.Draw, xy, fill, radius: int = 12):
    draw.rounded_rectangle(list(xy), radius=radius, fill=fill)


def _hline(draw: ImageDraw.Draw, y: int):
    draw.line([(_PAD, y), (_W - _PAD, y)], fill=_DIVIDER, width=1)


def _section_label(draw: ImageDraw.Draw, y: int, text: str) -> int:
    draw.text((_PAD, y), text, font=_fnt(True, 13), fill=_ACCENT)
    return y + 24


def _kv_row(draw: ImageDraw.Draw, y: int,
            label: str, value: str,
            value_color=_WHITE, value_size: int = 17) -> int:
    draw.text((_PAD + 8, y), label, font=_fnt(False, 16), fill=_MUTED)
    draw.text((_W - _PAD, y), value,
              font=_fnt(True, value_size), fill=value_color, anchor="ra")
    return y + 28


def _initials(name: str) -> str:
    parts = name.split()
    letters = [p[0] for p in parts if p]
    return "".join(letters[:2]).upper()


def _mini_blocks(draw: ImageDraw.Draw, y: int, blocks: list[tuple]) -> int:
    """blocks = [(label, value, color), ...]  — рисует горизонтальные плитки"""
    count = len(blocks)
    gap   = 12
    bw    = (_W - 2 * _PAD - gap * (count - 1)) // count
    bh    = 72

    for i, (lbl, val, vc) in enumerate(blocks):
        bx = _PAD + i * (bw + gap)
        _rrect(draw, [bx, y, bx + bw, y + bh], _DIVIDER, radius=10)
        draw.text((bx + bw // 2, y + 22), str(val),
                  font=_fnt(True, 22), fill=vc, anchor="mm")
        draw.text((bx + bw // 2, y + 52), lbl,
                  font=_fnt(False, 13), fill=_MUTED, anchor="mm")

    return y + bh + 16


def generate_card(data: dict, role: str) -> bytes:
    """
    data  — словарь из find_employee_in_cache()
    role  — 'admin' | 'mfu'
    return — PNG bytes
    """
    # ── Холст (высота с запасом, обрежем в конце) ───────────────────────────
    img  = Image.new("RGB", (_W, 900), _BG)
    draw = ImageDraw.Draw(img)

    # ── Карточка (surface) ──────────────────────────────────────────────────
    _rrect(draw, [16, 16, _W - 16, 884], _SURFACE, radius=24)

    # Акцентная полоска сверху
    draw.rounded_rectangle([16, 16, _W - 16, 22], radius=24, fill=_ACCENT)

    y = 46

    # ── Аватар с инициалами ─────────────────────────────────────────────────
    initials = _initials(data.get("fio", "??"))
    cx, cy, cr = 76, y + 34, 30
    draw.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=_ACCENT)
    draw.text((cx, cy), initials, font=_fnt(True, 17), fill=_WHITE, anchor="mm")

    # ── ФИО + ПВЗ ───────────────────────────────────────────────────────────
    fio = data.get("fio", "—")
    pvz = data.get("pvz", "—")
    # Если ФИО длинное — уменьшаем шрифт
    fio_size = 17 if len(fio) > 30 else 19
    draw.text((120, y + 6),  fio, font=_fnt(True, fio_size), fill=_WHITE)
    draw.text((120, y + 32), f"📍 ПВЗ: {pvz}", font=_fnt(False, 14), fill=_MUTED)

    y += 80

    # ── Бейдж роли ──────────────────────────────────────────────────────────
    role_label = "👔  Администратор" if role == "admin" else "🖨  МФУ"
    badge_w = 155 if role == "admin" else 100
    _rrect(draw, [_PAD, y, _PAD + badge_w, y + 26], _BADGE, radius=8)
    draw.text((_PAD + 10, y + 5), role_label, font=_fnt(False, 13), fill=_ACCENT)

    y += 44

    _hline(draw, y); y += 16

    # ── ФАКТ ЧАСОВ ──────────────────────────────────────────────────────────
    fact = data.get("fact", "—")
    draw.text((_PAD, y), "⏱  Факт часов", font=_fnt(True, 15), fill=_MUTED)
    draw.text((_W - _PAD, y), str(fact),
              font=_fnt(True, 22), fill=_SUCCESS, anchor="ra")
    y += 38

    _hline(draw, y); y += 16

    # ── ЛИМИТЫ (только для admin) ───────────────────────────────────────────
    if role == "admin":
        y = _section_label(draw, y, "📊  ЛИМИТЫ")
        y = _mini_blocks(draw, y, [
            ("Открыто",     data.get("open_limits", "—"),  _WARN),
            ("План",        data.get("plan_limits", "—"),   _MUTED),
            ("Выполнение",  data.get("execution", "—"),     _SUCCESS),
        ])
        _hline(draw, y); y += 16

    # ── КАРТЫ ───────────────────────────────────────────────────────────────
    y = _section_label(draw, y, "💳  КАРТЫ")
    y = _kv_row(draw, y, "   Виртуальные", str(data.get("virtual_cards", "—")))
    y = _kv_row(draw, y, "   Пластиковые", str(data.get("plastic_cards", "—")))

    y += 4
    _hline(draw, y); y += 16

    # ── ВЧЛ ─────────────────────────────────────────────────────────────────
    vchl = str(data.get("vchl", "—"))
    draw.text((_PAD, y), "🎥  ВЧЛ", font=_fnt(True, 15), fill=_MUTED)
    draw.text((_W - _PAD, y), vchl,
              font=_fnt(True, 20), fill=_SUCCESS, anchor="ra")
    y += 34

    _hline(draw, y); y += 14

    # ── Footer ──────────────────────────────────────────────────────────────
    draw.text((_W // 2, y + 10), "AdminStats · YandexTaxi",
              font=_fnt(False, 12), fill=(55, 63, 90), anchor="mm")

    y += 36

    # ── Обрезаем по реальной высоте ─────────────────────────────────────────
    img = img.crop((0, 0, _W, y + 20))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()
