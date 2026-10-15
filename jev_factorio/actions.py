"""Discrete game actions and the executor that turns them into key/mouse input."""

import time
from dataclasses import asdict, dataclass

import pydirectinput

from .window import Rect, factorio_is_active

pydirectinput.PAUSE = 0  # default adds a 0.1 s delay after every call, which skews timing

MOVE_KEYS = {
    "up": ["w"],
    "down": ["s"],
    "left": ["a"],
    "right": ["d"],
    "up_left": ["w", "a"],
    "up_right": ["w", "d"],
    "down_left": ["s", "a"],
    "down_right": ["s", "d"],
}
ALL_KEYS = sorted({k for keys in MOVE_KEYS.values() for k in keys} | {"e", "esc", "shift", "ctrl"})
MOUSE_BUTTONS = ("left", "right")


@dataclass
class Action:
    """kind: 'keys' (hold `keys` together for `duration` s; 0 = tap),
    'click' (press `button` at `target` for `duration` s; 0 = click), or 'wait'.
    `target` is (x, y) as fractions of the game client area."""

    name: str
    kind: str
    keys: tuple[str, ...] = ()
    button: str = "left"
    target: tuple[float, float] | None = None
    duration: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def move(direction: str, duration: float) -> Action:
    return Action(f"move_{direction}", "keys", tuple(MOVE_KEYS[direction]), duration=duration)


def tap(name: str, key: str) -> Action:
    return Action(name, "keys", (key,))


def wait(duration: float) -> Action:
    return Action("wait", "wait", duration=duration)


def execute(action: Action, game: Rect) -> bool:
    """Run the action. Returns False (and does nothing) if Factorio isn't focused."""
    if action.kind == "wait":
        time.sleep(action.duration)
        return True
    if not factorio_is_active():
        return False

    if action.kind == "keys":
        try:
            for k in action.keys:
                pydirectinput.keyDown(k)
            time.sleep(action.duration or 0.05)
        finally:
            for k in reversed(action.keys):
                pydirectinput.keyUp(k)
    elif action.kind == "click":
        if action.target is None:
            raise ValueError(f"click action {action.name!r} has no target")
        fx, fy = action.target
        pydirectinput.moveTo(game.left + round(fx * game.width), game.top + round(fy * game.height))
        try:
            pydirectinput.mouseDown(button=action.button)
            time.sleep(action.duration or 0.05)
        finally:
            pydirectinput.mouseUp(button=action.button)
    else:
        raise ValueError(f"unknown action kind {action.kind!r}")
    return True


def release_all():
    """Never leave a key or button stuck down."""
    for k in ALL_KEYS:
        pydirectinput.keyUp(k)
    for b in MOUSE_BUTTONS:
        pydirectinput.mouseUp(button=b)
