"""Turning Box answers into directions. The player is at the centre of both the main view
and the minimap, so the box centre relative to (0.5, 0.5) says where to walk."""

import math

from . import config

# 8 compass directions, indexed by 45-degree sector starting at "right" and going clockwise
# (screen y grows downward).
_SECTORS = ["right", "down_right", "down", "down_left", "left", "up_left", "up", "up_right"]


def turn(direction: str, eighths: int) -> str:
    """Rotate a compass direction clockwise by eighths of a turn (2 = 90 degrees)."""
    return _SECTORS[(_SECTORS.index(direction) + eighths) % 8]


def angle_off(direction: str, dx: float, dy: float) -> float:
    """Degrees between a compass direction and the offset (dx, dy), 0-180."""
    target = _SECTORS.index(direction) * 45
    angle = math.degrees(math.atan2(dy, dx)) % 360
    return abs((angle - target + 180) % 360 - 180)


def box_centre(box) -> tuple[float, float]:
    return (box.left + box.right) / 2, (box.top + box.bottom) / 2


def compass(dx: float, dy: float) -> str:
    """8-way direction of the offset (dx, dy), with y pointing down."""
    angle = math.degrees(math.atan2(dy, dx)) % 360
    return _SECTORS[round(angle / 45) % 8]


def direction_to(x: float, y: float, arrived_radius: float = 0.04) -> str:
    """Direction from the image centre to (x, y), or 'here' if within arrived_radius.
    Only for square images (the minimap); use screen_offset_tiles for the main view."""
    dx, dy = x - 0.5, y - 0.5
    if math.hypot(dx, dy) < arrived_radius:
        return "here"
    return compass(dx, dy)


def screen_offset_tiles(x: float, y: float) -> tuple[float, float]:
    """Offset in tiles from the player (screen centre) to a point given as fractions of the
    main view. The main view is 16:9, so fractions alone would distort the angle."""
    w, h = config.VIEW_TILES
    return (x - 0.5) * w, (y - 0.5) * h
