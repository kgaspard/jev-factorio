"""The Jev decision panel, drawn as a PIL image from one decisions.jsonl record.
Used by the live view now and by the video renderer later, so both look the same."""

import textwrap
from functools import cache, lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import config
from .planner import OBJECTIVES

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


def _step_label(sequence: dict | None) -> str:
    if not sequence:
        return ""
    return f"  (step {sequence['step'] + 1}/{len(sequence['steps'])})"


def render(record: dict | None, run_dir: Path, now: float) -> Image.Image:
    w, h = config.PANEL_SIZE
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)

    draw.text((PAD, 14), "JEV PLAYS FACTORIO", fill=ACCENT, font=font(38, mono=False))
    if record is None or "jev" not in record:
        draw.text((PAD, 70), "waiting for the first decision...", fill=DIM, font=font(18))
        return img

    jev = record["jev"]
    name = record.get("target_name", "target")
    draw.text(
        (PAD, 62),
        f"{config.JEV_MODEL}  |  tick {record['tick']:03d}  |  {record.get('objective', '')}"
        + _step_label(record.get("sequence")),
        fill=DIM,
        font=font(17),
    )

    # ---- Decision ----
    y = 96
    _card(draw, y, y + 120, "ACTION")
    action = record["action"]["name"].replace("_", " ")
    decision = record.get("decision", {})
    colour = GOOD if decision.get("source") in ("arrived", "done") else TEXT
    draw.text((PAD, y + 32), action.upper(), fill=colour, font=font(34, bold=True))
    source = decision.get("source", "")
    reason = textwrap.wrap(f"[{source}] {decision.get('reason', '')}", 64)
    for i, line in enumerate(reason[:2]):
        draw.text((PAD, y + 74 + i * 20), line, fill=DIM, font=font(15))

    if record.get("objective") == "plan":
        _plan_section(img, draw, record)
    elif record.get("objective") in (
        "place_stone_furnace",
        "fuel_stone_furnace",
        "load_iron_ore",
        "load_copper_ore",
        "go_to_stone_furnace",
        "wait_for_smelting",
        "collect_plates",
    ) or str(record.get("objective", "")).startswith("craft_"):
        _generic_section(img, draw, record, run_dir)
    elif record.get("objective") == "check_inventory":
        _inventory_section(img, draw, record, run_dir)
    elif "minimap" in jev:
        _walk_section(img, draw, record, run_dir, name)
    else:
        _mine_section(img, draw, record, run_dir, name)

    # ---- Stats ----
    y = 914
    _card(draw, y, h - 10, "STATS")
    age_ms = max(0, round((now - record["t_shot"]) * 1000))
    draw.text((PAD, y + 34), f"{age_ms:>5} ms old", fill=ACCENT, font=font(30, bold=True))
    latency = "  |  ".join(
        f"{k} {v['ms']} ms" for k, v in jev.items() if isinstance(v, dict) and "ms" in v
    )
    lines = [
        f"latency  {latency}",
        f"tick     decide {record.get('decide_ms', 0)} ms  |  act {record.get('act_ms', 0)} ms"
        + ("" if record.get("moved_tiles") is None else f"  |  moved {record['moved_tiles']:.1f}"),
        f"cost     {jev.get('tokens', 0):,} tok  ${jev.get('cost_usd', 0.0):.5f}  |  total "
        f"${record.get('total_cost_usd', 0):.4f}",
    ]
    for i, line in enumerate(lines):
        draw.text((PAD, y + 80 + i * 24), line, fill=TEXT, font=font(16))
    return img


def _signal_rows(draw, x: int, y: int, col_w: int, signals: list[tuple[str, float]]) -> int:
    for label, p in signals:
        draw.text((x, y), label, fill=TEXT, font=font(16))
        draw.text((x + col_w, y), f"{p:.2f}", fill=TEXT, font=font(16), anchor="ra")
        _bar(draw, x, y + 22, col_w, 10, p, ACCENT if p >= 0.5 else DIM)
        y += 48
    return y


def _walk_section(img, draw, record: dict, run_dir: Path, name: str):
    w = config.PANEL_SIZE[0]
    jev = record["jev"]
    mini_ans, screen_ans = jev["minimap"]["answers"], jev["screen"]["answers"]

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
    sy = _signal_rows(draw, x, sy, col_w, signals)
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


def _paste_image(img, run_dir: Path, rel: str | None, xy, size, box=None, label="", dot=None):
    path = run_dir / (rel or "")
    if not rel or not path.is_file():
        return
    shot = _load_image(path).resize(size, Image.Resampling.LANCZOS)
    if box:
        _draw_box(shot, box, label)
    if dot:
        cx, cy = dot[0] * shot.width, dot[1] * shot.height
        ImageDraw.Draw(shot).ellipse((cx - 9, cy - 9, cx + 9, cy + 9), outline=BOX, width=3)
    img.paste(shot, xy)


