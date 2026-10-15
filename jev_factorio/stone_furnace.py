"""The stone furnace objectives. Each starts by finding the furnace and ends with its window
closed (the shared steps are in building_window.py).

  fuel_stone_furnace:      put 10 coal into the fuel slot.
  load_iron_ore,
  load_copper_ore:         move all the ore into the input slot (ctrl+click).
  wait_for_smelting:       watch the hover info panel until the ore is used up.
  collect_iron_plates,
  collect_copper_plates:   move the plates from the output slot to the inventory.

Which furnace: the one at the drill on that ore for plates, the hand-fed one for ore loaded
by hand (see `pick_stone_furnace`).

watch:          (wait_for_smelting, no window) the info panel's status line and "Products
                finished", every few seconds, until the status says no ingredients.
take,
verify_taken:   (collect_*) read the output slot's count, ctrl+click it, and the output slot
                must then read empty. An empty output is no failure: nothing is ready yet.
verify_moved:   also reads the status line, for the log.
"""

import time

from PIL import Image

from . import actions, config
from .brain import (
    building_slot_request,
    panel_says_request,
    stone_furnace_panel_request,
    stone_furnace_status_request,
)
from .building_window import BuildingRef, BuildingWindowPolicy, WindowSpec
from .capture import building_slot, info_panel, stone_furnace_side
from .inventory import NEUTRAL
from .state import PLATES, Building, GameState

KIND = "stone_furnace"
ITEMS = {
    "fuel_stone_furnace": "coal",
    "load_iron_ore": "iron_ore",
    "load_copper_ore": "copper_ore",
    "collect_iron_plates": "iron_plate",
    "collect_copper_plates": "copper_plate",
}
OBJECTIVES = [*ITEMS, "wait_for_smelting"]
SPEC = WindowSpec(KIND, "Stone furnace", config.STONE_FURNACE_SLOTS, config.STONE_FURNACE_GRID_DY)
ORES = {v: k for k, v in PLATES.items()}


def pick_stone_furnace(state: GameState, objective: str) -> Building | None:
    """The furnace an objective is about. Plates: the furnace at the drill on that ore, else
    the hand-fed one that smelted it. Ore by hand: the hand-fed furnace already on that ore,
    else an empty hand-fed one, else the one at the drill on that ore. None: not known yet
    (found by box)."""
    furnaces = [b for b in state.buildings if b.kind == KIND]
    hand = [b for b in furnaces if b.site is None]
    item = ITEMS.get(objective)
    ore = ORES.get(item or "", item)
    at_drill = [b for b in furnaces if ore and b.site == ore]
    if objective.startswith("collect_") and ore:
        smelted = [b for b in hand if b.holds([ore, PLATES[ore]])]
        return next(iter(at_drill + smelted + hand), None)
    if objective.startswith("load_") and ore:
        same = [b for b in hand if b.holds([ore, PLATES[ore]])]
        empty = [b for b in hand if not b.holds(list(PLATES) + list(PLATES.values()))]
        return next(iter(same + empty + at_drill), None)
    if objective == "fuel_stone_furnace":
        unfuelled = [b for b in hand + at_drill if not b.contents.get("coal")]
        unfuelled += [b for b in furnaces if b.site and not b.contents.get("coal")]
        return next(iter(unfuelled + hand), None)
    smelting = [b for b in hand if b.holds(PLATES)]  # wait_for_smelting
    return next(iter(smelting + hand), None)


