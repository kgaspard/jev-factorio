"""What the player knows about the game so far. Jev fills it in (e.g. by checking the
inventory) and reads it back as text when choosing the next objective."""

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
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
    "copper_cable": "copper cable",
    "electronic_circuit": "electronic circuit",
    "transport_belt": "transport belt",
    "lab": "lab",
    "wood": "wood",
    "burner_mining_drill": "burner mining drill",
    "uranium_ore": "uranium ore",
}
# What the icons look like. Helps Jev box the right slot; the tooltip decides.
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
    "copper_cable": "a coil of copper wire",
    "electronic_circuit": "a green circuit board",
    "transport_belt": "a short yellow conveyor belt",
    "lab": "a machine with a glowing blue-white glass dome",
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
    of another kind in the output block it). A furnace at a drill's output gets its ore from
    the drill, so its plates are estimated from the drill's run time instead."""

    kind: str  # its item name, e.g. "stone_furnace"
    at: tuple[float, float] | None = None  # world tiles, same frame as GameState.player_at
    contents: dict[str, int] = field(default_factory=dict)  # item -> count, as last known
    taken: dict[str, int] = field(default_factory=dict)  # item -> count taken out so far
    # The ore a burner mining drill mines; also set on the stone furnace at its output.
    site: str | None = None
    started_at: float | None = None  # when it got its fuel (a drill, or a drill's furnace)

    def mined(self, now: float) -> int:
        """A burner mining drill: about how much ore it has mined, its fuel permitting."""
        if self.started_at is None:
            return 0
        ran = (now - self.started_at) * config.BURNER_MINING_DRILL_ORE_PER_SECOND
        return int(min(ran, self.fuel_for()))

    def fuel_for(self) -> float:
        """A burner mining drill: the ore all the coal put in so far lasts for."""
        return self.contents.get("coal", 0) * config.BURNER_MINING_DRILL_ORE_PER_COAL

    def put(self, item: str, n: int) -> None:
        self.contents[item] = self.contents.get(item, 0) + n

    def took(self, item: str, n: int) -> None:
        self.contents.pop(item, None)
        self.taken[item] = self.taken.get(item, 0) + n

    def holds(self, kinds) -> str | None:
        """The first item of `kinds` in it, e.g. which ore a furnace is smelting."""
        return next((k for k in self.contents if k in kinds), None)

    def where(self, player_at: tuple[float, float]) -> str:
        if self.at is None:
            return "on the ground"
        d = math.hypot(self.at[0] - player_at[0], self.at[1] - player_at[1])
        return "next to the player" if d < 5 else f"about {d:.0f} tiles from the player"

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
        name = ITEM_NAMES.get(self.kind, self.kind)
        text = f"A {name} is already placed {self.where(player_at)}, holding {holding}."
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

    def building(self, kind: str, site: str | None = None) -> Building | None:
        """The first placed building of this kind (at this drill site, if given)."""
        return next(
            (b for b in self.buildings if b.kind == kind and (site is None or b.site == site)),
            None,
        )

    def plates_ready(self, furnace: Building, now: float) -> int:
        """A furnace at a drill's output: about how many plates wait in its output. It smelts
        what the drill brought (the drill is the slower one), but only once it has fuel: ore
        brought before that waits in its input."""
        drill = self.building("burner_mining_drill", furnace.site)
        if drill is None or furnace.site is None or furnace.started_at is None:
            return 0
        smelted = (now - furnace.started_at) * config.STONE_FURNACE_PLATES_PER_SECOND
        made = int(min(drill.mined(now) - 1, smelted)) + furnace.contents.get(furnace.site, 0)
        return max(0, min(made - furnace.taken.get(PLATES[furnace.site], 0), 100))

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

    def save(self, path: Path) -> None:
        """What the player knows, for a later run to carry on from (`--resume`)."""
        data = {
            "inventory": self.inventory,
            "inventory_checked_at": self.inventory_checked_at,
            "completed": self.completed,
            "buildings": [asdict(b) for b in self.buildings],
            "player_at": self.player_at,
        }
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: Path) -> "GameState":
        """The state a run saved. Valid while nobody moved the player in between: positions
        are tiles from where that run's first run started."""
        d = json.loads(path.read_text())
        buildings = [
            Building(**{**b, "at": tuple(b["at"]) if b["at"] else None}) for b in d["buildings"]
        ]
        return cls(
            d["inventory"],
            d["inventory_checked_at"],
            d["completed"],
            buildings,
            tuple(d["player_at"]),
        )

    def set_inventory(self, items: dict[str, int]) -> None:
        self.inventory = dict(items)
        self.inventory_checked_at = time.time()

    def describe_inventory(self) -> str:
        if self.inventory is None:
            return "Inventory: unknown, it has not been checked yet."
        held = {k: n for k, n in self.inventory.items() if n > 0}
        absent = [ITEM_NAMES.get(k, k) for k, n in self.inventory.items() if n == 0]
        text = "Inventory (checked): "
        text += ", ".join(_plural(n, k) for k, n in held.items()) or "nothing"
        if absent:
            text += "; no " + ", no ".join(absent)
        return text + "."

    def describe_world(self) -> str:
        if not self.buildings:
            return "No building has been placed yet."
        now = time.time()
        return " ".join(self._describe_building(b, now) for b in self.buildings)

    def _describe_building(self, b: Building, now: float) -> str:
        if b.site is None:
            return b.describe(self.player_at)
        ore = ITEM_NAMES[b.site]
        where = b.where(self.player_at)
        if b.kind == "burner_mining_drill":
            if b.started_at is None:
                return f"A burner mining drill is placed on {ore} {where}, without fuel."
            mined, coal = b.mined(now), b.contents.get("coal", 0)
            text = (
                f"A burner mining drill is placed on {ore} {where}. It has been given {coal} "
                f"coal in all (enough for about {b.fuel_for():.0f} ore) and has mined about "
                f"{mined} ore into the stone furnace at its output"
            )
            if mined >= b.fuel_for() - 1:
                return text + ". Its fuel is used up: it has stopped until it gets more coal."
            return text + ", about 15 a minute."
        plates = PLATES[b.site]
        text = f"A stone furnace is placed at the output of the {ore} drill, {where}"
        coal = b.contents.get("coal", 0)
        text += (
            f", given {coal} coal as fuel."
            if coal
            else ", without fuel: it smelts nothing, the ore waits in its input."
        )
        text += f" About {_plural(self.plates_ready(b, now), plates)} have piled up in its output."
        taken = b.taken.get(plates, 0)
        if taken:
            text += f" {_plural(taken, plates)} have been taken out of it."
        return text

    def describe(self) -> str:
        runs: list[list] = []  # repeats folded: "collect_iron_plates (x27)"
        for o in self.completed:
            if runs and runs[-1][0] == o:
                runs[-1][1] += 1
            else:
                runs.append([o, 1])
        done = ", ".join(o if n == 1 else f"{o} (x{n})" for o, n in runs) or "none yet"
        return (
            f"Objectives completed so far: {done}. {self.describe_world()} "
            f"{self.describe_inventory()}"
        )
