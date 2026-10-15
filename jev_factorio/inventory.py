"""Objective `check_inventory`: open the inventory, look for the items the plan needs, close it.

open:         press E.
verify_open:  Jev says whether the "Character" window is open. Not open: press E again.
locate:       Jev boxes the slot holding the wanted item; the cursor goes to that slot.
confirm:      Jev reads the hovered slot's tooltip title and the number on its icon. Title is
              the wanted item: record the count. Another item: hover the neighbouring slot on
              the side the box leaned towards (a box once landed one slot off), then record
              it as absent. Re-boxing doesn't help: Jev puts the box in the same place (O37).
              The cursor then leaves the grid so the tooltip can't hide slots.
close:        press E, and Jev checks it closed.
The box alone can't tell present from absent (uranium ore boxed the iron ore slot with the
same confidence as real items), but the tooltip can (O36).
"""

from PIL import Image

from . import actions, config
from .actions import Action
from .brain import Brain, inventory_box_request, inventory_open_request, slot_request
from .capture import inventory_panel, slot_closeup
from .state import GameState

NEEDED = ["stone_furnace", "iron_ore", "coal", "stone", "iron_plate"]  # for 16 iron plates
NEUTRAL = (300, 500)  # cursor spot off the inventory grid, in game-area pixels


def slot_centre(i: int) -> tuple[int, int]:
    """Centre of inventory slot i in pixels of the 1920x1080 game area."""
    x0, y0 = config.INVENTORY_SLOT0
    row, col = divmod(i, config.INVENTORY_COLUMNS)
    return x0 + col * config.INVENTORY_SLOT_PITCH, y0 + row * config.INVENTORY_SLOT_PITCH


def slot_at(box: list[float]) -> tuple[int | None, int | None]:
    """The slot under the centre of a box given as fractions of the inventory panel crop, and
    the slot next to it on the side the centre leans towards (None at the grid's edge)."""
    left, top, right, bottom = config.INVENTORY_PANEL
    cx = left + (box[0] + box[2]) / 2 * (right - left)
    cy = top + (box[1] + box[3]) / 2 * (bottom - top)
    x0, y0 = config.INVENTORY_SLOT0
    fx = (cx - x0) / config.INVENTORY_SLOT_PITCH
    col = round(fx)
    row = round((cy - y0) / config.INVENTORY_SLOT_PITCH)
    rows = config.INVENTORY_SLOTS // config.INVENTORY_COLUMNS
    if not (0 <= col < config.INVENTORY_COLUMNS and 0 <= row < rows):
        return None, None
    side = -1 if fx < col else 1
    ncol = col + side
    if not 0 <= ncol < config.INVENTORY_COLUMNS:
        ncol = col - side
    return row * config.INVENTORY_COLUMNS + col, row * config.INVENTORY_COLUMNS + ncol


