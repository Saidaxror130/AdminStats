"""
Генерация PNG-карточки сотрудника через Pillow.
Возвращает bytes — готово для bot.send_photo().
"""

import io
import os as _os
from PIL import Image, ImageDraw, ImageFont

_FONT_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "assets", "fonts")
_REG  = lambda s: ImageFont.truetype(_os.path.join(_FONT_DIR, "DejaVuSans.ttf"), s)
_BOLD = lambda s: ImageFont.truetype(_os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf"), s)

BG      = (18,  20,  28)
SURFACE = (28,  32,  44)
CARD    = (34,  38,  54)
GREEN   = (80, 255, 160)
RED     = (220,  70,  70)
YELLOW  = (255, 185,  50)
WHITE   = (235, 242, 255)
MUTED   = (140, 155, 190)
W       = 520
PAD     = 24
ICON    = (90, 200, 140)


def _rrect(draw, xy, fill, r=18):
    draw.rounded_rectangle(list(xy), radius=r, fill=fill)


def _exec_color(val):
    try:
        n = float(str(val).replace("%", "").replace(",", ".").strip())
        return GREEN if n >= 80 else (YELLOW if n >= 50 else RED)
    except Exception:
        return MUTED


def _initials(name: str) -> str:
    return "".join(p[0] for p in name.split() if p)[:2].upper()


# ── Иконки (чистая геометрия, без emoji) ────────────────────────────────────

def _icon_clock(draw, cx, cy, r=14):
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=ICON, width=2)
    draw.line([cx, cy, cx, cy-r+4], fill=ICON, width=2)
    draw.line([cx, cy, cx+r-5, cy+3], fill=ICON, width=2)
    draw.ellipse([cx-2, cy-2, cx+2, cy+2], fill=ICON)


def _icon_chart(draw, cx, cy, r=13):
    bw = 5
    for x, h in zip([cx-9, cx-2, cx+5], [8, 13, 10]):
        draw.rectangle([x, cy+r-h, x+bw, cy+r], fill=ICON)
    draw.line([cx-r, cy+r+1, cx+r, cy+r+1], fill=ICON, width=1)


def _icon_card(draw, cx, cy, r=13):
    draw.rounded_rectangle([cx-r, cy-8, cx+r, cy+8], radius=3, outline=ICON, width=2)
    draw.line([cx-r+2, cy-2, cx+r-2, cy-2], fill=ICON, width=3)


def _icon_play(draw, cx, cy, r=13):
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=ICON, width=2)
    draw.polygon([cx-4, cy-7, cx-4, cy+7, cx+8, cy], fill=ICON)


def _checkmark(draw, cx, cy, r=16):
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=GREEN, width=2)
    # галочка
    pts = [(cx-8, cy), (cx-2, cy+7), (cx+9, cy-7)]
    for i in range(len(pts)-1):
        draw.line([pts[i], pts[i+1]], fill=GREEN, width=3)



def _shadow(draw, xy, r=18):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(
        [x1+2, y1+4, x2+2, y2+4],
        radius=r,
        fill=(10, 12, 18)
    )

# ── Главная функция ──────────────────────────────────────────────────────────

