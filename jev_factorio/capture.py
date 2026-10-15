"""Screenshots of the Factorio client area."""

import mss
from PIL import Image, ImageDraw

from . import config
from .window import Rect


class Screen:
    def __init__(self):
        self._sct = mss.mss()

    def grab(self, rect: Rect) -> Image.Image:
        raw = self._sct.grab(rect.as_mss())
        return Image.frombytes("RGB", raw.size, raw.rgb)

    def close(self):
        self._sct.close()


def minimap(frame: Image.Image) -> Image.Image:
    """Crop the minimap (centred on the player), upscale it with crisp pixels and mark the
    player with a red cross."""
    right = frame.width - config.MINIMAP_RIGHT
    box = (
        right - config.MINIMAP_SIZE,
        config.MINIMAP_TOP,
        right,
        config.MINIMAP_TOP + config.MINIMAP_SIZE,
    )
    size = (config.MINIMAP_JEV_SIZE, config.MINIMAP_JEV_SIZE)
    img = frame.crop(box).resize(size, Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(img)
    scale = img.width / 448  # the cross was tuned at 448 px; keep its size relative to the map
    c, arm, width = img.width / 2, 14 * scale, round(3 * scale)
    draw.line((c - arm, c, c + arm, c), fill=(255, 0, 0), width=width)
    draw.line((c, c - arm, c, c + arm), fill=(255, 0, 0), width=width)
    return img


def for_jev(img: Image.Image) -> Image.Image:
    """Downscale so the longest side fits Jev's limit. Box answers are fractions, so the
    scale doesn't matter for mapping back to screen coordinates."""
    longest = max(img.size)
    if longest <= config.JEV_MAX_IMAGE_SIDE:
        return img
    scale = config.JEV_MAX_IMAGE_SIDE / longest
    return img.resize(
        (round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS
    )


def closeup(frame: Image.Image) -> tuple[Image.Image, tuple[float, float, float, float]]:
    """The area around the player (screen centre), upscaled 2x so obstacles are big enough
    for Jev. Also returns the region as (left, top, right, bottom) fractions of the frame, to
    map boxes on the close-up back onto the full frame."""
    w, h = config.CLOSEUP_SIZE
    cx, cy = frame.width // 2, frame.height // 2
    box = (cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2)
    img = frame.crop(box).resize((w * 2, h * 2), Image.Resampling.BICUBIC)
    region = (
        box[0] / frame.width,
        box[1] / frame.height,
        box[2] / frame.width,
        box[3] / frame.height,
    )
    return img, region


def _upscaled(frame: Image.Image, box: tuple[int, int, int, int], factor: int) -> Image.Image:
    crop = frame.crop(box)
    return crop.resize((crop.width * factor, crop.height * factor), Image.Resampling.LANCZOS)


def info_panel(frame: Image.Image) -> Image.Image:
    """The entity info panel under the minimap, upscaled 3x (the API rejects small images)."""
    left, top, bottom = config.INFO_PANEL
    return _upscaled(frame, (frame.width - left, top, frame.width, bottom), 3)


def progress_bar(frame: Image.Image) -> Image.Image:
    """The strip above the quickbar where the hand-mining progress bar appears, upscaled 2x.
    A thin strip is rejected by the API, so it includes some of the world above."""
    return _upscaled(frame, config.PROGRESS_BAR, 2)


def cursor_closeup(frame: Image.Image, x: int, y: int) -> Image.Image:
    """The area the '+1 Coal (N)' text rises through, above the cursor at (x, y), 2x."""
    w, above, below = config.CURSOR_TEXT_AREA
    left = max(0, min(frame.width - w, x - w // 2))
    top = max(0, y - above)
    return _upscaled(frame, (left, top, left + w, min(frame.height, y + below)), 2)


def inventory_panel(frame: Image.Image) -> Image.Image:
    """Where the "Character" inventory panel sits when open, upscaled 2x."""
    return _upscaled(frame, config.INVENTORY_PANEL, 2)


def slot_closeup(frame: Image.Image, x: int, y: int) -> Image.Image:
    """A hovered inventory slot at (x, y): its icon and count, and the tooltip that opens to
    its lower right, upscaled 3x."""
    return _upscaled(frame, (x - 22, y - 22, x + 238, y + 98), 3)


def furnace_window(frame: Image.Image) -> Image.Image:
    """Where a building's window opens, unscaled (920x440)."""
    return _upscaled(frame, config.FURNACE_WINDOW, 1)


def furnace_side(frame: Image.Image) -> Image.Image:
    """The furnace half of its window, upscaled 2x."""
    return _upscaled(frame, config.FURNACE_SIDE, 2)


def furnace_slot(frame: Image.Image, name: str) -> Image.Image:
    """One furnace slot ("input", "output", "fuel"), 64x64 upscaled 5x (4x, 256 px, is
    rejected by the API)."""
    x, y = config.FURNACE_SLOTS[name]
    return _upscaled(frame, (x - 32, y - 32, x + 32, y + 32), 5)
