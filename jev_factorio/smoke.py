"""Checkpoint 0: can Jev find iron ore in the main view and on the minimap?

Grab the Factorio window:   uv run python -m jev_factorio.smoke
  (click into Factorio during the countdown so nothing covers it)
Or a saved screenshot:      uv run python -m jev_factorio.smoke --image path/to/shot.png
Prints answers and latency, and saves the screenshot and minimap with boxes drawn on.
"""

import argparse
import time
from datetime import datetime

from PIL import Image, ImageDraw
from typesafe_sdk import Box, Choice
from typesafe_sdk import Image as JevImage
from typesafe_sdk import Noul

from . import config
from .capture import Screen, for_jev, minimap
from .geometry import box_centre, direction_to
from .jev import make_client
from .window import client_rect, factorio_is_active, find_factorio, place_client

DIRECTIONS = ["up", "down", "left", "right", "up_left", "up_right", "down_left", "down_right"]

# Two separate requests: one image per request did better than both images in one.
SCREEN_STATE = [
    "A screenshot of the video game Factorio (version 2.0, top-down view). The player's "
    "character is at the centre. Iron ore looks like grey-blue rocks on the ground, copper "
    "ore is orange-brown, coal is black and stone is beige.",
    "<screenshot>",
]
SCREEN_QUESTIONS = {
    "iron_on_screen": Noul(instructions="Is iron ore visible in the screenshot?"),
    "iron_box_screen": Box(instructions="The iron ore nearest the player in the screenshot"),
}

MINIMAP_STATE = [
    "A Factorio minimap, centred on the player, who is marked with a red cross. Up is north. "
    "Resource patches show as checkered areas: iron ore is grey-blue, copper ore is orange, "
    "coal is black, stone is light beige-grey. Water is solid dark blue.",
    "<minimap>",
]
MINIMAP_QUESTIONS = {
    "iron_on_minimap": Noul(instructions="Is an iron ore patch visible on the map?"),
    "iron_box_minimap": Box(
        instructions="The grey-blue checkered iron ore patch nearest the red cross (the player)"
    ),
    "direction": Choice(
        instructions="Which direction from the red cross (the player) is the nearest "
        "iron ore patch?",
        criteria={
            **{d: None for d in DIRECTIONS},
            "here": "Under the red cross",
            "not_visible": "No iron ore on the map",
        },
    ),
}


def grab_factorio(countdown: float) -> Image.Image:
    hwnd = find_factorio()
    if hwnd is None:
        raise SystemExit("Factorio window not found. Pass --image instead.")
    place_client(hwnd, *config.GAME_CLIENT_SIZE)
    print(f"Click into Factorio. Capturing in {countdown:.0f} s...")
    time.sleep(countdown)
    if not factorio_is_active():
        raise SystemExit("Factorio wasn't focused, so another window may cover it. Try again.")
    screen = Screen()
    try:
        return screen.grab(client_rect(hwnd))
    finally:
        screen.close()


def draw_box(img: Image.Image, b, label: str):
    draw = ImageDraw.Draw(img)
    xy = (b.left * img.width, b.top * img.height, b.right * img.width, b.bottom * img.height)
    draw.rectangle(xy, outline=(255, 210, 0), width=3)
    draw.text((xy[0] + 4, xy[1] + 4), label, fill=(255, 210, 0))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", help="screenshot to test; default: grab the Factorio window")
    parser.add_argument("--repeat", type=int, default=3, help="calls to make, for latency stats")
    parser.add_argument("--countdown", type=float, default=2)
    args = parser.parse_args()

    shot = Image.open(args.image).convert("RGB") if args.image else grab_factorio(args.countdown)
    clean = shot.copy()  # the saved annotated copy must never be fed back to Jev
    mini = minimap(shot)
    sent = for_jev(shot)
    print(
        f"Screenshot {shot.width}x{shot.height}, sent to Jev as {sent.width}x{sent.height}"
        f" + minimap {mini.width}x{mini.height}"
    )

    latencies = []
    with make_client() as client:
        for _ in range(args.repeat):
            t0 = time.perf_counter()
            screen_resp = client.system_one(
                state=SCREEN_STATE,
                questions=SCREEN_QUESTIONS,
                assets={"<screenshot>": JevImage.from_pil(sent)},
            )
            t1 = time.perf_counter()
            resp = client.system_one(
                state=MINIMAP_STATE,
                questions=MINIMAP_QUESTIONS,
                assets={"<minimap>": JevImage.from_pil(mini)},
            )
            latencies.append(((t1 - t0) * 1000, (time.perf_counter() - t1) * 1000))
    answers = {**screen_resp.answers, **resp.answers}

    tokens = (screen_resp.usage.input_tokens or 0) + (resp.usage.input_tokens or 0)
    print(f"\nmodel={resp.model}")
    print("latency ms (screen, minimap): " + ", ".join(f"({a:.0f}, {b:.0f})" for a, b in latencies))
    print(f"input tokens: {tokens}  cost: ${tokens * config.JEV_PRICE_PER_INPUT_TOKEN:.6f}\n")

    nouls = {k: a for k, a in answers.items() if a.type == "noul"}
    boxes = {k: a for k, a in answers.items() if a.type == "box"}
    for name, ans in nouls.items():
        print(f"{name}: {ans.noul:.2f}")
    for name, ans in boxes.items():
        b = ans.box
        print(
            f"{name}: top={b.top:.2f} bottom={b.bottom:.2f} left={b.left:.2f} right={b.right:.2f}"
            f"  confidence={ans.confidence}  -> walk {direction_to(*box_centre(b))}"
        )
    direction = resp.choices["direction"]
    print(f"direction (Jev choice): {direction.choice}  confidence={direction.confidence:.2f}")
    for label, p in sorted(direction.probabilities.items(), key=lambda kv: -kv[1]):
        print(f"  {label:<12} {'#' * round(p * 40)} {p:.2f}")

    draw_box(shot, boxes["iron_box_screen"].box, f"iron {nouls['iron_on_screen'].noul:.2f}")
    draw_box(mini, boxes["iron_box_minimap"].box, f"iron {nouls['iron_on_minimap'].noul:.2f}")
    out_dir = config.RUNS_DIR / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    clean.save(out_dir / f"{stamp}.png")
    shot.save(out_dir / f"{stamp}-annotated.png")
    mini.save(out_dir / f"{stamp}-minimap-annotated.png")
    print(f"\nSaved {out_dir / stamp}.png (clean), -annotated.png and -minimap-annotated.png")


if __name__ == "__main__":
    main()
