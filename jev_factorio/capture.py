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
    c, arm = img.width / 2, 14
    draw.line((c - arm, c, c + arm, c), fill=(255, 0, 0), width=3)
    draw.line((c, c - arm, c, c + arm), fill=(255, 0, 0), width=3)
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
