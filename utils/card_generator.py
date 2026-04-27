"""
Генерация PNG-карточки сотрудника через Pillow.
Иконки из assets/icons/*.png (64x64 RGBA).
"""

import io
import os as _os
from PIL import Image, ImageDraw, ImageFont

_BASE     = _os.path.dirname(_os.path.abspath(__file__))
_FONT_DIR = _os.path.join(_BASE, "..", "assets", "fonts")
_ICON_DIR = _os.path.join(_BASE, "..", "assets", "icons")

_REG  = lambda s: ImageFont.truetype(_os.path.join(_FONT_DIR, "DejaVuSans.ttf"), s)
_BOLD = lambda s: ImageFont.truetype(_os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf"), s)

BG      = (18,  20,  28)
CARD    = (34,  38,  54)
GREEN   = (46,  204, 110)
RED     = (220,  70,  70)
YELLOW  = (255, 185,  50)
WHITE   = (235, 242, 255)
MUTED   = (110, 125, 160)
DIVIDER = (55,  62,  85)

W   = 520
PAD = 24


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


def _paste_icon(base: Image.Image, name: str, x: int, y: int, size: int = 26):
    path = _os.path.join(_ICON_DIR, f"{name}.png")
    icon = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
    base.paste(icon, (x, y), icon)


def generate_card(data: dict, role: str) -> bytes:
    img  = Image.new("RGB", (W, 820), BG)
    draw = ImageDraw.Draw(img)
    y    = PAD

    # Аватар
    cr = 38
    cx, cy_av = PAD+cr, y+cr+8
    draw.ellipse([cx-cr, cy_av-cr, cx+cr, cy_av+cr], fill=GREEN)
    draw.text((cx, cy_av), _initials(data.get("fio", "??")),
              font=_BOLD(20), fill=(10, 20, 10), anchor="mm")

    # ФИО + ПВЗ
    fio   = data.get("fio", "—")
    words = fio.split()
    line1 = " ".join(words[:2]) if len(words) > 2 else fio
    line2 = " ".join(words[2:]) if len(words) > 2 else ""
    tx = cx+cr+18
    draw.text((tx, y+10), line1, font=_BOLD(20), fill=WHITE)
    if line2:
        draw.text((tx, y+36), line2, font=_BOLD(20), fill=WHITE)
    draw.text((tx, y+(62 if line2 else 38)),
              f"ПВЗ: {data.get('pvz', '—')}", font=_REG(15), fill=MUTED)

    y = cy_av+cr+18

    # Бейдж роли
    role_label = "Администратор" if role == "admin" else "МФУ"
    bw = len(role_label)*10+32
    _rrect(draw, [PAD, y, PAD+bw, y+32], GREEN, r=8)
    draw.text((PAD+16, y+7), role_label, font=_BOLD(15), fill=(10, 20, 10))
    y += 50

    # ── Факт часов ───────────────────────────────────────────────────────────
    _rrect(draw, [PAD, y, W-PAD, y+68], CARD)
    _paste_icon(img, "clock", PAD+14, y+21, size=26)
    draw.text((PAD+50, y+20), "ФАКТ ЧАСОВ", font=_BOLD(13), fill=MUTED)
    draw.text((W-PAD-12, y+10), str(data.get("fact", "—")),
              font=_BOLD(34), fill=GREEN, anchor="ra")
    y += 80

    # ── Лимиты (только admin) ────────────────────────────────────────────────
    if role == "admin":
        _rrect(draw, [PAD, y, W-PAD, y+90], CARD)
        _paste_icon(img, "chart", PAD+14, y+24, size=26)
        draw.text((PAD+50, y+14), "ЛИМИТЫ", font=_BOLD(13), fill=MUTED)

        ratio = f"{data.get('open_limits','—')} / {data.get('plan_limits','—')}"
        draw.text((PAD+50, y+34), ratio, font=_BOLD(26), fill=GREEN)
        draw.text((PAD+50, y+66), "Открыто / План", font=_REG(13), fill=MUTED)

        ec = _exec_color(data.get("execution", "0"))
        draw.text((W-PAD-12, y+26), str(data.get("execution", "—")),
                  font=_BOLD(30), fill=ec, anchor="ra")
        draw.text((W-PAD-12, y+62), "Выполнение", font=_REG(13), fill=MUTED, anchor="ra")
        y += 102

    # ── Карты ────────────────────────────────────────────────────────────────
    _rrect(draw, [PAD, y, W-PAD, y+90], CARD)
    _paste_icon(img, "card", PAD+14, y+24, size=26)
    draw.text((PAD+50, y+14), "КАРТЫ", font=_BOLD(13), fill=MUTED)

    mid = W // 2
    draw.line([(mid, y+30), (mid, y+80)], fill=DIVIDER, width=1)

    lc = (PAD+50+mid) // 2
    draw.text((lc, y+34), str(data.get("virtual_cards", "—")),
              font=_BOLD(30), fill=WHITE, anchor="mm")
    draw.text((lc, y+66), "Виртуальные", font=_REG(13), fill=MUTED, anchor="mm")

    rc = (mid+W-PAD) // 2
    draw.text((rc, y+34), str(data.get("plastic_cards", "—")),
              font=_BOLD(30), fill=WHITE, anchor="mm")
    draw.text((rc, y+66), "Пластиковые", font=_REG(13), fill=MUTED, anchor="mm")
    y += 102

    # ── ВЧЛ ──────────────────────────────────────────────────────────────────
    _rrect(draw, [PAD, y, W-PAD, y+68], CARD)
    _paste_icon(img, "play", PAD+14, y+21, size=26)
    draw.text((PAD+50, y+20), "ВЧЛ", font=_BOLD(13), fill=MUTED)

    vchl_val   = str(data.get("vchl", "—"))
    vchl_color = _exec_color(vchl_val)
    is_100     = vchl_val.strip() in ("100%", "100")

    if is_100:
        draw.text((W-PAD-46, y+10), vchl_val,
                  font=_BOLD(34), fill=vchl_color, anchor="ra")
        _paste_icon(img, "check", W-PAD-38, y+18, size=32)
    else:
        draw.text((W-PAD-12, y+10), vchl_val,
                  font=_BOLD(34), fill=vchl_color, anchor="ra")
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
