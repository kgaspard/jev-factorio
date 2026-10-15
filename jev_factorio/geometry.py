"""Turning Box answers into directions. The player is at the centre of both the main view
and the minimap, so the box centre relative to (0.5, 0.5) says where to walk."""

import math

# 8 compass directions, indexed by 45-degree sector starting at "right" and going clockwise
# (screen y grows downward).
_SECTORS = ["right", "down_right", "down", "down_left", "left", "up_left", "up", "up_right"]


def box_centre(box) -> tuple[float, float]:
    return (box.left + box.right) / 2, (box.top + box.bottom) / 2


def direction_to(x: float, y: float, arrived_radius: float = 0.04) -> str:
    """Direction from the image centre to (x, y), or 'here' if within arrived_radius."""
    dx, dy = x - 0.5, y - 0.5
    if math.hypot(dx, dy) < arrived_radius:
        return "here"
    angle = math.degrees(math.atan2(dy, dx)) % 360
    return _SECTORS[round(angle / 45) % 8]