class CheckInventoryPolicy:
    def __init__(self, state: GameState, wanted: list[str] | None = None) -> None:
        self.state = state
        self.wanted = list(wanted or NEEDED)
        self.brain = Brain()
        self.phase = "open"
        self.index = 0  # which wanted item
        self.slot: int | None = None
        self.neighbour: int | None = None  # slot to try if the boxed one is wrong
        self.tried_neighbour = False
        self.found: dict[str, int] = {}  # wanted items: count, 0 = not there
        self.seen: dict[str, int] = {}  # other items read on the way
        self.retries = 0
        self.total_cost = 0.0
        self.done = False
        self.success = False

    @property
    def item(self) -> str:
        return self.wanted[self.index]

    def paused(self) -> None:
        """Focus lost: the inventory may have been closed or the cursor moved; start over."""
        self.phase, self.index, self.retries = "open", 0, 0

    def _tap_e(self, name: str) -> Action:
        return actions.Action(name, "keys", ("e",), duration=config.INVENTORY_TAP_SECONDS)

    def _to(self, name: str, xy: tuple[int, int], frame: Image.Image) -> Action:
        return actions.hover(name, (xy[0] / frame.width, xy[1] / frame.height))

    def decide(self, frame: Image.Image, tick: int) -> tuple[Action, dict]:
        phase = self.phase
        images: dict[str, Image.Image] = {}
        jobs: dict = {}
        if phase in ("verify_open", "verify_closed"):
            images["inventory"] = inventory_panel(frame)
            jobs["open"] = inventory_open_request(images["inventory"])
        elif phase == "locate":
            images["inventory"] = inventory_panel(frame)
            jobs["locate"] = inventory_box_request(images["inventory"], self.item)
        elif phase == "confirm":
            assert self.slot is not None
            images["slot"] = slot_closeup(frame, *slot_centre(self.slot))
            jobs["slot"] = slot_request(images["slot"], extra=self.wanted)
        look: dict = self.brain.ask(jobs) if jobs else {"tokens": 0, "cost_usd": 0.0}
        self.total_cost += look["cost_usd"]
        looking_for = self.item

        if phase == "open":
            self.phase = "verify_open"
            action, source, reason = self._tap_e("open_inventory"), "open", "press E"
        elif phase == "verify_open":
            action, source, reason = self._verify_open(look["open"]["answers"]["open"]["p"])
        elif phase == "locate":
            action, source, reason = self._locate(look["locate"]["answers"], frame)
        elif phase == "confirm":
            action, source, reason = self._confirm(look["slot"]["answers"], frame)
        else:  # verify_closed
            action, source, reason = self._verify_closed(look["open"]["answers"]["open"]["p"])

        info = {
            "objective": "check_inventory",
            "phase": phase,
            "jev": look,
            "wanted": self.wanted,
            "looking_for": looking_for,
            "slot": self.slot,
            "items": dict(self.found),
            "seen": dict(self.seen),
            "decision": {"source": source, "reason": reason},
            "total_cost_usd": self.total_cost,
            "_images": images,
        }
        return action, info

    def _verify_open(self, p: float):
        if p >= config.OPEN_MIN:
            self.phase, self.retries = "locate", 0
            return actions.wait(0), "opened", f"inventory open ({p:.2f}); look for {self.item}"
        return self._retry(f"inventory not open ({p:.2f})", self._tap_e("open_inventory"))

    def _locate(self, a: dict, frame: Image.Image):
        box = a["box"]
        slot, self.neighbour = slot_at(box["box"])
        self.tried_neighbour = False
        conf = box["confidence"] or 0
        if slot is None:
            return self._next_item(0, f"{self.item}: box off the grid", frame)
        self.slot, self.phase = slot, "confirm"
        return (
            self._to(f"hover_slot_{slot}", slot_centre(slot), frame),
            "locate",
            f"{self.item}: box on slot {slot} (conf {conf:.2f}, there {a['there']['p']:.2f})",
        )

    def _confirm(self, a: dict, frame: Image.Image):
        item = a["item"]
        p = item["probs"].get(self.item, 0.0)
        count = a["count"]["choice"]
        if p >= config.TOOLTIP_SAYS_MIN and count not in ("none", None):
            n = 101 if count == "more" else int(count)
            return self._next_item(n, f"slot {self.slot}: {n} {self.item} ({p:.2f})", frame)
        what = item["choice"]
        if what not in ("none", "other") and count not in ("none", "more"):
            self.seen[what] = int(count)  # free knowledge, e.g. iron ore when asked for uranium
        why = f"slot {self.slot} says {what} ({item['confidence']:.2f}), {self.item} {p:.2f}"
        if not self.tried_neighbour and self.neighbour is not None:
            self.slot, self.tried_neighbour = self.neighbour, True
            return (
                self._to(f"hover_slot_{self.slot}", slot_centre(self.slot), frame),
                "neighbour",
                f"{why}; try slot {self.slot}",
            )
        return self._next_item(0, why + f"; no {self.item}", frame)

    def _next_item(self, count: int, why: str, frame: Image.Image):
        self.found[self.item] = count
        self.index += 1
        self.slot = None
        if self.index < len(self.wanted):
            self.phase = "locate"
            return (
                self._to("hover_off_grid", NEUTRAL, frame),
                "found" if count else "not there",
                f"{why}; next: {self.item}",
            )
        self.index -= 1  # keep `item` valid for logging
        self.state.set_inventory({**self.seen, **self.found})
        self.phase, self.retries = "verify_closed", 0
        return self._tap_e("close_inventory"), "close", f"{why}; close"

    def _verify_closed(self, p: float):
        if p < 1 - config.OPEN_MIN:
            self.done = self.success = True
            return actions.wait(0), "done", "inventory closed; " + self.state.describe_inventory()
        return self._retry(f"inventory still open ({p:.2f})", self._tap_e("close_inventory"))

    def _retry(self, why: str, action: Action):
        self.retries += 1
        if self.retries > config.INVENTORY_RETRIES:
            self.done = True
            return actions.wait(0), "give up", f"{why}; {self.retries - 1} retries"
        return action, "retry", f"{why} (retry {self.retries}/{config.INVENTORY_RETRIES})"

    def cleanup(self) -> list[Action]:
        self.brain.close()
        # Stopped while looking: the inventory is known to be open, so close it.
        open_phases = ("locate", "confirm")
        return [self._tap_e("close_inventory")] if self.phase in open_phases else []
