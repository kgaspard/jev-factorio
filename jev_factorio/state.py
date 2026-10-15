"""What the player knows about the game so far. Jev fills it in (e.g. by checking the
inventory) and reads it back as text when choosing the next objective."""

import math
import time
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from . import config, odometry
from .actions import Action, is_move

ITEM_NAMES = {
    "iron_ore": "iron ore",
    "coal": "coal",
    "stone": "stone",
    "copper_ore": "copper ore",
    "stone_furnace": "stone furnace",
    "iron_plate": "iron plate",
    "copper_plate": "copper plate",
    "iron_gear_wheel": "iron gear wheel",
    "automation_science_pack": "automation science pack",
    "wood": "wood",
    "burner_mining_drill": "burner mining drill",
    "uranium_ore": "uranium ore",
}
# What the icons look like. Helps Jev box the right slot (O36); the tooltip decides.
ICONS = {
    "iron_ore": "a pile of light blue-grey rocks",
    "coal": "a pile of black lumps",
    "stone": "a pile of beige-brown stones",
    "copper_ore": "a pile of orange-brown rocks",
    "stone_furnace": "a grey-yellow stone dome with a glowing fire opening",
    "iron_plate": "flat grey-blue metal plates",
    "copper_plate": "flat orange-brown metal plates",
    "iron_gear_wheel": "a grey gear (cog wheel)",
    "automation_science_pack": "a small red flask",
    "wood": "brown logs",
    "burner_mining_drill": "a grey drill machine on legs",
    "uranium_ore": "a pile of glowing green rocks",
}


PLATES = {"iron_ore": "iron_plate", "copper_ore": "copper_plate"}  # what a furnace makes


UNCOUNTABLE = ("ore", "coal", "stone", "wood")


def _plural(n: int, item: str) -> str:
    name = ITEM_NAMES.get(item, item)
    return f"{n} {name}" if n == 1 or name.endswith(UNCOUNTABLE) else f"{n} {name}s"


FUELS = ("coal", "wood")


@dataclass
class Building:
    """Something the player placed: where it is and what is in it, as far as the player knows.
    For a stone furnace, `contents` holds the fuel put in, the ore still to smelt and the plates
    waiting in the output (one kind of ore at a time: the input slot holds one kind, and plates
    of another kind in the output block it)."""

    kind: str  # its item name, e.g. "stone_furnace"
    at: tuple[float, float] | None = None  # world tiles, same frame as GameState.player_at
    contents: dict[str, int] = field(default_factory=dict)  # item -> count, as last known
    taken: dict[str, int] = field(default_factory=dict)  # item -> count taken out so far

    def put(self, item: str, n: int) -> None:
        self.contents[item] = self.contents.get(item, 0) + n

    def took(self, item: str, n: int) -> None:
        self.contents.pop(item, None)
        self.taken[item] = self.taken.get(item, 0) + n

    def holds(self, kinds) -> str | None:
        """The first item of `kinds` in it, e.g. which ore a furnace is smelting."""
        return next((k for k in self.contents if k in kinds), None)

    def describe(self, player_at: tuple[float, float]) -> str:
        parts = []
        for item, n in self.contents.items():
            if not n:
                continue
            role = (
                "as fuel"
                if item in FUELS
                else "to smelt"
                if item in PLATES
                else "ready to take out"
                if item in PLATES.values()
                else "inside"
            )
            parts.append(f"{_plural(n, item)} {role}")
        holding = " and ".join(parts) if parts else "nothing"
        where = "on the ground"
        if self.at is not None:
            d = math.hypot(self.at[0] - player_at[0], self.at[1] - player_at[1])
            where = "next to the player" if d < 8 else f"about {d:.0f} tiles from the player"
        name = ITEM_NAMES.get(self.kind, self.kind)
        text = f"A {name} is already placed {where}, holding {holding}."
        taken = [_plural(n, k) for k, n in self.taken.items() if n]
        if taken:
            text += f" {' and '.join(taken)} have been taken out of it."
        return text


@dataclass
class GameState:
    inventory: dict[str, int] | None = None  # None: never checked
    inventory_checked_at: float | None = None
    completed: list[str] = field(default_factory=list)  # objectives done, in order
    buildings: list[Building] = field(default_factory=list)  # placed, in order
    # Where the player is, in tiles from where the run started (x right, y down), from visual
    # odometry: the ground's shift between frames after each move.
    player_at: tuple[float, float] = (0.0, 0.0)
    _ground: Any = field(default=None, repr=False, compare=False)

    def observe(self, frame: Image.Image, last_action: Action | None) -> tuple[float, float]:
        """Update player_at from this frame. Only after a move: nothing else walks, and a
        window opening between frames could fake a shift."""
        ground = odometry.ground(frame)
        step = (0.0, 0.0)
        if self._ground is not None and last_action is not None and is_move(last_action):
            step = odometry.walked(self._ground, ground)
            self.player_at = (self.player_at[0] + step[0], self.player_at[1] + step[1])
        self._ground = ground
        return step

    def building(self, kind: str) -> Building | None:
        """The first placed building of this kind (there is only one of each so far)."""
        return next((b for b in self.buildings if b.kind == kind), None)

    def add(self, building: Building) -> Building:
        self.buildings.append(building)
        return building

    def seen_at(self, px: tuple[float, float], frame: Image.Image) -> tuple[float, float]:
        """World tiles of a point on screen (the player is at the centre of the view)."""
        x, y = self.player_at
        return (
            x + (px[0] - frame.width / 2) / config.TILE_PX,
            y + (px[1] - frame.height / 2) / config.TILE_PX,
        )

    def set_inventory(self, items: dict[str, int]) -> None:
        self.inventory = dict(items)
        self.inventory_checked_at = time.time()

    def describe_inventory(self) -> str:
        if self.inventory is None:
            return "Inventory: unknown, it has not been checked yet."
        held = {k: n for k, n in self.inventory.items() if n > 0}
        absent = [ITEM_NAMES.get(k, k) for k, n in self.inventory.items() if n == 0]
        # A placed building isn't in the inventory; "no stone furnace" read as "make one".
        placed = {ITEM_NAMES.get(b.kind, b.kind) for b in self.buildings}
        absent = [a for a in absent if a not in placed]
        text = "Inventory (checked): "
        text += ", ".join(_plural(n, k) for k, n in held.items()) or "nothing"
        if absent:
            text += "; no " + ", no ".join(absent)
        return text + "."

    def describe_world(self) -> str:
        if not self.buildings:
            return "No furnace has been placed yet."
        return " ".join(b.describe(self.player_at) for b in self.buildings)

    def describe(self) -> str:
        done = ", ".join(self.completed) if self.completed else "none yet"
        return (
            f"Objectives completed so far: {done}. {self.describe_world()} "
            f"{self.describe_inventory()}"
        )
