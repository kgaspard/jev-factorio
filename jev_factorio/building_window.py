"""What every building objective does: find the building, open its window, move an item in,
close the window. The stone furnace and the burner mining drill add their own slots.

find:           the building's recorded position, when it is on screen (right after placing it,
                or after walking back); otherwise Jev boxes it in the game view. The
                cursor goes there.
check_hover:    Factorio's info panel must say the building's name. Then left-click to open it.
                Not it from the recorded position: box it instead.
verify_open:    Jev says which window is open: this building's.
locate,
confirm:        as in the inventory check, but in the window's character grid: Jev boxes the
                item's slot; the tooltip of one of the slots under the box (nearest the centre
                first, up to 3) must name it.
                Ore: ctrl+click, Factorio moves all of it into the slot it fits.
                Fuel: a set amount, not all of it (the coal is shared between buildings):
pick, put,
stow:           left-click picks the coal stack up, right-clicks on the fuel slot put one each,
                and Q puts the rest back into the inventory.
verify_moved:   Jev reads the count in the slot from its own close-up. It must hold something.
                If not, box the item again: the inventory re-sorts after a move, so the old
                slot may now hold something else.
verify_closed:  press E until no window is open.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image

from . import actions, config
from .actions import Action
from .brain import (
    Brain,
    building_box_request,
    building_slot_request,
    inventory_box_request,
    panel_says_request,
    slot_request,
    window_request,
)
from .capture import (
    building_slot,
    building_window,
    for_jev,
    info_panel,
    inventory_panel,
    slot_closeup,
)
from .inventory import NEUTRAL, slot_centre, slots_in
from .state import Building, GameState


@dataclass(frozen=True)
class WindowSpec:
    kind: str  # the building's item name
    title: str  # in its info panel and window title
    slots: dict[str, tuple[int, int]]  # its slots' centres in the open window
    grid_dy: int  # its window's character grid sits this much lower than the inventory's


# Where ctrl+click (or the right-clicks) put an item.
SLOT = {"coal": "fuel", "iron_ore": "input", "copper_ore": "input"}

# A building, or how to find it in the state once the policy starts (it may be placed by the
# step before).
BuildingRef = Building | Callable[[], Building | None] | None


class BuildingWindowPolicy:
    SPEC: WindowSpec

    def __init__(self, state: GameState, objective: str, item: str, building: BuildingRef) -> None:
        self.state = state
        self.objective = objective
        self.item = item
        self._ref = building
        self._resolved: Building | None = None
        self.brain = Brain()
        self.phase = "find"
        self.px: tuple[float, float] | None = None  # the building on screen
        self.from_memory = False  # px came from its recorded position
        self.slot: int | None = None
        self.candidates: list[int] = []  # slots under the box still to check
        self.held = 0  # the count read off the inventory slot
        self.window_open = False  # as last seen by Jev, or assumed after a failed close
        self.retries = 0
        self.total_cost = 0.0
        self.done = False
        self.success = False

    @property
    def building(self) -> Building | None:
        if self._resolved is None:
            ref = self._ref
            self._resolved = ref() if callable(ref) else ref
        return self._resolved

    def _building(self) -> Building:
        """This building in the state, added if the state didn't know it yet."""
        if self.building is None:
            self._resolved = self.state.add(Building(self.SPEC.kind))
        assert self._resolved is not None
        return self._resolved

    def paused(self) -> None:
        # A window may be open; E in close handles it. Start over from finding.
        self.phase, self.retries = "find", 0

    def _tap(self, name: str, key: str) -> Action:
        return actions.Action(name, "keys", (key,), duration=config.INVENTORY_TAP_SECONDS)

    def _to(self, name: str, xy: tuple[float, float], frame: Image.Image) -> Action:
        return actions.hover(name, (xy[0] / frame.width, xy[1] / frame.height))

    def _grid_centre(self, i: int) -> tuple[int, int]:
        x, y = slot_centre(i)
        return x, y + self.SPEC.grid_dy

    def _slot(self, name: str) -> tuple[int, int]:
        return self.SPEC.slots[name]

    # ---- one tick ----
    def _look(self, phase: str, frame: Image.Image) -> tuple[dict, dict]:
        """The images and Jev requests of a phase."""
        images: dict[str, Image.Image] = {}
        jobs: dict = {}
        if phase == "find":
            if self._remembered_px(frame) is None:
                images["view"] = for_jev(frame)
                jobs["find"] = building_box_request(images["view"], self.SPEC.kind)
        elif phase == "check_hover":
            images["panel"] = info_panel(frame)
            jobs["panel"] = panel_says_request(images["panel"], self.SPEC.title)
        elif phase in ("verify_open", "verify_closed"):
            images["window"] = building_window(frame)
            jobs["window"] = window_request(images["window"])
        elif phase == "locate":
            images["inventory"] = inventory_panel(frame)
            jobs["locate"] = inventory_box_request(images["inventory"], self.item)
        elif phase == "confirm":
            assert self.slot is not None
            images["slot"] = slot_closeup(frame, *self._grid_centre(self.slot))
            jobs["slot"] = slot_request(images["slot"])
        elif phase == "verify_moved":
            name = SLOT[self.item]
            images[name] = building_slot(frame, self._slot(name))
            jobs[name] = building_slot_request(images[name])
        return images, jobs

    def decide(self, frame: Image.Image, tick: int) -> tuple[Action, dict]:
        phase = self.phase
        images, jobs = self._look(phase, frame)
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

    # ---- the building in the world ----
    def _remembered_px(self, frame: Image.Image) -> tuple[float, float] | None:
        """Its recorded position on screen, if it has one, it is in view and it hasn't been
        tried yet."""
        b = self.building
        if b is None or b.at is None or self.from_memory:
            return None
        x = frame.width / 2 + (b.at[0] - self.state.player_at[0]) * config.TILE_PX
        y = frame.height / 2 + (b.at[1] - self.state.player_at[1]) * config.TILE_PX
        if not (64 <= x <= frame.width - 320 and 64 <= y <= frame.height - 220):
            return None  # off screen, or under the minimap and info panel
        return x, y

    def _find(self, look, frame):
        name = self.SPEC.kind
        px = self._remembered_px(frame)
        if px is not None:
            self.px, self.from_memory = px, True
            why = f"{name} where it was left, at ({px[0]:.0f},{px[1]:.0f})"
        else:
            a = look["find"]["answers"]["box"]
            b = a["box"]
            self.px = ((b[0] + b[2]) / 2 * frame.width, (b[1] + b[3]) / 2 * frame.height)
            self.from_memory = True  # don't go back to the memory after a box
            x, y = self.px
            why = f"{name} boxed at ({x:.0f},{y:.0f}) ({a['confidence'] or 0:.2f})"
        self.phase = self._after_find()
        return self._to(f"hover_{name}", self.px, frame), "find", why

    def _after_find(self) -> str:
        return "check_hover"

    def _check_hover(self, look, frame):
        p = look["panel"]["answers"]["says"]["p"]
        if p >= config.PANEL_SAYS_MIN:
            assert self.px is not None
            self._building().at = self.state.seen_at(self.px, frame)
            self.phase, self.retries = "verify_open", 0
            return (
                self._open_click(frame),
                "open",
                f"panel says {self.SPEC.title} ({p:.2f}); open it",
            )
        self.phase = "find"
        return self._retry(f"panel doesn't say {self.SPEC.title} ({p:.2f})", actions.wait(0))

    def _open_click(self, frame) -> Action:
        assert self.px is not None
        target = self._to("", self.px, frame).target
        return actions.Action(
            f"open_{self.SPEC.kind}", "click", button="left", target=target, duration=0.1
        )

    def _verify_open(self, look, frame):
        c = look["window"]["answers"]["which"]
        p = c["probs"].get(f"{self.SPEC.kind}_window", 0.0)
        if p >= config.WINDOW_OPEN_MIN:
            self.retries, self.window_open = 0, True
            self.phase = self._after_open()
            # Off the window, so no tooltip covers the grid.
            return self._to("hover_off", NEUTRAL, frame), "opened", f"window open ({p:.2f})"
        if c["choice"] == "inventory" or c["choice"].endswith("_window"):
            # A stray E, or another building's window: close it, then click again.
            return self._retry(f"{c['choice']} is open", self._tap("close_window", "e"))
        return self._retry(f"window not open ({p:.2f})", self._open_click(frame))

    def _after_open(self) -> str:
        return "locate"

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
            self._to(f"hover_slot_{slot}", self._grid_centre(slot), frame),
            "locate",
            f"{self.item} box on slot {slot}{rest} ({a['box']['confidence'] or 0:.2f})",
        )

    def _confirm(self, look, frame):
        a = look["slot"]["answers"]
        p = a["item"]["probs"].get(self.item, 0.0)
        if p >= config.TOOLTIP_SAYS_MIN:
            assert self.slot is not None
            self.held = int(a["count"]["choice"]) if a["count"]["choice"].isdigit() else 0
            target = self._to("", self._grid_centre(self.slot), frame).target
            if SLOT[self.item] == "fuel":
                self.phase = "put"
                return (
                    actions.Action(f"pick_up_{self.item}", "click", (), "left", target, 0.1),
                    "pick",
                    f"slot {self.slot} is {self.held} {self.item} ({p:.2f}); pick it up",
                )
            self.phase = "verify_moved"
            return (
                actions.Action(f"move_{self.item}", "click", ("ctrl",), "left", target, 0.1),
                "move",
                f"slot {self.slot} is {self.held} {self.item} ({p:.2f}); ctrl+click it in",
            )
        why = f"slot {self.slot} says {a['item']['choice']}, {self.item} {p:.2f}"
        if self.candidates:
            self.slot = self.candidates.pop(0)
            return (
                self._to(f"hover_slot_{self.slot}", self._grid_centre(self.slot), frame),
                "next slot",
                f"{why}; try slot {self.slot}",
            )
        if self.state.inventory is not None:
            self.state.inventory[self.item] = 0
        return self._fail(f"{why}; no {self.item} in the inventory")

    # ---- fuel: a set amount from the cursor ----
    def _put(self, look, frame):
        n = min(self.held, config.FUEL_COUNT) or config.FUEL_COUNT
        x, y = self._slot("fuel")
        self.phase = "stow"
        return (
            actions.Action(
                f"put_{n}_{self.item}",
                "click",
                (),
                "right",
                (x / frame.width, y / frame.height),
                0.05,
                times=n,
            ),
            "put",
            f"right-click the fuel slot {n} times, one {self.item} each",
        )

    def _stow(self, look, frame):
        self.phase = "verify_moved"
        return self._tap("stow_cursor", "q"), "stow", "Q: the rest goes back into the inventory"

    # ---- the building's slot ----
    def _verify_moved(self, look, frame):
        name = SLOT[self.item]
        c = look[name]["answers"]["count"]
        empty, count = c["probs"].get("0", 0.0), c["choice"]
        if empty <= config.STONE_FURNACE_EMPTY_MAX:
            # Count what left the inventory, not the slot: a building starts burning (and a
            # furnace smelting) at once, so the slot already reads one less.
            cap = config.FUEL_COUNT if name == "fuel" else config.STONE_FURNACE_STACK
            moved = min(self.held, cap)
            self._building().put(self.item, moved)
            if self.state.inventory is not None:
                self.state.inventory[self.item] = self.held - moved
            self._moved(moved)
            self.phase, self.retries = "verify_closed", 0
            return (
                self._tap("close_window", "e"),
                "moved",
                f"{name} slot holds {count} ({1 - empty:.2f}); close",
            )
        # The click may not have taken. Box the item again (the inventory may have re-sorted).
        self.phase = "locate"
        return self._retry(
            f"{name} slot reads empty ({empty:.2f})", self._to("hover_off", NEUTRAL, frame)
        )

    def _moved(self, n: int) -> None:
        """Called once the item is in."""

    def _verify_closed(self, look, frame):
        c = look["window"]["answers"]["which"]
        p = c["probs"].get("nothing", 0.0)
        # "nothing" as the top answer is enough: with a drill and furnace in view it read only
        # 0.70-0.78 when closed (open windows read 0.99-1.00), and an E too many opens the
        # inventory.
        if c["choice"] == "nothing":
            self.window_open = False
            self.done = self.success = True
            return self._to("hover_off", NEUTRAL, frame), "closed", f"no window open ({p:.2f})"
        # E closes whichever window it is.
        why = f"{c['choice']} still open ({c['confidence'] or 0:.2f})"
        return self._retry(why, self._tap("close_window", "e"))

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
        # Q puts coal left on the cursor back (between pick and stow); harmless otherwise.
        return [self._tap("stow_cursor", "q")] if self.phase in ("put", "stow") else []
