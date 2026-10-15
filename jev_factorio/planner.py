"""Jev's `next_objective` decision: given the goal and what the state says so far, which
objective comes next. Text only, no image: everything it needs is in the state."""

from typesafe_sdk import Choice

from .brain import GAME_CONTEXT
from .state import GameState

GOAL = (
    "Goal: have 16 iron plates. A stone furnace smelts iron ore into iron plates, one plate per "
    "ore, and burns coal as fuel. A stone furnace is crafted from 5 stone. So the player needs "
    "a stone furnace, 16 iron ore and a few coal."
)

OBJECTIVES = {
    "check_inventory": "Open the inventory to see what the player has",
    "mine_stone": "Mine stone, to craft a stone furnace from",
    "craft_furnace": "Craft a stone furnace from 5 stone",
    "mine_coal": "Mine coal, the fuel for the furnace",
    "mine_iron": "Mine iron ore, to smelt into iron plates",
    "place_furnace": "Place a stone furnace from the inventory on the ground",
    "fuel_furnace": "Put coal into the placed furnace",
    "load_ore": "Put iron ore into the placed furnace",
    "wait_for_smelting": "Wait while the furnace smelts the ore",
    "collect_plates": "Take the iron plates out of the furnace",
    "done": "The player has 16 iron plates",
}


def next_objective_request(state: GameState) -> tuple[list, dict]:
    return [GAME_CONTEXT, GOAL, state.describe()], {
        "next_objective": Choice(
            instructions="What should the player do next to reach the goal?",
            criteria=OBJECTIVES,
        ),
    }
