"""The planner loop: Jev picks `next_objective` from the state, the matching policy runs until
it is done, the state is updated, and Jev picks again.

Objectives without a policy yet stop the run, saying which one Jev chose.
"""

import time
from collections.abc import Callable
from typing import Any

from PIL import Image

from . import actions, config
from .actions import Action
from .brain import Brain
from .burner_mining_drill import BurnerMiningDrillPolicy
from .craft import CraftPolicy
from .goto import GoToBuildingPolicy
from .inventory import CheckInventoryPolicy
from .mine import MinePolicy
from .navigate import WalkPolicy
from .place import PlacePolicy, stone_furnace_at_drill
from .planner import GOALS, Goal, drill_needing_fuel, next_objective_request
from .sequence import SequencePolicy
from .state import GameState
from .stone_furnace import OBJECTIVES as STONE_FURNACE_OBJECTIVES
from .stone_furnace import StoneFurnacePolicy, pick_stone_furnace
from .targets import TARGETS
from .wait import WaitPolicy

MINE_ORES = {"mine_iron": "iron_ore", "mine_copper": "copper_ore", "mine_coal": "coal"}
MINE_ORES["mine_stone"] = "stone"
CRAFTS = [
    "craft_stone_furnace",
    "craft_burner_mining_drill",
    "craft_gears",
    "craft_lab",
    "craft_red_science",
]


def _gather(state: GameState, objective: str, goal: Goal):
    # How many to have, a total: the "+1 Coal (N)" text counts the whole inventory.
    target = TARGETS[MINE_ORES[objective]]
    count = goal.count(goal.mine[objective], state)
    return SequencePolicy(objective, [WalkPolicy(target), MinePolicy(target, count)])


def _stone_furnace(state: GameState, objective: str, goal: Goal):
    # Walk back first: mining may have taken the player far from the furnace.
    furnace = pick_stone_furnace(state, objective)
    steps = [
        GoToBuildingPolicy(state, furnace, "stone_furnace"),
        StoneFurnacePolicy(state, objective, furnace),
    ]
    return SequencePolicy(objective, steps, state)


def set_up_mining(state: GameState, ore: str) -> SequencePolicy:
    """Walk to the ore, place a drill on it and a furnace at its output (without moving in
    between: the furnace's spot is worked out from the drill's), then fuel both. A site left
    half done carries on: walk back to its drill and do only what is missing."""
    drill = state.building("burner_mining_drill", ore)
    furnace = state.building("stone_furnace", ore)
    steps: list = []
    if drill is None:
        steps += [
            WalkPolicy(TARGETS[ore]),
            PlacePolicy(
                state, "burner_mining_drill", config.BURNER_MINING_DRILL_SPOTS, ore=ore, site=ore
            ),
        ]
    else:
        steps.append(GoToBuildingPolicy(state, drill, "burner_mining_drill"))
    if furnace is None:
        steps.append(
            PlacePolicy(state, "stone_furnace", stone_furnace_at_drill(state, ore), site=ore)
        )
    if drill is None or drill.started_at is None:
        steps.append(
            BurnerMiningDrillPolicy(state, lambda: state.building("burner_mining_drill", ore))
        )
    if furnace is None or not furnace.contents.get("coal"):
        steps.append(
            StoneFurnacePolicy(
                state, "fuel_stone_furnace", lambda: state.building("stone_furnace", ore)
            )
        )
    return SequencePolicy(f"set_up_{ore}_mining", steps, state)


def _fuel_drill(state: GameState, goal: Goal) -> SequencePolicy:
    drill = drill_needing_fuel(state, time.time(), goal)
    steps = [
        GoToBuildingPolicy(state, drill, "burner_mining_drill"),
        BurnerMiningDrillPolicy(state, drill),
    ]
    return SequencePolicy("fuel_burner_mining_drill", steps, state)


def _craft(state: GameState, objective: str, goal: Goal):
    item, count = goal.craft[objective]
    return CraftPolicy(state, item, goal.count(count, state))


