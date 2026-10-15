"""What the player knows about the game so far. Jev fills it in (e.g. by checking the
inventory) and reads it back as text when choosing the next objective."""

import time
from dataclasses import dataclass, field

ITEM_NAMES = {
    "iron_ore": "iron ore",
    "coal": "coal",
    "stone": "stone",
    "copper_ore": "copper ore",
    "stone_furnace": "stone furnace",
    "iron_plate": "iron plate",
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
    "wood": "brown logs",
    "burner_mining_drill": "a grey drill machine on legs",
    "uranium_ore": "a pile of glowing green rocks",
}


@dataclass
class Furnace:
    """A placed stone furnace and what was put into it or taken out."""

    fuel: int = 0  # coal put in
    ore: int = 0  # iron ore put in and not smelted yet
    plates_ready: int = 0  # smelted, waiting in the output slot
    plates_taken: int = 0


@dataclass
class GameState:
    inventory: dict[str, int] | None = None  # None: never checked
    inventory_checked_at: float | None = None
    completed: list[str] = field(default_factory=list)  # objectives done, in order
    furnace: Furnace | None = None  # None: no furnace placed yet

    def set_inventory(self, items: dict[str, int]) -> None:
        self.inventory = dict(items)
        self.inventory_checked_at = time.time()

    def describe_inventory(self) -> str:
        if self.inventory is None:
            return "Inventory: unknown, it has not been checked yet."
        held = {k: n for k, n in self.inventory.items() if n > 0}
        absent = [ITEM_NAMES.get(k, k) for k, n in self.inventory.items() if n == 0]
        text = "Inventory (checked): "
        text += ", ".join(f"{n} {ITEM_NAMES.get(k, k)}" for k, n in held.items()) or "nothing"
        if absent:
            text += "; no " + ", no ".join(absent)
        return text + "."

    def describe_world(self) -> str:
        f = self.furnace
        if f is None:
            return "No furnace has been placed yet."
        parts = []
        if f.fuel:
            parts.append(f"{f.fuel} coal as fuel")
        if f.ore:
            parts.append(f"{f.ore} iron ore to smelt")
        if f.plates_ready:
            parts.append(f"{f.plates_ready} iron plates ready to take out")
        holding = " and ".join(parts) if parts else "nothing"
        text = f"A stone furnace is placed on the ground next to the player, holding {holding}."
        if f.plates_taken:
            text += f" {f.plates_taken} iron plates have been taken out of it."
        return text

    def describe(self) -> str:
        done = ", ".join(self.completed) if self.completed else "none yet"
        return (
            f"Objectives completed so far: {done}. {self.describe_world()} "
            f"{self.describe_inventory()}"
        )
