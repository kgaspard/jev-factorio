"""Objective `craft_<item>`: craft N of an item by hand from the crafting panel.

open, verify_open:      press E until Jev says the inventory is open; the crafting panel is to
                        the right of the "Character" grid.
tab_locate,
tab_confirm:            Jev boxes the recipe's tab; hovering it must show the tab's name.
                        Then left-click it (harmless if it's already selected).
recipe_locate,
recipe_confirm:         Jev boxes the recipe; its tooltip must say "<Item> (Recipe)". The
                        number on the icon is how many can be crafted now: fewer than N fails.
craft:                  left-click the recipe N times, one per tick (each click queues one).
item_locate,
item_confirm:           Jev boxes the item in the character grid and reads its tooltip, every
                        second until the count reaches what was there plus N (crafting takes
                        time: 0.5 s per gear).
close, verify_closed:   press E until the inventory is closed.
Every check is a slot of a grid: the slots under Jev's box are tried nearest first.
"""

import math
from dataclasses import dataclass

from PIL import Image

from . import actions, config
from .actions import Action
from .brain import (
    Brain,
    crafting_box_request,
    inventory_box_request,
    inventory_open_request,
    recipe_request,
    slot_request,
    tab_request,
)
from .capture import _upscaled, inventory_panel, slot_closeup
from .inventory import INVENTORY_GRID, NEUTRAL, Grid, slots_in
from .state import ICONS, ITEM_NAMES, GameState


@dataclass(frozen=True)
class Recipe:
    tab: str
    ingredients: dict[str, int]
    seconds: float  # crafting time for one craft
    makes: int = 1  # items per craft


RECIPES = {
    "iron_gear_wheel": Recipe("intermediate_products", {"iron_plate": 2}, 0.5),
    "copper_cable": Recipe("intermediate_products", {"copper_plate": 1}, 0.5, makes=2),
    "electronic_circuit": Recipe(
        "intermediate_products", {"iron_plate": 1, "copper_cable": 3}, 0.5
    ),
    "transport_belt": Recipe("logistics", {"iron_gear_wheel": 1, "iron_plate": 1}, 0.5, makes=2),
    # Crafting a lab researches "Automation science pack" (a 2.0 trigger technology).
    "lab": Recipe(
        "production",
        {"electronic_circuit": 10, "iron_gear_wheel": 10, "transport_belt": 4},
        2.0,
    ),
    "automation_science_pack": Recipe(
        "intermediate_products", {"copper_plate": 1, "iron_gear_wheel": 1}, 5.0
    ),
    "stone_furnace": Recipe("production", {"stone": 5}, 0.5),
    # Uses a stone furnace from the inventory if there is one: craft drills before furnaces.
    "burner_mining_drill": Recipe(
        "production", {"iron_gear_wheel": 3, "iron_plate": 3, "stone_furnace": 1}, 2.0
    ),
}


@dataclass
class CraftPlan:
    used: dict[str, int]  # taken from the inventory
    extra: dict[str, int]  # made beyond what was needed (a cable craft makes 2), left over
    seconds: float  # total crafting time, intermediates included


def plan_craft(item: str, count: int, have: dict[str, int]) -> CraftPlan:
    """What crafting `count` of `item` by hand takes, as Factorio does it: ingredients already
    in the inventory are used first, and missing intermediates are crafted from theirs."""
    have = dict(have)
    plan = CraftPlan({}, {}, 0.0)

    def craft(it: str, n: int) -> None:
        r = RECIPES[it]
        crafts = math.ceil(n / r.makes)
        plan.seconds += crafts * r.seconds
        if crafts * r.makes > n:
            plan.extra[it] = plan.extra.get(it, 0) + crafts * r.makes - n
        for ing, k in r.ingredients.items():
            need(ing, k * crafts)

    def need(it: str, n: int) -> None:
        take = min(have.get(it, 0), n)
        if take:
            have[it] -= take
            plan.used[it] = plan.used.get(it, 0) + take
        if n > take:
            if it in RECIPES:
                craft(it, n - take)
            else:  # a raw material that's missing; the craftable count should have caught it
                plan.used[it] = plan.used.get(it, 0) + n - take

    craft(item, count)
    return plan