BUILDERS: dict[str, Callable[[GameState, str, Goal], Any]] = {
    "check_inventory": lambda state, objective, goal: CheckInventoryPolicy(state, goal.check),
    "place_stone_furnace": lambda state, objective, goal: PlacePolicy(state),
    "set_up_iron_mining": lambda state, objective, goal: set_up_mining(state, "iron_ore"),
    "set_up_copper_mining": lambda state, objective, goal: set_up_mining(state, "copper_ore"),
    **{objective: _gather for objective in MINE_ORES},
    **{objective: _stone_furnace for objective in STONE_FURNACE_OBJECTIVES},
    "wait": lambda state, objective, goal: WaitPolicy(),
    "fuel_burner_mining_drill": lambda state, objective, goal: _fuel_drill(state, goal),
    **{objective: _craft for objective in CRAFTS},
}


class PlayPolicy:
    def __init__(self, state: GameState, goal: str = "red_science") -> None:
        self.state = state
        self.goal_name = goal
        self.goal = GOALS[goal]
        self.brain = Brain()
        self.objective: str | None = None
        self.current: Any = None  # the running objective's policy
        self.cost_before = 0.0  # Jev cost of planning and finished objectives
        self.total_cost = 0.0
        self.done = False
        self.success = False
        self.outcome: str | None = None  # how the run ended, for the console
        self.failures: dict[str, int] = {}  # failed attempts per objective

    def paused(self) -> None:
        if self.current is not None and hasattr(self.current, "paused"):
            self.current.paused()

    def decide(self, frame: Image.Image, tick: int) -> tuple[Action, dict]:
        if self.current is None:
            return self._plan()
        action, info = self.current.decide(frame, tick)
        info["total_cost_usd"] = self.cost_before + info.get("total_cost_usd", 0.0)
        info["play"] = {"objective": self.objective, "completed": list(self.state.completed)}
        self.total_cost = info["total_cost_usd"]
        if self.current.done:
            self._finish_objective(info)
        return action, info

    def _plan(self) -> tuple[Action, dict]:
        look = self.brain.ask({"plan": next_objective_request(self.state, self.goal)})
        self.cost_before += look["cost_usd"]
        self.total_cost = self.cost_before
        choice = look["plan"]["answers"]["next_objective"]
        objective = choice["choice"]
        ranked = sorted(choice["probs"].items(), key=lambda kv: -kv[1])[:3]
        odds = ", ".join(f"{k} {p:.2f}" for k, p in ranked)
        if objective == "done":
            self.done = self.success = True
            source, reason = "done", f"Jev says the goal is reached ({odds})"
        elif objective not in BUILDERS or (
            objective.startswith("craft_") and objective not in self.goal.craft
        ):
            self.done = True
            source, reason = "not built", f"next: {objective} ({odds}), no policy for it yet"
            self.outcome = f"stopped at {objective} (not built yet)"
        else:
            self.objective = objective
            self.current = BUILDERS[objective](self.state, objective, self.goal)
            source, reason = "plan", f"next: {objective} ({odds})"
        info = {
            "objective": "plan",
            "jev": look,
            "goal": self.goal_name,
            "state_text": self.state.describe(),
            "next_objective": objective,
            "decision": {"source": source, "reason": reason},
            "total_cost_usd": self.total_cost,
        }
        return actions.wait(0), info

    def _finish_objective(self, info: dict) -> None:
        policy, objective = self.current, self.objective
        assert policy is not None and objective is not None
        self.cost_before = info["total_cost_usd"]
        policy.cleanup()
        self.current = None
        if not getattr(policy, "success", True):
            # Plan again: a half-done objective carries on from what the state says is done.
            n = self.failures[objective] = self.failures.get(objective, 0) + 1
            if n <= config.OBJECTIVE_RETRIES:
                info["decision"]["reason"] += (
                    f"; {objective} failed ({n}/{config.OBJECTIVE_RETRIES + 1}), plan again"
                )
                return
            self.done = True
            info["decision"]["reason"] += f"; {objective} failed, stopping"
            return
        self.state.completed.append(objective)
        if objective in MINE_ORES:
            # Mining read the inventory total from the floating text; trust it.
            miner = policy.steps[-1]
            if self.state.inventory is not None and miner.count is not None:
                self.state.inventory[MINE_ORES[objective]] = miner.count
        info["decision"]["reason"] += f"; {objective} done"

    def cleanup(self) -> list[Action]:
        self.brain.close()
        return self.current.cleanup() if self.current is not None else []
