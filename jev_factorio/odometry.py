"""Visual odometry: how far the player walked between two frames. The camera follows the
player, so the ground shifts by the distance walked; phase correlation finds that shift. No
Jev call. On a recorded walk, each 0.25 s move read 107 px (3.34 tiles) in any direction."""

import numpy as np
from PIL import Image

from . import config

SCALE = 2  # correlate at half resolution: 4x faster, still sub-tile


def ground(frame: Image.Image) -> np.ndarray:
    """The part of the game view used for matching (no HUD), grey, at 1/SCALE size."""
    crop = frame.crop(config.ODOMETRY_AREA).convert("L")
    crop = crop.resize((crop.width // SCALE, crop.height // SCALE))
    return np.asarray(crop, dtype=np.float32)


def walked(before: np.ndarray, after: np.ndarray) -> tuple[float, float]:
    """Tiles the player moved from `before` to `after` (x right, y down)."""
    fa = np.fft.fft2(before - before.mean())
    fb = np.fft.fft2(after - after.mean())
    cross = fa * np.conj(fb)
    r = np.fft.ifft2(cross / (np.abs(cross) + 1e-9)).real
    dy, dx = np.unravel_index(int(np.argmax(r)), r.shape)
    h, w = r.shape
    dx = dx - w if dx > w // 2 else dx
    dy = dy - h if dy > h // 2 else dy
    px = SCALE / config.TILE_PX
    return dx * px, dy * px