class StoneFurnacePolicy(BuildingWindowPolicy):
    SPEC = SPEC

    def __init__(self, state: GameState, objective: str, furnace: BuildingRef = None) -> None:
        super().__init__(state, objective, ITEMS.get(objective, "coal"), furnace)
        self.taken = 0  # collect_*: plates taken by earlier clicks
        self.polls = 0  # wait_for_smelting panel reads

    def _look(self, phase: str, frame: Image.Image) -> tuple[dict, dict]:
        images, jobs = super()._look(phase, frame)
        if phase == "watch":
            images["panel"] = info_panel(frame)
            jobs["panel"] = panel_says_request(images["panel"], SPEC.title)
            jobs["watch"] = stone_furnace_panel_request(images["panel"])
        elif phase in ("take", "verify_taken"):
            images["output"] = building_slot(frame, self._slot("output"))
            kinds = list(PLATES.values()) if phase == "take" else None
            jobs["output"] = building_slot_request(images["output"], kinds)
        elif phase == "verify_moved":
            images["side"] = stone_furnace_side(frame)
            jobs["status"] = stone_furnace_status_request(images["side"])
        return images, jobs

    def _moved(self, n: int) -> None:
        b = self._building()
        if self.item == "coal" and b.started_at is None:
            b.started_at = time.time()

    def _after_find(self) -> str:
        return "watch" if self.objective == "wait_for_smelting" else "check_hover"

    def _after_open(self) -> str:
        return "take" if self.objective.startswith("collect_") else "locate"

    def _verify_moved(self, look, frame):
        action, source, reason = super()._verify_moved(look, frame)
        s = look["status"]["answers"]["status"]
        return action, source, f"{reason}; status {s['choice']} ({s['confidence'] or 0:.2f})"

    # ---- wait_for_smelting: the info panel ----
    def _watch(self, look, frame):
        says = look["panel"]["answers"]["says"]["p"]
        if says < config.PANEL_SAYS_MIN:
            self.phase = "find"  # the cursor isn't on the furnace any more
            return self._retry(f"panel doesn't say stone furnace ({says:.2f})", actions.wait(0))
        a = look["watch"]["answers"]
        status, p = a["status"]["choice"], a["status"]["confidence"] or 0
        finished = a["finished"]["choice"]
        self.retries = 0
        self.polls += 1
        why = f"{status} ({p:.2f}), {finished} finished"
        if p >= config.STATUS_MIN and status in ("no_ingredients", "output_full"):
            # "Products finished" counts the furnace's whole life; plates taken out before
            # are in `taken`. The ore is used up; what's left is plates of its kind.
            b = self._building()
            ore = b.holds(PLATES)
            if ore:
                b.contents.pop(ore)
                if finished.isdigit():
                    b.contents[PLATES[ore]] = int(finished) - sum(b.taken.values())
            self.done = self.success = True
            return self._to("hover_off", NEUTRAL, frame), "smelted", f"{why}; done"
        if p >= config.STATUS_MIN and status == "no_fuel":
            return self._fail(f"{why}; the furnace needs fuel")
        if self.polls >= config.SMELT_MAX_POLLS:
            return self._fail(f"{why}; still not done after {self.polls} looks")
        return actions.wait(config.SMELT_POLL_SECONDS), "wait", f"{why}; wait"

    # ---- collect_*: the output slot ----
    def _output_target(self, frame) -> tuple[float, float]:
        x, y = self._slot("output")
        return x / frame.width, y / frame.height

    def _take(self, look, frame):
        c = look["output"]["answers"]["count"]
        empty, count = c["probs"].get("0", 0.0), c["choice"]
        if empty > config.STONE_FURNACE_EMPTY_MAX or not count.isdigit():
            self.phase, self.retries = "verify_closed", 0
            return (
                self._tap("close_window", "e"),
                "nothing yet",
                f"output slot reads empty ({empty:.2f}), nothing to collect yet; close",
            )
        other = self._other_site(look["output"]["answers"]["item"]["choice"])
        if other is not None:
            return self._fail(other)
        self.held, self.phase = int(count), "verify_taken"
        return (
            actions.Action(
                "take_plates", "click", ("ctrl",), "left", self._output_target(frame), 0.1
            ),
            "take",
            f"output slot holds {count} ({1 - empty:.2f}); ctrl+click it out",
        )

    def _other_site(self, plate: str) -> str | None:
        """The output holds the other site's plates: this is that site's furnace (they look the
        same; after a drift it collected 11 iron plates as copper). The player is then where
        that furnace is, not this one: move the player's position by the gap between them."""
        b = self._building()
        if plate == self.item or plate not in PLATES.values() or b.at is None:
            return None
        ore = ORES[plate]
        there = self.state.building(SPEC.kind, ore)
        if there is None or there.at is None:
            return f"output holds {plate}, not {self.item}"
        x, y = self.state.player_at
        self.state.player_at = (x + there.at[0] - b.at[0], y + there.at[1] - b.at[1])
        return f"output holds {plate}: this is the {ore} site's furnace; position corrected"

    def _verify_taken(self, look, frame):
        c = look["output"]["answers"]["count"]
        empty = c["probs"].get("0", 0.0)
        if empty >= 1 - config.STONE_FURNACE_EMPTY_MAX:
            took = self.taken + self.held
            self._building().took(self.item, took)
            inv = self.state.inventory
            if inv is not None:
                inv[self.item] = inv.get(self.item, 0) + took
            self.phase, self.retries = "verify_closed", 0
            return (
                self._tap("close_window", "e"),
                "taken",
                f"output slot empty ({empty:.2f}), took {took} {self.item}; close",
            )
        # More may have finished meanwhile (fewer than before: the click took), or the click
        # didn't take (as many as before): read and click again.
        left = c["choice"]
        if left.isdigit() and int(left) < self.held:
            self.taken += self.held
        self.phase = "take"
        return self._retry(
            f"output slot still holds {c['choice']} ({1 - empty:.2f})", actions.wait(0)
        )