def _mine_section(img, draw, record: dict, run_dir: Path, name: str):
    w = config.PANEL_SIZE[0]
    jev, shots = record["jev"], record.get("images", {})
    state = record.get("state", "")

    # ---- What Jev is looking at this tick ----
    y = 228
    _card(draw, y, y + 340, f"WHAT JEV SEES  ({state})")
    if "aim" in jev:
        dot = None
        region, aim = record.get("closeup_region"), record.get("aim")
        if region and aim and record.get("action", {}).get("kind") == "hover":
            rl, rt, rr, rb = region
            dot = ((aim[0] - rl) / (rr - rl), (aim[1] - rt) / (rb - rt))
        _paste_image(img, run_dir, shots.get("closeup"), (PAD, y + 38), (w - 2 * PAD, 337 - 45),
                     dot=dot)  # fmt: skip
    else:
        if "cursor" in shots:
            _paste_image(img, run_dir, shots["cursor"], (PAD, y + 38), (400, 258))
        if "text" in shots:
            _paste_image(img, run_dir, shots["text"], (PAD, y + 38), (400, 258))
            _paste_image(img, run_dir, shots.get("bar"), (PAD, y + 300), (400, 34))
        _paste_image(img, run_dir, shots.get("panel"), (w - PAD - 170, y + 38), (170, 212))

    # ---- Signals and the count ----
    y = 576
    _card(draw, y, y + 330, f"MINING {name.upper()}")
    signals = []
    if "aim" in jev:
        probs = jev["aim"]["answers"]["side"]["probs"]
        top = sorted(probs.items(), key=lambda kv: -kv[1])[:5]
        signals += [(f"{name} {side.replace('_', ' ')}", p) for side, p in top]
    if "panel" in jev:
        a = jev["panel"]["answers"]
        signals += [("info panel shown", a["panel_shown"]["p"]),
                    (f"panel says {name}", a["says_target"]["p"])]  # fmt: skip
    if "corners" in jev:
        signals.append(
            (
                "corners yellow (reach)",
                jev["corners"]["answers"]["corners"]["probs"].get("yellow", 0.0),
            )
        )
    if "bar" in jev:
        signals.append(("mining bar", jev["bar"]["answers"]["mining"]["p"]))
    if "text" in jev:
        a = jev["text"]["answers"]
        signals += [("'+1 ... (N)' text", a["text_shown"]["p"]),
                    ("count conf", a["count"]["confidence"] or 0)]  # fmt: skip
    col_w = 330
    _signal_rows(draw, PAD, y + 40, col_w, signals[:5])

    x = PAD + col_w + 30
    count = record.get("count")
    goal = record.get("goal", 0)
    draw.text((x, y + 40), "HAVE", fill=DIM, font=font(16, bold=True))
    draw.text((x, y + 60), f"{'?' if count is None else count}", fill=ACCENT,
              font=font(64, bold=True))  # fmt: skip
    draw.text((x, y + 136), f"of {goal}", fill=TEXT, font=font(22))
    _bar(draw, x, y + 172, w - PAD - 10 - x, 14, (count or 0) / goal if goal else 0, GOOD)
    if "text" in jev:
        c = jev["text"]["answers"]["count"]
        top = sorted(c["probs"].items(), key=lambda kv: -kv[1])[:3]
        draw.text((x, y + 200), "Jev reads N:", fill=DIM, font=font(15))
        for i, (label, p) in enumerate(top):
            draw.text((x, y + 222 + i * 22), f"{label:>5}  {p:.2f}", fill=TEXT, font=font(16))


