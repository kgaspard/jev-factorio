"""The furnace objectives. Each starts by finding the furnace and ends with its window closed.

  fuel_furnace, load_ore:  move coal (fuel) or iron ore (input) in from the inventory.
  wait_for_smelting:       watch the hover info panel until the ore is used up.
  collect_plates:          move the plates from the output slot to the inventory.

find:           Jev boxes the furnace in the game view; the cursor goes to the box centre.
                Its recorded position isn't trusted: the furnace turned up elsewhere (O43).
check_hover:    Factorio's info panel must say "Stone furnace". Then left-click to open it.
verify_open:    Jev says the furnace window is open.
watch:          (wait_for_smelting, no window) the info panel's status line and "Products
                finished", every few seconds, until the status says no ingredients.
take,
verify_taken:   (collect_plates) read the output slot's count, ctrl+click it, and the output
                slot must then read empty.
locate,
confirm:        as in the inventory check, but in the window's character grid (4 px higher):
                Jev boxes the item's slot; the tooltip of one of the slots under the box
                (nearest the centre first, up to 3) must name it.
                Then ctrl+click: Factorio moves all of that item into the furnace slot it fits.
verify_moved:   Jev reads the count in the fuel slot (coal) or the ore input slot (iron ore)
                from its own close-up, and the status line. The slot must hold something.
                If not, box the item again: the inventory re-sorts after a move, so the old
                slot may now hold something else.
close,
verify_closed:  press E until the window is closed.
"""

from PIL import Image

from . import actions, config
from .actions import Action
from .brain import (
    Brain,
    furnace_box_request,
    furnace_panel_request,
    furnace_slot_request,
    furnace_status_request,
    inventory_box_request,
    panel_says_request,
    slot_request,
    window_open_request,
)
from .capture import (
    for_jev,
    furnace_side,
    furnace_slot,
    furnace_window,
    info_panel,
    inventory_panel,
    slot_closeup,
)
from .inventory import NEUTRAL, slot_centre, slots_in
from .state import Furnace, GameState

ITEMS = {"fuel_furnace": "coal", "load_ore": "iron_ore"}
OBJECTIVES = [*ITEMS, "wait_for_smelting", "collect_plates"]
SLOT = {"coal": "fuel", "iron_ore": "input"}  # where ctrl+click puts it


def grid_slot_centre(i: int) -> tuple[int, int]:
    x, y = slot_centre(i)
    return x, y + config.FURNACE_GRID_DY


