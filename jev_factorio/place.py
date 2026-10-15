"""Objective `place_stone_furnace`: take the stone furnace out of the inventory and put it down next
to the player.

open, verify_open:     press E until Jev says the inventory is open.
locate, confirm:       Jev boxes the furnace's slot; its tooltip must say "Stone furnace" (or the
                       neighbouring slot's, as in the inventory check).
pick:                  left-click the slot: the furnace goes onto the cursor.
close, verify_closed:  press E until the inventory is closed.
spot:                  the cursor hovers a spot a few tiles from the player. Factorio draws the
                       furnace there, green if it fits and red if not; Jev says which (O41).
                       Green: left-click. Otherwise the next spot.
verify_placed:         the cursor is now over the placed furnace, so Factorio's info panel
                       should say "Stone furnace".
"""

from PIL import Image

from . import actions, config
from .actions import Action
from .brain import (
    Brain,
    inventory_box_request,
    inventory_open_request,
    panel_says_request,
    preview_request,
    slot_request,
)
from .capture import cursor_closeup, info_panel, inventory_panel, slot_closeup
from .inventory import NEUTRAL, slot_at, slot_centre
from .state import Building, GameState

ITEM = "stone_furnace"


class PlaceStoneFurnacePolicy:
    def __init__(self, state: GameState) -> None:
        self.state = state
        self.brain = Brain()
        self.phase = "open"
        self.slot: int | None = None
        self.neighbour: int | None = None
        self.tried_neighbour = False
        self.spot = 0  # index into config.PLACE_SPOTS
        self.retries = 0
        self.total_cost = 0.0
        self.done = False
        self.success = False

    def paused(self) -> None:
        # The furnace may be on the cursor or back in the inventory; Q puts it back either way.
        self.phase, self.retries, self.spot = "open", 0, 0

    def _tap(self, name: str, key: str) -> Action:
        return actions.Action(name, "keys", (key,), duration=config.INVENTORY_TAP_SECONDS)

    def _to(self, name: str, xy: tuple[float, float], frame: Image.Image) -> Action:
        return actions.hover(name, (xy[0] / frame.width, xy[1] / frame.height))

    def _spot_px(self, frame: Image.Image) -> tuple[float, float]:
        dx, dy = config.PLACE_SPOTS[self.spot]
        return frame.width / 2 + dx * config.TILE_PX, frame.height / 2 + dy * config.TILE_PX

    def decide(self, frame: Image.Image, tick: int) -> tuple[Action, dict]:
        phase = self.phase
        images: dict[str, Image.Image] = {}
        jobs: dict = {}
        if phase in ("verify_open", "verify_closed"):
            images["inventory"] = inventory_panel(frame)
            jobs["open"] = inventory_open_request(images["inventory"])
        elif phase == "locate":
            images["inventory"] = inventory_panel(frame)
            jobs["locate"] = inventory_box_request(images["inventory"], ITEM)
        elif phase == "confirm":
            assert self.slot is not None
            images["slot"] = slot_closeup(frame, *slot_centre(self.slot))
            jobs["slot"] = slot_request(images["slot"])
        elif phase == "spot":
            x, y = self._spot_px(frame)
            images["cursor"] = cursor_closeup(frame, round(x), round(y) + 60)
            jobs["preview"] = preview_request(images["cursor"])
        elif phase == "verify_placed":
            images["panel"] = info_panel(frame)
            jobs["panel"] = panel_says_request(images["panel"], "Stone furnace")
        look: dict = self.brain.ask(jobs) if jobs else {"tokens": 0, "cost_usd": 0.0}
        self.total_cost += look["cost_usd"]
        handler = getattr(self, f"_{phase}")
        action, source, reason = handler(look, frame)
        info = {
            "objective": "place_stone_furnace",
            "phase": phase,
            "jev": look,
            "slot": self.slot,
            "spot_tiles": list(config.PLACE_SPOTS[self.spot])
            if self.spot < len(config.PLACE_SPOTS)
            else None,
            "decision": {"source": source, "reason": reason},
            "total_cost_usd": self.total_cost,
            "_images": images,
        }
        return action, info

    # ---- inventory ----
    def _open(self, look, frame):
        self.phase = "verify_open"
        return self._tap("open_inventory", "e"), "open", "press E"

    def _verify_open(self, look, frame):
        p = look["open"]["answers"]["open"]["p"]
        if p >= config.OPEN_MIN:
            self.phase, self.retries = "locate", 0
            return actions.wait(0), "opened", f"inventory open ({p:.2f}); find the furnace"
        return self._retry(f"inventory not open ({p:.2f})", self._tap("open_inventory", "e"))

    def _locate(self, look, frame):
        a = look["locate"]["answers"]
        slot, self.neighbour = slot_at(a["box"]["box"])
        self.tried_neighbour = False
        if slot is None:
            return self._fail("furnace box off the grid")
        self.slot, self.phase = slot, "confirm"
        conf = a["box"]["confidence"] or 0
        return (
            self._to(f"hover_slot_{slot}", slot_centre(slot), frame),
            "locate",
            f"furnace box on slot {slot} ({conf:.2f})",
        )

    def _confirm(self, look, frame):
        item = look["slot"]["answers"]["item"]
        p = item["probs"].get(ITEM, 0.0)
        if p >= config.TOOLTIP_SAYS_MIN:
            assert self.slot is not None
            self.phase = "close"
            return (
                actions.Action(
                    "pick_up_stone_furnace",
                    "click",
                    button="left",
                    target=self._to("", slot_centre(self.slot), frame).target,
                    duration=0.1,
                ),
                "pick",
                f"slot {self.slot} is the stone furnace ({p:.2f}); pick it up",
            )
        why = f"slot {self.slot} says {item['choice']}, furnace {p:.2f}"
        if not self.tried_neighbour and self.neighbour is not None:
            self.slot, self.tried_neighbour = self.neighbour, True
            return (
                self._to(f"hover_slot_{self.slot}", slot_centre(self.slot), frame),
                "neighbour",
                f"{why}; try slot {self.slot}",
            )
        if self.state.inventory is not None:
            self.state.inventory[ITEM] = 0
        return self._fail(f"{why}; no stone furnace in the inventory")

    def _close(self, look, frame):
        self.phase = "verify_closed"
        return self._tap("close_inventory", "e"), "close", "press E (furnace on the cursor)"

    def _verify_closed(self, look, frame):
        p = look["open"]["answers"]["open"]["p"]
        if p < 1 - config.OPEN_MIN:
            self.phase, self.retries = "spot", 0
            return self._hover_spot(frame, f"inventory closed ({p:.2f})")
        return self._retry(f"inventory still open ({p:.2f})", self._tap("close_inventory", "e"))

    # ---- the ground ----
    def _hover_spot(self, frame, why: str):
        dx, dy = config.PLACE_SPOTS[self.spot]
        return (
            self._to(f"hover_spot_{dx:+g}_{dy:+g}", self._spot_px(frame), frame),
            "spot",
            f"{why}; try {dx:+g},{dy:+g} tiles from the player",
        )

    def _spot(self, look, frame):
        c = look["preview"]["answers"]["preview"]
        green = c["probs"].get("green", 0.0)
        dx, dy = config.PLACE_SPOTS[self.spot]
        if green >= config.PREVIEW_GREEN_MIN:
            self.phase = "verify_placed"
            return (
                actions.Action(
                    "place_stone_furnace",
                    "click",
                    button="left",
                    target=self._to("", self._spot_px(frame), frame).target,
                    duration=0.1,
                ),
                "place",
                f"preview green ({green:.2f}) at {dx:+g},{dy:+g}; place",
            )
        if c["choice"] in ("none", "corners_only"):
            # Nothing on the cursor: the pick-up didn't take. Start over once.
            self.phase = "open"
            return self._retry(f"no furnace on the cursor ({c['choice']})", actions.wait(0))
        self.spot += 1
        if self.spot >= len(config.PLACE_SPOTS):
            return self._fail(f"preview {c['choice']} at every spot")
        return self._hover_spot(frame, f"preview {c['choice']} ({green:.2f} green)")

    def _verify_placed(self, look, frame):
        p = look["panel"]["answers"]["says"]["p"]
        dx, dy = config.PLACE_SPOTS[self.spot]
        if p >= config.PANEL_SAYS_MIN:
            self.done = self.success = True
            at = self.state.seen_at(self._spot_px(frame), frame)
            self.state.add(Building(ITEM, at=at))
            if self.state.inventory is not None:
                self.state.inventory[ITEM] = max(0, self.state.inventory.get(ITEM, 1) - 1)
            return (
                self._to("hover_off", NEUTRAL, frame),
                "placed",
                f"panel says stone furnace ({p:.2f}) at {dx:+g},{dy:+g}",
            )
        return self._retry(f"panel doesn't say stone furnace ({p:.2f})", actions.wait(0))

    # ---- shared ----
    def _retry(self, why: str, action: Action):
        self.retries += 1
        if self.retries > config.INVENTORY_RETRIES:
            return self._fail(f"{why}; {self.retries - 1} retries")
        return action, "retry", f"{why} (retry {self.retries}/{config.INVENTORY_RETRIES})"

    def _fail(self, why: str):
        self.done = True
        return self._tap("clear_cursor", "q"), "give up", why

    def cleanup(self) -> list[Action]:
        self.brain.close()
        # Q puts anything on the cursor back into the inventory; harmless otherwise.
        return [self._tap("clear_cursor", "q")] if not self.success else []