# The tabs' tooltip names and what their icons look like.
TAB_NAMES = {
    "logistics": "Logistics",
    "production": "Production",
    "intermediate_products": "Intermediate products",
    "combat": "Combat",
}
TAB_LOOK = {
    "logistics": "a yellow inserter arm on a machine",
    "production": "a grey machine with a dark screen",
    "intermediate_products": "a gear, a metal plate and a green circuit board",
    "combat": "a gun with bullets",
}
TAB_GRID = Grid(config.CRAFTING_PANEL, config.CRAFT_TAB0, 4, 4, config.CRAFT_TAB_PITCH)
RECIPE_GRID = Grid(
    config.RECIPE_PANEL, config.RECIPE_SLOT0, config.RECIPE_COLUMNS, config.RECIPE_SLOTS
)


def around(slots: list[int], grid: Grid) -> list[int]:
    """The slots next to `slots` (left, right, above, below), the first slot's first: a
    recipe box landed a row off the stone furnace with either crop."""
    out: list[int] = []
    for s in slots:
        row, col = divmod(s, grid.columns)
        for r, k in ((row, col - 1), (row, col + 1), (row - 1, col), (row + 1, col)):
            i = r * grid.columns + k
            if 0 <= k < grid.columns and 0 <= i < grid.slots and i not in slots + out:
                out.append(i)
    return out


