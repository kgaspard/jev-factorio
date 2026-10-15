"""Jev's `next_objective` decision: given the goal and what the state says so far, which
objective comes next. Text only, no image: everything it needs is in the state."""

from dataclasses import dataclass, field

from typesafe_sdk import Choice

from .brain import GAME_CONTEXT
from .state import GameState

RULES = (
    "A stone furnace smelts ore into plates, one plate per ore, and burns coal as fuel. It "
    "smelts one kind of ore at a time: take its plates out before loading a different ore. A "
    "stone furnace is crafted from 5 stone."
)


@dataclass(frozen=True)
class Goal:
    text: str
    mine: dict[str, int]  # mine_* objective -> how many of that ore to have
    craft: dict[str, tuple[str, int]] = field(default_factory=dict)  # objective -> item, count
    check: list[str] = field(default_factory=list)  # items check_inventory looks for


GOALS = {
    "iron_plates": Goal(
        "Goal: have 16 iron plates. So the player needs one stone furnace placed on the "
        "ground, 16 iron ore and a few coal.",
        {"mine_iron": 16, "mine_coal": 5, "mine_stone": 5},
        check=["stone_furnace", "iron_ore", "coal", "stone", "iron_plate"],
    ),
    "gears_copper": Goal(
        "Goal: have 5 iron gear wheels and 10 copper plates. A gear is crafted from 2 iron "
        "plates. So the player needs one stone furnace placed on the ground, 10 iron plates "
        "(16 iron ore is plenty), 10 copper ore and a few coal.",
        {"mine_iron": 16, "mine_copper": 10, "mine_coal": 5, "mine_stone": 5},
        {"craft_gears": ("iron_gear_wheel", 5)},
        [
            "stone_furnace",
            "iron_ore",
            "copper_ore",
            "coal",
            "iron_plate",
            "copper_plate",
            "iron_gear_wheel",
        ],
    ),
    "red_science": Goal(
        "Goal: have 10 automation science packs (red science). Their recipe is locked until "
        "the player crafts a lab: crafting one researches 'Automation science pack'. A lab is "
        "crafted from 10 electronic circuits, 10 iron gear wheels and 4 transport belts; "
        "crafting it by hand makes those parts too, from 36 iron plates and 15 copper plates. "
        "Then each pack is crafted from 1 copper plate and 1 iron gear wheel (2 iron plates): "
        "20 iron plates and 10 copper plates for 10 packs. So the player needs one stone "
        "furnace placed on the ground, 56 iron ore, 25 copper ore and about 10 coal; craft the "
        "lab first, then the packs. A furnace slot holds at most 50 ore.",
        {"mine_iron": 56, "mine_copper": 25, "mine_coal": 10, "mine_stone": 5},
        {
            "craft_gears": ("iron_gear_wheel", 10),
            "craft_lab": ("lab", 1),
            "craft_red_science": ("automation_science_pack", 10),
        },
        [
            "stone_furnace",
            "iron_ore",
            "copper_ore",
            "coal",
            "iron_plate",
            "copper_plate",
            "iron_gear_wheel",
        ],
    ),
}

OBJECTIVES = {
    "check_inventory": "Open the inventory to see what the player has",
    "mine_stone": "Mine stone, to craft a stone furnace from",
    "craft_stone_furnace": "Craft a stone furnace from 5 stone",
    "mine_coal": "Mine coal, the fuel for the furnace",
    "mine_iron": "Mine iron ore, to smelt into iron plates",
    "mine_copper": "Mine copper ore, to smelt into copper plates",
    "place_stone_furnace": "Place a stone furnace from the inventory on the ground",
    "fuel_stone_furnace": "Put coal into the placed furnace",
    "load_iron_ore": "Put iron ore into the placed furnace",
    "load_copper_ore": "Put copper ore into the placed furnace",
    "wait_for_smelting": "Wait while the furnace smelts the ore",
    "collect_plates": "Take the plates out of the furnace",
    "craft_gears": "Craft iron gear wheels from iron plates",
    "craft_lab": "Craft a lab (makes its circuits, gears and belts from plates)",
    "craft_red_science": "Craft automation science packs from copper plates and gears",
    "done": "The goal is reached",
}


def next_objective_request(state: GameState, goal: Goal) -> tuple[list, dict]:
    return [GAME_CONTEXT, goal.text, RULES, state.describe()], {
        "next_objective": Choice(
            instructions="What should the player do next to reach the goal?",
            criteria=OBJECTIVES,
        ),
    }
