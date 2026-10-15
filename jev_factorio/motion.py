"""How far the player moved between two ticks, from the frames alone. The camera follows the
player, so the shift between two screenshots of the world is the player's movement."""

import numpy as np
from PIL import Image

from . import config

_SCALE = 4  # downscale factor; at 48 px per tile, 1 px of the thumbnail is 1/12 tile
_WORLD = (0, 0, 1600, 952)  # game world only: leaves out the minimap and the hotbar


def world_thumb(frame: Image.Image) -> np.ndarray:
    w, h = _WORLD[2] - _WORLD[0], _WORLD[3] - _WORLD[1]
    small = frame.convert("L").crop(_WORLD).resize((w // _SCALE, h // _SCALE))
    return np.asarray(small, dtype=np.float32)


def moved_tiles(prev: np.ndarray, cur: np.ndarray) -> float:
    """Distance the camera moved, in tiles, by phase correlation. Walking one 250 ms stride
    measured 2.3 tiles, day or night; blocked by a tree, 0.0-0.3."""
    a, b = prev - prev.mean(), cur - cur.mean()
    window = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))  # no edge artefacts
    cross = np.fft.fft2(a * window) * np.conj(np.fft.fft2(b * window))
    peak = np.fft.ifft2(cross / (np.abs(cross) + 1e-9)).real
    y, x = np.unravel_index(np.argmax(peak), peak.shape)
    dy = y - peak.shape[0] if y > peak.shape[0] // 2 else y
    dx = x - peak.shape[1] if x > peak.shape[1] // 2 else x
    return float(np.hypot(dx, dy)) * _SCALE / config.TILE_PX