class CraftPolicy:
    def __init__(self, state: GameState, item: str, count: int) -> None:
        self.state = state
        self.item = item
        self.count = count
        self.recipe = RECIPES[item]
        self.objective = f"craft_{item}"
        self.brain = Brain()
        self.phase = "open"
        self.slot: int | None = None  # in the grid of the current phase
        self.candidates: list[int] = []
        self.clicks = 0
        held = (state.inventory or {}).get(item, 0)
        self.target = held + count  # the item count to see in the inventory
        self.plan = plan_craft(item, count, state.inventory or {})
        self.polls = 0
        self.max_polls = math.ceil(self.plan.seconds / config.CRAFT_POLL_SECONDS)
        self.max_polls += config.CRAFT_EXTRA_POLLS
        self.inventory_open = False
        self.retries = 0
        self.total_cost = 0.0
        self.done = False
        self.success = False

    def paused(self) -> None:
        # Unknown what's open now; start over (E toggles, and verify_open checks).
        self.phase, self.retries, self.clicks = "open", 0, 0

    def _tap(self, name: str, key: str) -> Action:
        return actions.Action(name, "keys", (key,), duration=config.INVENTORY_TAP_SECONDS)

    def _to(self, name: str, xy: tuple[float, float], frame: Image.Image) -> Action:
        return actions.hover(name, (xy[0] / frame.width, xy[1] / frame.height))

    def _click(self, name: str, xy: tuple[float, float], frame: Image.Image) -> Action:
        target = self._to("", xy, frame).target
        return actions.Action(name, "click", button="left", target=target, duration=0.1)

    def decide(self, frame: Image.Image, tick: int) -> tuple[Action, dict]:
        phase = self.phase
        images: dict[str, Image.Image] = {}
        jobs: dict = {}
        if phase in ("verify_open", "verify_closed"):
            images["inventory"] = inventory_panel(frame)
            jobs["open"] = inventory_open_request(images["inventory"])
        elif phase == "tab_locate":
            images["crafting"] = _upscaled(frame, config.CRAFTING_PANEL, 2)
            what = f"The '{TAB_NAMES[self.recipe.tab]}' tab: {TAB_LOOK[self.recipe.tab]}"
            jobs["locate"] = crafting_box_request(images["crafting"], what)
        elif phase == "tab_confirm":
            assert self.slot is not None
            images["slot"] = slot_closeup(frame, *TAB_GRID.centre(self.slot))
            jobs["tab"] = tab_request(images["slot"])
        elif phase == "recipe_locate":
            images["crafting"] = _upscaled(frame, config.RECIPE_PANEL, 2)
            what = f"The {ITEM_NAMES[self.item]} recipe: {ICONS[self.item]}"
            jobs["locate"] = crafting_box_request(images["crafting"], what)
        elif phase == "recipe_confirm":
            assert self.slot is not None
            images["slot"] = slot_closeup(frame, *RECIPE_GRID.centre(self.slot))
            jobs["recipe"] = recipe_request(images["slot"], list(RECIPES))
        elif phase == "item_locate":
            images["inventory"] = inventory_panel(frame)
            jobs["locate"] = inventory_box_request(images["inventory"], self.item)
        elif phase == "item_confirm":
            assert self.slot is not None
            images["slot"] = slot_closeup(frame, *INVENTORY_GRID.centre(self.slot))
            jobs["slot"] = slot_request(images["slot"])
        look: dict = self.brain.ask(jobs) if jobs else {"tokens": 0, "cost_usd": 0.0}
        self.total_cost += look["cost_usd"]
        action, source, reason = getattr(self, f"_{phase}")(look, frame)
        info = {
            "objective": self.objective,
            "phase": phase,
            "jev": look,
            "slot": self.slot,
            "decision": {"source": source, "reason": reason},
            "total_cost_usd": self.total_cost,
            "_images": images,
        }
        return action, info

    # ---- the inventory window ----
    def _open(self, look, frame):
        self.phase = "verify_open"
        return self._tap("open_inventory", "e"), "open", "press E"

    def _verify_open(self, look, frame):
        p = look["open"]["answers"]["open"]["p"]
        if p >= config.OPEN_MIN:
            self.phase, self.retries, self.inventory_open = "tab_locate", 0, True
            return actions.wait(0), "opened", f"inventory open ({p:.2f}); find the tab"
        return self._retry(f"inventory not open ({p:.2f})", self._tap("open_inventory", "e"))

    def _close(self, look, frame):
        self.phase = "verify_closed"
        return self._tap("close_inventory", "e"), "close", "press E"

    def _verify_closed(self, look, frame):
        p = look["open"]["answers"]["open"]["p"]
        if p < 1 - config.OPEN_MIN:
            self.inventory_open = False
            self.done = self.success = True
            return actions.wait(0), "closed", f"inventory closed ({p:.2f})"
        return self._retry(f"inventory still open ({p:.2f})", self._tap("close_inventory", "e"))

    # ---- shared: box a grid, then hover the slots under the box one by one ----
    def _boxed(self, look, grid: Grid, next_phase: str, what: str, frame):
        box = look["locate"]["answers"]["box"]
        self.candidates = slots_in(box["box"], grid)
        slot = self.slot = self.candidates.pop(0)
        self.phase = next_phase
        rest = f", then {self.candidates}" if self.candidates else ""
        return (
            self._to(f"hover_{what}_{slot}", grid.centre(slot), frame),
            "locate",
            f"{what} box on slot {slot}{rest} ({box['confidence'] or 0:.2f})",
        )

    def _next_candidate(self, grid: Grid, what: str, why: str, frame):
        """Hover the next slot under the box, or None when there is none left."""
        if not self.candidates:
            return None
        slot = self.slot = self.candidates.pop(0)
        return self._to(f"hover_{what}_{slot}", grid.centre(slot), frame), "next slot", why

    # ---- the tab ----
    def _tab_locate(self, look, frame):
        result = self._boxed(look, TAB_GRID, "tab_confirm", "tab", frame)
        # Only 4 tabs: when the box is wrong, hover every tab rather than box again (a box
        # landed on Logistics 4 times in a row, 0.08-0.14, with the right tab selected).
        self.candidates += [
            i for i in range(TAB_GRID.slots) if i != self.slot and i not in self.candidates
        ]
        return result

    def _tab_confirm(self, look, frame):
        c = look["tab"]["answers"]["tab"]
        p = c["probs"].get(self.recipe.tab, 0.0)
        assert self.slot is not None
        if p >= config.TOOLTIP_SAYS_MIN:
            # retries not reset: a failed recipe goes back here, and must count
            self.phase = "recipe_locate"
            return (
                self._click("select_tab", TAB_GRID.centre(self.slot), frame),
                "tab",
                f"tab {self.slot} is {self.recipe.tab} ({p:.2f}); click it",
            )
        why = f"tab {self.slot} says {c['choice']}, {self.recipe.tab} {p:.2f}"
        nxt = self._next_candidate(TAB_GRID, "tab", why, frame)
        if nxt:
            return nxt
        self.phase = "tab_locate"
        return self._retry(why, self._to("hover_off", NEUTRAL, frame))

    # ---- the recipe ----
    def _recipe_locate(self, look, frame):
        result = self._boxed(look, RECIPE_GRID, "recipe_confirm", "recipe", frame)
        assert self.slot is not None
        self.candidates += around([self.slot, *self.candidates], RECIPE_GRID)
        return result

    def _recipe_confirm(self, look, frame):
        a = look["recipe"]["answers"]
        p = a["recipe"]["probs"].get(self.item, 0.0)
        assert self.slot is not None
        if p >= config.TOOLTIP_SAYS_MIN:
            craftable = a["craftable"]["choice"]
            n = int(craftable) if craftable.isdigit() else 0
            if n < self.count:
                return self._fail(f"recipe says only {n} can be crafted, {self.count} wanted")
            self.phase, self.clicks = "craft", 1
            return (
                self._click(f"craft_1_of_{self.count}", RECIPE_GRID.centre(self.slot), frame),
                "craft",
                f"recipe {self.slot} is {self.item} ({p:.2f}), {n} craftable; click 1/{self.count}",
            )
        why = f"recipe {self.slot} says {a['recipe']['choice']}, {self.item} {p:.2f}"
        nxt = self._next_candidate(RECIPE_GRID, "recipe", why, frame)
        if nxt:
            return nxt
        self.phase = "tab_locate"  # maybe the tab click didn't take
        return self._retry(why, self._to("hover_off", NEUTRAL, frame))

    def _craft(self, look, frame):
        assert self.slot is not None
        if self.clicks < self.count:
            self.clicks += 1
            name = f"craft_{self.clicks}_of_{self.count}"
            return (
                self._click(name, RECIPE_GRID.centre(self.slot), frame),
                "craft",
                f"click {self.clicks}/{self.count}",
            )
        self.phase = "item_locate"
        return self._to("hover_off", NEUTRAL, frame), "crafted", "all queued; find the items"

    # ---- the result ----
    def _item_locate(self, look, frame):
        return self._boxed(look, INVENTORY_GRID, "item_confirm", "item", frame)

    def _item_confirm(self, look, frame):
        a = look["slot"]["answers"]
        p = a["item"]["probs"].get(self.item, 0.0)
        assert self.slot is not None
        if p >= config.TOOLTIP_SAYS_MIN:
            count = a["count"]["choice"]
            n = int(count) if count.isdigit() else 0
            if n >= self.target:
                inv = self.state.inventory
                if inv is not None:
                    inv[self.item] = n
                    for it, k in self.plan.used.items():
                        inv[it] = max(0, inv.get(it, 0) - k)
                    for it, k in self.plan.extra.items():
                        inv[it] = inv.get(it, 0) + k
                self.phase, self.retries = "close", 0
                return (
                    self._to("hover_off", NEUTRAL, frame),
                    "crafted",
                    f"slot {self.slot} holds {n} {self.item} ({p:.2f}); done",
                )
            return self._poll(f"slot {self.slot} holds {n} of {self.target} {self.item}")
        why = f"slot {self.slot} says {a['item']['choice']}, {self.item} {p:.2f}"
        nxt = self._next_candidate(INVENTORY_GRID, "item", why, frame)
        if nxt:
            return nxt
        self.phase = "item_locate"  # the first one may not be crafted yet
        return self._poll(why)

    def _poll(self, why: str):
        self.polls += 1
        if self.polls > self.max_polls:
            return self._fail(f"{why}; still not there after {self.polls - 1} looks")
        return actions.wait(config.CRAFT_POLL_SECONDS), "wait", f"{why}; crafting, wait"

    # ---- shared ----
    def _retry(self, why: str, action: Action):
        self.retries += 1
        if self.retries > config.INVENTORY_RETRIES:
            return self._fail(f"{why}; {self.retries - 1} retries")
        return action, "retry", f"{why} (retry {self.retries}/{config.INVENTORY_RETRIES})"

    def _fail(self, why: str):
        self.done = True
        if self.inventory_open:
            return self._tap("close_inventory", "e"), "give up", f"{why}; close the inventory"
        return actions.wait(0), "give up", why

    def cleanup(self) -> list[Action]:
        self.brain.close()
        return []