def _inventory_section(img, draw, record: dict, run_dir: Path):
    w = config.PANEL_SIZE[0]
    jev, shots = record["jev"], record.get("images", {})
    wanted = record.get("looking_for") or ""
    wanted_name = wanted.replace("_", " ")

    # ---- What Jev is looking at this tick ----
    y = 228
    _card(draw, y, y + 340, f"WHAT JEV SEES  ({record.get('phase', '')})")
    if "slot" in shots:
        _paste_image(img, run_dir, shots["slot"], (PAD, y + 38), (w - 2 * PAD, 277))
    elif "inventory" in shots:
        box = jev["locate"]["answers"]["box"] if "locate" in jev else None
        label = f"{wanted_name} {box['confidence'] or 0:.2f}" if box else ""
        _paste_image(img, run_dir, shots["inventory"], (PAD + 140, y + 38), (300, 293),
                     box["box"] if box else None, label)  # fmt: skip
    else:
        draw.text((PAD, y + 50), "pressing E, nothing to read", fill=DIM, font=font(16))

    # ---- Signals and what has been found so far ----
    y = 576
    _card(draw, y, y + 330, f"INVENTORY  looking for: {wanted_name}")
    signals: list[tuple[str, float]] = []
    if "open" in jev:
        signals.append(("inventory open", jev["open"]["answers"]["open"]["p"]))
    if "locate" in jev:
        a = jev["locate"]["answers"]
        signals += [("is it there? (Noul)", a["there"]["p"]),
                    ("slot box conf", a["box"]["confidence"] or 0)]  # fmt: skip
    if "slot" in jev:
        a = jev["slot"]["answers"]
        signals += [
            (f"tooltip says {wanted_name}", a["item"]["probs"].get(wanted, 0.0)),
            (f"tooltip: {a['item']['choice']}", a["item"]["confidence"] or 0),
            (f"count: {a['count']['choice']}", a["count"]["confidence"] or 0),
        ]
    _signal_rows(draw, PAD, y + 40, 330, signals)
    x = PAD + 360
    draw.text((x, y + 40), "FOUND", fill=DIM, font=font(16, bold=True))
    for i, (item, n) in enumerate(record.get("items", {}).items()):
        text = f"{n:>3}  {item.replace('_', ' ')}" if n else f" no  {item.replace('_', ' ')}"
        draw.text((x, y + 66 + i * 26), text, fill=TEXT if n else DIM, font=font(16))


def _plan_section(img, draw, record: dict):
    w = config.PANEL_SIZE[0]
    choice = record["jev"]["plan"]["answers"]["next_objective"]

    # ---- The state Jev reads (text only, no image) ----
    y = 228
    _card(draw, y, y + 340, "WHAT JEV KNOWS  (text, no image)")
    lines = []
    for sentence in record.get("state_text", "").split(". "):
        lines += textwrap.wrap(sentence.rstrip(".") + ".", 56)
    for i, line in enumerate(lines[:12]):
        draw.text((PAD, y + 40 + i * 24), line, fill=TEXT, font=font(16))

    # ---- The next_objective choice ----
    y = 576
    _card(draw, y, y + 330, "NEXT OBJECTIVE?")
    ry = y + 38
    for label in OBJECTIVES:
        p = choice["probs"].get(label, 0.0)
        chosen = label == choice["choice"]
        draw.text((PAD, ry), label, fill=ACCENT if chosen else TEXT, font=font(15, bold=chosen))
        _bar(draw, PAD + 175, ry + 3, 340, 12, p, ACCENT if chosen else DIM)
        draw.text((w - PAD - 4, ry), f"{p:.2f}", fill=TEXT, font=font(15), anchor="ra")
        ry += 26


def _generic_section(img, draw, record: dict, run_dir: Path):
    """Any objective: the image Jev looked at this tick, and every answer as a bar."""
    w = config.PANEL_SIZE[0]
    jev, shots = record["jev"], record.get("images", {})

    y = 228
    _card(draw, y, y + 340, f"WHAT JEV SEES  ({record.get('phase', '')})")
    for name, size, xy in [
        ("slot", (w - 2 * PAD, 277), (PAD, y + 38)),
        ("cursor", (450, 290), (PAD + 75, y + 38)),
        ("panel", (230, 290), (PAD + 185, y + 38)),
        ("inventory", (300, 293), (PAD + 140, y + 38)),
        ("view", (515, 290), (PAD + 42, y + 38)),
        ("window", (w - 2 * PAD, 287), (PAD, y + 38)),
        ("side", (330, 284), (PAD + 135, y + 38)),
        ("output", (285, 285), (PAD + 157, y + 38)),
        ("crafting", (330, 284), (PAD + 135, y + 38)),  # verify_moved: the slots go in the bars
    ]:
        if name in shots:
            box = None
            if name == "inventory" and "locate" in jev:
                box = jev["locate"]["answers"]["box"]["box"]
            if name == "crafting" and "locate" in jev:
                box = jev["locate"]["answers"]["box"]["box"]
            if name == "view" and "find" in jev:
                box = jev["find"]["answers"]["box"]["box"]
            _paste_image(img, run_dir, shots[name], xy, size, box)
            break
    else:
        draw.text((PAD, y + 50), "acting, nothing to read", fill=DIM, font=font(16))

    y = 576
    _card(draw, y, y + 330, record.get("objective", "").upper().replace("_", " "))
    signals: list[tuple[str, float]] = []
    for job, result in jev.items():
        if not isinstance(result, dict) or "answers" not in result:
            continue
        for key, a in result["answers"].items():
            if a["type"] == "noul":
                signals.append((f"{job}: {key}", a["p"]))
            elif a["type"] == "choice":
                signals.append((f"{job}: {a['choice']}", a["confidence"] or 0))
            else:
                signals.append((f"{job}: box conf", a["confidence"] or 0))
    _signal_rows(draw, PAD, y + 40, w - 2 * PAD - 10, signals[:6])
