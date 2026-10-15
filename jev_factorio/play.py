"""The planner loop: Jev picks `next_objective` from the state, the matching policy runs until
it is done, the state is updated, and Jev picks again.

Objectives without a policy yet stop the run, saying which one Jev chose.
"""

from collections.abc import Callable
from typing import Any

from PIL import Image

from . import actions
from .actions import Action
from .brain import Brain
from .craft import CraftPolicy
from .goto import GoToBuildingPolicy
from .inventory import CheckInventoryPolicy
from .mine import MinePolicy
from .navigate import WalkPolicy
from .place import PlaceStoneFurnacePolicy
from .planner import GOALS, Goal, next_objective_request
from .sequence import SequencePolicy
from .state import GameState
from .stone_furnace import OBJECTIVES as STONE_FURNACE_OBJECTIVES
from .stone_furnace import StoneFurnacePolicy
from .targets import TARGETS

MINE_ORES = {"mine_iron": "iron_ore", "mine_copper": "copper_ore", "mine_coal": "coal"}
MINE_ORES["mine_stone"] = "stone"


def _gather(state: GameState, objective: str, goal: Goal):
    # How many to have, a total: the "+1 Coal (N)" text counts the whole inventory.
    target = TARGETS[MINE_ORES[objective]]
    return SequencePolicy(objective, [WalkPolicy(target), MinePolicy(target, goal.mine[objective])])


def _stone_furnace(state: GameState, objective: str, goal: Goal):
    # Walk back first: mining may have taken the player far from the furnace.
    steps = [GoToBuildingPolicy(state, "stone_furnace"), StoneFurnacePolicy(state, objective)]
    return SequencePolicy(objective, steps, state)


def _craft(state: GameState, objective: str, goal: Goal):
    item, count = goal.craft[objective]
    return CraftPolicy(state, item, count)


BUILDERS: dict[str, Callable[[GameState, str, Goal], Any]] = {
    "check_inventory": lambda state, objective, goal: CheckInventoryPolicy(state, goal.check),
    "place_stone_furnace": lambda state, objective, goal: PlaceStoneFurnacePolicy(state),
    **{objective: _gather for objective in MINE_ORES},
    **{objective: _stone_furnace for objective in STONE_FURNACE_OBJECTIVES},
    "craft_gears": _craft,
    "craft_lab": _craft,
    "craft_red_science": _craft,
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