def generate_card(data: dict, role: str) -> bytes:
    def _gradient(h):
        img = Image.new("RGB", (W, h), BG)
        px = img.load()
        for y in range(h):
            t = y / h
            r = int(18 + t * 8)
            g = int(20 + t * 10)
            b = int(28 + t * 18)
            for x in range(W):
                px[x, y] = (r, g, b)
        return img
    img = _gradient(820)
    draw = ImageDraw.Draw(img)
    y    = PAD

    # Аватар
    cr = 38
    cx, cy_av = PAD + cr, y + cr + 8
    draw.ellipse([cx-cr, cy_av-cr, cx+cr, cy_av+cr], fill=GREEN)
    draw.text((cx, cy_av), _initials(data.get("fio", "??")),
              font=_BOLD(20), fill=(10, 20, 10), anchor="mm")

    # ФИО (перенос на 2-ю строку если длинное)
    fio   = data.get("fio", "—")
    words = fio.split()
    line1 = " ".join(words[:2]) if len(words) > 2 else fio
    line2 = " ".join(words[2:]) if len(words) > 2 else ""
    tx = cx + cr + 18
    draw.text((tx, y + 10), line1, font=_BOLD(20), fill=WHITE)
    if line2:
        draw.text((tx, y + 36), line2, font=_BOLD(20), fill=WHITE)
    draw.text((tx, y + (62 if line2 else 38)),
              f"ПВЗ: {data.get('pvz', '—')}", font=_REG(15), fill=MUTED)

    y = cy_av + cr + 18

    # Бейдж роли
    role_label = "Администратор" if role == "admin" else "МФУ"
    bw = len(role_label) * 10 + 32
    BADGE_BG = (30, 90, 60)
    BADGE_TX = (120, 255, 170)

    _rrect(draw, [PAD, y, PAD + bw, y + 32], BADGE_BG, r=10)
    draw.text((PAD + 16, y + 7), role_label, font=_BOLD(15), fill=BADGE_TX)
    y += 50

    # ── Блок: Факт часов ────────────────────────────────────────────────────
    _shadow(draw, [PAD, y, W-PAD, y+68])
    _rrect(draw, [PAD, y, W-PAD, y+68], CARD)
    _icon_clock(draw, PAD+30, y+34)
    draw.text((PAD+54, y+18), "ФАКТ ЧАСОВ", font=_BOLD(13), fill=MUTED)
    draw.text((W-PAD-12, y+10), str(data.get("fact", "—")),
              font=_BOLD(34), fill=GREEN, anchor="ra")
    y += 80

    # ── Блок: Лимиты (только admin) ─────────────────────────────────────────
    if role == "admin":
        _shadow(draw, [PAD, y, W-PAD, y+68])
        _rrect(draw, [PAD, y, W-PAD, y+68], CARD)
        _icon_chart(draw, PAD+30, y+38)
        draw.text((PAD+54, y+14), "ЛИМИТЫ", font=_BOLD(13), fill=MUTED)

        ratio = f"{data.get('open_limits','—')} / {data.get('plan_limits','—')}"
        draw.text((PAD+54, y+34), ratio, font=_BOLD(26), fill=GREEN)
        draw.text((PAD+54, y+66), "Открыто / План", font=_REG(13), fill=MUTED)

        ec = _exec_color(data.get("execution", "0"))
        draw.text((W-PAD-12, y+28), str(data.get("execution", "—")),
                  font=_BOLD(30), fill=ec, anchor="ra")
        draw.text((W-PAD-12, y+64), "Выполнение", font=_REG(13), fill=MUTED, anchor="ra")
        y += 102

    # ── Блок: Карты ─────────────────────────────────────────────────────────
    _shadow(draw, [PAD, y, W-PAD, y+68])
    _rrect(draw, [PAD, y, W-PAD, y+68], CARD)
    _icon_card(draw, PAD+30, y+38)
    draw.text((PAD+54, y+14), "КАРТЫ", font=_BOLD(13), fill=MUTED)

    mid = W // 2
    draw.text((mid-40, y+34), str(data.get("virtual_cards", "—")), font=_BOLD(30), anchor="mm", fill=WHITE)
    draw.text((mid-40, y+66), "Виртуальные", font=_REG(13), fill=MUTED)
    draw.text((W-PAD-12, y+34), str(data.get("plastic_cards", "—")),
              font=_BOLD(30), fill=WHITE, anchor="ra")
    draw.text((W-PAD-12, y+66), "Пластиковые", font=_REG(13), fill=MUTED, anchor="ra")
    y += 102

    # ── Блок: ВЧЛ ───────────────────────────────────────────────────────────
    _shadow(draw, [PAD, y, W-PAD, y+68])
    _rrect(draw, [PAD, y, W-PAD, y+68], CARD)
    _icon_play(draw, PAD+30, y+34)
    draw.text((PAD+54, y+18), "ВЧЛ", font=_BOLD(13), fill=MUTED)

    vchl_val   = str(data.get("vchl", "—"))
    vchl_color = _exec_color(vchl_val)
    is_100     = vchl_val.strip() in ("100%", "100")
    vx = W-PAD-50 if is_100 else W-PAD-12
    draw.text((vx, y+10), vchl_val, font=_BOLD(34), fill=vchl_color, anchor="ra")
    if is_100:
        _checkmark(draw, W-PAD-22, y+34)
        draw.ellipse(
            [W-PAD-32, y+20, W-PAD-12, y+48],
            outline=(80, 255, 160)
        )
    y += 80

    # Footer
    y += 8
    draw.text((W//2, y+10), "AdminStats  •  @PZStatsBot",
              font=_REG(12), fill=(55, 65, 90), anchor="mm")
    y += 32

    img = img.crop((0, 0, W, y+12))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()