class StoneFurnacePolicy:
    def __init__(self, state: GameState, objective: str) -> None:
        self.state = state
        self.objective = objective
        self.item = ITEMS.get(objective, "iron_plate")
        self.brain = Brain()
        self.phase = "find"
        self.furnace_px: tuple[float, float] | None = None
        self.slot: int | None = None
        self.candidates: list[int] = []  # slots under the box still to check
        self.held = 0  # the count read off the inventory slot (or the output slot)
        self.polls = 0  # wait_for_smelting panel reads
        self.taken = 0  # collect_plates: plates taken by earlier clicks
        self.window_open = False  # as last seen by Jev, or assumed after a failed close
        self.retries = 0
        self.total_cost = 0.0
        self.done = False
        self.success = False

    def paused(self) -> None:
        # A window may be open; E in cleanup/close handles it. Start over from finding.
        self.phase, self.retries = "find", 0

    def _tap(self, name: str, key: str) -> Action:
        return actions.Action(name, "keys", (key,), duration=config.INVENTORY_TAP_SECONDS)

    def _to(self, name: str, xy: tuple[float, float], frame: Image.Image) -> Action:
        return actions.hover(name, (xy[0] / frame.width, xy[1] / frame.height))

    def decide(self, frame: Image.Image, tick: int) -> tuple[Action, dict]:
        phase = self.phase
        images: dict[str, Image.Image] = {}
        jobs: dict = {}
        if phase == "find":
            images["view"] = for_jev(frame)
            jobs["find"] = furnace_box_request(images["view"])
        elif phase in ("check_hover", "watch"):
            images["panel"] = info_panel(frame)
            jobs["panel"] = panel_says_request(images["panel"], "Stone furnace")
            if phase == "watch":
                jobs["watch"] = furnace_panel_request(images["panel"])
        elif phase in ("take", "verify_taken"):
            images["output"] = furnace_slot(frame, "output")
            jobs["output"] = furnace_slot_request(images["output"])
        elif phase in ("verify_open", "verify_closed"):
            images["window"] = furnace_window(frame)
            jobs["window"] = window_open_request(images["window"])
        elif phase == "locate":
            images["inventory"] = inventory_panel(frame)
            jobs["locate"] = inventory_box_request(images["inventory"], self.item)
        elif phase == "confirm":
            assert self.slot is not None
            images["slot"] = slot_closeup(frame, *grid_slot_centre(self.slot))
            jobs["slot"] = slot_request(images["slot"])
        elif phase == "verify_moved":
            images["side"] = furnace_side(frame)
            jobs["status"] = furnace_status_request(images["side"])
            for name in config.FURNACE_SLOTS:
                images[name] = furnace_slot(frame, name)
                jobs[name] = furnace_slot_request(images[name])
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

    # ---- the furnace in the world ----
    def _find(self, look, frame):
        a = look["find"]["answers"]["box"]
        b = a["box"]
        self.furnace_px = ((b[0] + b[2]) / 2 * frame.width, (b[1] + b[3]) / 2 * frame.height)
        self.phase = "watch" if self.objective == "wait_for_smelting" else "check_hover"
        x, y = self.furnace_px
        return (
            self._to("hover_furnace", self.furnace_px, frame),
            "find",
            f"furnace boxed at ({x:.0f},{y:.0f}) ({a['confidence'] or 0:.2f})",
        )

    def _check_hover(self, look, frame):
        p = look["panel"]["answers"]["says"]["p"]
        if p >= config.PANEL_SAYS_MIN:
            assert self.furnace_px is not None
            if self.state.furnace is None:
                self.state.furnace = Furnace()
            self.phase, self.retries = "verify_open", 0
            return self._open_click(frame), "open", f"panel says stone furnace ({p:.2f}); open it"
        self.phase = "find"
        return self._retry(f"panel doesn't say stone furnace ({p:.2f})", actions.wait(0))

    def _open_click(self, frame) -> Action:
        assert self.furnace_px is not None
        target = self._to("", self.furnace_px, frame).target
        return actions.Action("open_furnace", "click", button="left", target=target, duration=0.1)

    def _verify_open(self, look, frame):
        p = look["window"]["answers"]["open"]["p"]
        if p >= config.WINDOW_OPEN_MIN:
            self.retries, self.window_open = 0, True
            self.phase = "take" if self.objective == "collect_plates" else "locate"
            # Off the window, so no tooltip covers the grid.
            return self._to("hover_off", NEUTRAL, frame), "opened", f"window open ({p:.2f})"
        return self._retry(f"window not open ({p:.2f})", self._open_click(frame))

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
            f = self.state.furnace or Furnace()
            self.state.furnace = f
            if finished.isdigit():
                f.plates_ready = int(finished) - f.plates_taken
            f.ore = 0
            self.done = self.success = True
            return self._to("hover_off", NEUTRAL, frame), "smelted", f"{why}; done"
        if p >= config.STATUS_MIN and status == "no_fuel":
            return self._fail(f"{why}; the furnace needs fuel")
        if self.polls >= config.SMELT_MAX_POLLS:
            return self._fail(f"{why}; still not done after {self.polls} looks")
        return actions.wait(config.SMELT_POLL_SECONDS), "wait", f"{why}; wait"

    # ---- collect_plates: the output slot ----
    def _output_target(self, frame) -> tuple[float, float]:
        x, y = config.FURNACE_SLOTS["output"]
        return x / frame.width, y / frame.height

    def _take(self, look, frame):
        c = look["output"]["answers"]["count"]
        empty, count = c["probs"].get("0", 0.0), c["choice"]
        if empty > config.FURNACE_EMPTY_MAX or not count.isdigit():
            return self._fail(f"output slot reads empty ({empty:.2f}), nothing to collect")
        self.held, self.phase = int(count), "verify_taken"
        return (
            actions.Action(
                "take_plates", "click", ("ctrl",), "left", self._output_target(frame), 0.1
            ),
            "take",
            f"output slot holds {count} ({1 - empty:.2f}); ctrl+click it out",
        )

    def _verify_taken(self, look, frame):
        c = look["output"]["answers"]["count"]
        empty = c["probs"].get("0", 0.0)
        if empty >= 1 - config.FURNACE_EMPTY_MAX:
            took = self.taken + self.held
            f = self.state.furnace or Furnace()
            self.state.furnace = f
            f.plates_taken += took
            f.plates_ready = 0
            inv = self.state.inventory
            if inv is not None:
                inv["iron_plate"] = inv.get("iron_plate", 0) + took
            self.phase, self.retries = "verify_closed", 0
            return (
                self._tap("close_window", "e"),
                "taken",
                f"output slot empty ({empty:.2f}), took {took} plates; close",
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

    # ---- the character grid ----
    def _locate(self, look, frame):
        a = look["locate"]["answers"]
        self.candidates = slots_in(a["box"]["box"])
        if not self.candidates:
            return self._fail(f"{self.item} box off the grid")
        slot = self.slot = self.candidates.pop(0)
        self.phase = "confirm"
        rest = f", then {self.candidates}" if self.candidates else ""
        return (
            self._to(f"hover_slot_{slot}", grid_slot_centre(slot), frame),
            "locate",
            f"{self.item} box on slot {slot}{rest} ({a['box']['confidence'] or 0:.2f})",
        )

    def _confirm(self, look, frame):
        a = look["slot"]["answers"]
        p = a["item"]["probs"].get(self.item, 0.0)
        if p >= config.TOOLTIP_SAYS_MIN:
            assert self.slot is not None
            self.held = int(a["count"]["choice"]) if a["count"]["choice"].isdigit() else 0
            self.phase = "verify_moved"
            target = self._to("", grid_slot_centre(self.slot), frame).target
            return (
                actions.Action(
                    f"move_{self.item}", "click", ("ctrl",), "left", target, duration=0.1
                ),
                "move",
                f"slot {self.slot} is {self.held} {self.item} ({p:.2f}); ctrl+click it in",
            )
        why = f"slot {self.slot} says {a['item']['choice']}, {self.item} {p:.2f}"
        if self.candidates:
            self.slot = self.candidates.pop(0)
            return (
                self._to(f"hover_slot_{self.slot}", grid_slot_centre(self.slot), frame),
                "next slot",
                f"{why}; try slot {self.slot}",
            )
        if self.state.inventory is not None:
            self.state.inventory[self.item] = 0
        return self._fail(f"{why}; no {self.item} in the inventory")

    # ---- the furnace half of the window ----
    def _verify_moved(self, look, frame):
        s = look["status"]["answers"]["status"]
        status = f"status {s['choice']} ({s['confidence'] or 0:.2f})"
        c = look[SLOT[self.item]]["answers"]["count"]
        empty, count = c["probs"].get("0", 0.0), c["choice"]
        if empty <= config.FURNACE_EMPTY_MAX:
            # Ctrl+click moves the whole stack (both fit in a furnace slot). The slot count
            # is already lower: the furnace starts burning and smelting at once (16 ore in,
            # the slot read 15 with one at 4%), so count what left the inventory.
            f = self.state.furnace or Furnace()
            self.state.furnace = f
            if self.item == "coal":
                f.fuel += self.held
            else:
                f.ore += self.held
            if self.state.inventory is not None:
                self.state.inventory[self.item] = 0
            self.phase, self.retries = "verify_closed", 0
            return (
                self._tap("close_window", "e"),
                "moved",
                f"{SLOT[self.item]} slot holds {count} ({1 - empty:.2f}), {status}; close",
            )
        # The click may not have taken. Box the item again (the inventory may have re-sorted).
        self.phase = "locate"
        return self._retry(
            f"{SLOT[self.item]} slot reads empty ({empty:.2f}), {status}",
            self._to("hover_off", NEUTRAL, frame),
        )

    def _verify_closed(self, look, frame):
        p = look["window"]["answers"]["open"]["p"]
        if p < config.WINDOW_CLOSED_MAX:
            self.window_open = False
            self.done = self.success = True
            return self._to("hover_off", NEUTRAL, frame), "closed", f"window closed ({p:.2f})"
        return self._retry(f"window still open ({p:.2f})", self._tap("close_window", "e"))

    # ---- shared ----
    def _retry(self, why: str, action: Action):
        self.retries += 1
        if self.retries > config.INVENTORY_RETRIES:
            return self._fail(f"{why}; {self.retries - 1} retries")
        return action, "retry", f"{why} (retry {self.retries}/{config.INVENTORY_RETRIES})"

    def _fail(self, why: str):
        self.done = True
        if self.window_open:
            return self._tap("close_window", "e"), "give up", f"{why}; close the window"
        return actions.wait(0), "give up", why

    def cleanup(self) -> list[Action]:
        self.brain.close()
        return []
