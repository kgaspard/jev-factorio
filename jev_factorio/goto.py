"""Walk back to a placed building from where the player is, both known from visual odometry
(GameState.player_at, Building.at). No Jev call: this is memory, not perception. It stops
once the building is within a few tiles; the objective after it then finds the building on
screen by Box and checks it by the info panel as usual.

A move that walked (almost) nothing means something is in the way; a few in a row fail.
"""

import math

from PIL import Image

from . import actions, config
from .actions import Action
from .state import ITEM_NAMES, GameState


def heading(vx: float, vy: float) -> str:
    """The 8-way move towards (vx, vy); an axis under 1.5 tiles is left out."""
    v = "up" if vy < -1.5 else "down" if vy > 1.5 else ""
    h = "left" if vx < -1.5 else "right" if vx > 1.5 else ""
    return f"{v}_{h}" if v and h else v or h


class GoToBuildingPolicy:
    MAX_MOVES = 60

    def __init__(self, state: GameState, kind: str) -> None:
        self.state = state
        self.kind = kind
        self.name = ITEM_NAMES.get(kind, kind)
        self.moves = 0
        self.stuck = 0
        self.last_at: tuple[float, float] | None = None
        self.total_cost = 0.0
        self.done = False
        self.success = False

    def decide(self, frame: Image.Image, tick: int) -> tuple[Action, dict]:
        action, source, reason = self._decide()
        b = self.state.building(self.kind)
        info = {
            "objective": f"go_to_{self.kind}",
            "jev": {"tokens": 0, "cost_usd": 0.0},  # no Jev call
            "player_at": [round(v, 2) for v in self.state.player_at],
            "building_at": [round(v, 2) for v in b.at] if b and b.at else None,
            "decision": {"source": source, "reason": reason},
            "total_cost_usd": 0.0,
        }
        return action, info

    def _decide(self) -> tuple[Action, str, str]:
        b = self.state.building(self.kind)
        if b is None or b.at is None:
            self.done = self.success = True
            return actions.wait(0), "unknown", f"{self.name} position unknown; look from here"
        px, py = self.state.player_at
        vx, vy = b.at[0] - px, b.at[1] - py
        dist = math.hypot(vx, vy)
        if self.last_at is not None:
            walked = math.hypot(px - self.last_at[0], py - self.last_at[1])
            self.stuck = self.stuck + 1 if walked < config.GO_TO_STUCK_TILES else 0
        if dist <= config.GO_TO_NEAR_TILES:
            self.done = self.success = True
            return actions.wait(0), "arrived", f"{self.name} {dist:.1f} tiles away, in reach"
        if self.stuck >= 3:
            self.done = True
            return actions.wait(0), "stuck", f"blocked 3 moves in a row, {dist:.0f} tiles to go"
        if self.moves >= self.MAX_MOVES:
            self.done = True
            return actions.wait(0), "give up", f"{self.moves} moves, still {dist:.0f} tiles away"
        direction = heading(vx, vy)
        self.moves += 1
        self.last_at = (px, py)
        return (
            actions.move(direction, config.GO_TO_MOVE_SECONDS),
            "walk",
            f"{self.name} {dist:.0f} tiles away ({vx:+.0f},{vy:+.0f}); walk {direction}",
        )

    def cleanup(self) -> list[Action]:
        return []
