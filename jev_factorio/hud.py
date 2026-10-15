"""The Jev decision panel, drawn as a PIL image from one decisions.jsonl record.
Used by the live view now and by the video renderer later, so both look the same."""

from functools import cache, lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import config

BG = (14, 16, 20)
CARD = (25, 28, 34)
TEXT = (232, 232, 232)
DIM = (140, 146, 158)
ACCENT = (255, 160, 40)  # Factorio orange
GOOD = (96, 206, 128)
BAR_BG = (45, 49, 58)
BOX = (255, 210, 0)

PAD = 20
DIRECTION_ORDER = [
    "up", "up_right", "right", "down_right", "down", "down_left", "left", "up_left",
    "here", "not_visible",
]  # fmt: skip


@cache
def font(size: int, bold: bool = False, mono: bool = True):
    name = ("consolab.ttf" if bold else "consola.ttf") if mono else "bahnschrift.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default(size)


@lru_cache(maxsize=4)
def _load_image(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def _card(draw: ImageDraw.ImageDraw, top: int, bottom: int, title: str):
    draw.rounded_rectangle((PAD / 2, top, config.PANEL_SIZE[0] - PAD / 2, bottom), 8, fill=CARD)
    draw.text((PAD, top + 10), title, fill=DIM, font=font(15, bold=True))


def _bar(draw, x: int, y: int, w: int, h: int, value: float, colour, marker: float | None = None):
    value = max(0.0, min(1.0, value))
    draw.rectangle((x, y, x + w, y + h), fill=BAR_BG)
    if value > 0:
        draw.rectangle((x, y, x + round(w * value), y + h), fill=colour)
    if marker is not None:
        mx = x + round(w * max(0.0, min(1.0, marker)))
        draw.rectangle((mx - 1, y - 3, mx + 1, y + h + 3), fill=TEXT)


def _draw_box(img: Image.Image, box: list[float], label: str):
    left, top, right, bottom = box
    draw = ImageDraw.Draw(img)
    xy = (left * img.width, top * img.height, right * img.width, bottom * img.height)
    draw.rectangle(xy, outline=BOX, width=3)
    draw.text((xy[0] + 3, xy[1] - 18), label, fill=BOX, font=font(14, bold=True))


def render(record: dict | None, run_dir: Path, now: float) -> Image.Image:
    w, h = config.PANEL_SIZE
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)

    draw.text((PAD, 14), "JEV PLAYS FACTORIO", fill=ACCENT, font=font(38, mono=False))
    if record is None or "jev" not in record:
        draw.text((PAD, 70), "waiting for the first decision...", fill=DIM, font=font(18))
        return img

    jev = record["jev"]
    mini_ans, screen_ans = jev["minimap"]["answers"], jev["screen"]["answers"]
    name = record.get("target_name", "target")
    draw.text(
        (PAD, 62),
        f"{config.JEV_MODEL}  |  tick {record['tick']:03d}  |  {record.get('objective', '')}",
        fill=DIM,
        font=font(17),
    )

    # ---- Decision ----
    y = 96
    _card(draw, y, y + 120, "ACTION")
    action = record["action"]["name"].replace("_", " ")
    decision = record.get("decision", {})
    colour = GOOD if decision.get("source") == "arrived" else TEXT
    draw.text((PAD, y + 32), action.upper(), fill=colour, font=font(34, bold=True))
    source = decision.get("source", "")
    draw.text((PAD, y + 80), f"[{source}] {decision.get('reason', '')}", fill=DIM, font=font(16))

    # ---- Minimap with Jev's box, plus yes/no signals ----
    y = 228
    _card(draw, y, y + 340, "MINIMAP (what Jev sees)")
    mini_path = run_dir / record.get("images", {}).get("minimap", "")
    if mini_path.is_file():
        mini = _load_image(mini_path).resize((290, 290), Image.Resampling.NEAREST)
        mbox = mini_ans["box_minimap"]
        _draw_box(mini, mbox["box"], f"{name} {mbox['confidence'] or 0:.2f}")
        img.paste(mini, (PAD, y + 38))

    x, col_w = PAD + 310, w - PAD - (PAD + 310) - 10
    sy = y + 40
    signals = [
        (f"{name} on minimap", mini_ans["on_minimap"]["p"]),
        (f"{name} on screen", screen_ans["on_screen"]["p"]),
        (f"standing on {name}", screen_ans["standing_on"]["p"]),
        ("minimap box conf", mini_ans["box_minimap"]["confidence"] or 0),
        ("screen box conf", screen_ans["box_screen"]["confidence"] or 0),
    ]
    for label, p in signals:
        draw.text((x, sy), label, fill=TEXT, font=font(16))
        draw.text((x + col_w, sy), f"{p:.2f}", fill=TEXT, font=font(16), anchor="ra")
        _bar(draw, x, sy + 22, col_w, 10, p, ACCENT if p >= 0.5 else DIM)
        sy += 48
    dx, dy = record.get("screen_box_tiles", [0, 0])
    draw.text((x, sy + 4), f"screen box  {dx:+.0f}, {dy:+.0f} tiles", fill=DIM, font=font(15))
    draw.text(
        (x, sy + 26),
        f"streaks  screen {record.get('screen_streak', 0)}/{config.SCREEN_STREAK}"
        f"  arrived {record.get('arrived_streak', 0)}/{config.ARRIVED_STREAK}",
        fill=DIM,
        font=font(15),
    )

    # ---- Direction choice ----
    y = 576
    _card(draw, y, y + 330, f"WHICH WAY TO {name.upper()}?  bar = this tick, | = smoothed")
    direction = mini_ans["direction"]
    smoothed = record.get("smoothed_direction", {})
    ry = y + 40
    for label in DIRECTION_ORDER:
        p = direction["probs"].get(label, 0.0)
        chosen = label == direction["choice"]
        draw.text((PAD, ry), label, fill=ACCENT if chosen else TEXT, font=font(16, bold=chosen))
        _bar(draw, PAD + 120, ry + 3, 390, 14, p, ACCENT if chosen else DIM, smoothed.get(label))
        draw.text((w - PAD - 4, ry), f"{p:.2f}", fill=TEXT, font=font(16), anchor="ra")
        ry += 28

    # ---- Stats ----
    y = 914
    _card(draw, y, h - 10, "STATS")
    age_ms = max(0, round((now - record["t_shot"]) * 1000))
    draw.text((PAD, y + 34), f"{age_ms:>5} ms old", fill=ACCENT, font=font(30, bold=True))
    lines = [
        f"latency  minimap {jev['minimap']['ms']} ms  |  screen {jev['screen']['ms']} ms",
        f"tick     decide {record.get('decide_ms', 0)} ms  |  act {record.get('act_ms', 0)} ms"
        + ("" if record.get("moved_tiles") is None else f"  |  moved {record['moved_tiles']:.1f}"),
        f"cost     {jev['tokens']:,} tok  ${jev['cost_usd']:.5f}  |  total "
        f"${record.get('total_cost_usd', 0):.4f}",
    ]
    for i, line in enumerate(lines):
        draw.text((PAD, y + 80 + i * 24), line, fill=TEXT, font=font(16))
    return img
