"""Placing a building: take it out of the inventory and put it down near the player.
`place_stone_furnace` puts a furnace anywhere it fits; setting up mining puts a burner mining
drill on ore, then a stone furnace at the drill's output.

open, verify_open:     press E until Jev says the inventory is open.
locate, confirm:       Jev boxes the building's slot; its tooltip must name it (or the
                       neighbouring slot's, as in the inventory check).
pick:                  left-click the slot: the building goes onto the cursor.
close, verify_closed:  press E until the inventory is closed.
spot:                  the cursor hovers a spot a few tiles from the player. Factorio draws the
                       building there, green if it fits and red if not; Jev says which.
                       A drill also has to stand on its ore. Green: left-click. Otherwise the
                       next spot.
verify_placed:         the cursor is now over the placed building, so Factorio's info panel
                       should say its name (and, for a drill, its ore: logged).
"""

from collections.abc import Callable, Sequence

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
from .state import ITEM_NAMES, Building, GameState
from .targets import TARGETS

Spots = Sequence[tuple[float, float]]


class PlacePolicy:
    def __init__(
        self,
        state: GameState,
        item: str = "stone_furnace",
        spots: Spots | Callable[[], Spots] = config.PLACE_SPOTS,
        ore: str | None = None,
        site: str | None = None,
    ) -> None:
        """`spots`: tiles from the player to try, first fitting one wins (a callable is asked
        when the policy needs them: a furnace's spot depends on where its drill went). `ore`:
        the spot must be on it. `site`: recorded on the building (the ore of its drill)."""
        self.state = state
        self.item = item
        self.title = ITEM_NAMES[item].capitalize()
        self._spots = spots
        self.ore = TARGETS[ore] if ore else None
        self.site = site
        self.brain = Brain()
        self.phase = "open"
        self.slot: int | None = None
        self.neighbour: int | None = None
        self.tried_neighbour = False
        self.spot = 0  # index into self.spots
        self.retries = 0
        self.total_cost = 0.0
        self.done = False
        self.success = False

    @property
    def spots(self) -> Spots:
        if callable(self._spots):
            self._spots = self._spots()
        return self._spots

    def paused(self) -> None:
        # It may be on the cursor or back in the inventory; Q puts it back either way.
        self.phase, self.retries, self.spot = "open", 0, 0

    def _tap(self, name: str, key: str) -> Action:
        return actions.Action(name, "keys", (key,), duration=config.INVENTORY_TAP_SECONDS)

    def _to(self, name: str, xy: tuple[float, float], frame: Image.Image) -> Action:
        return actions.hover(name, (xy[0] / frame.width, xy[1] / frame.height))

    def _spot_px(self, frame: Image.Image) -> tuple[float, float]:
        dx, dy = self.spots[self.spot]
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
            jobs["locate"] = inventory_box_request(images["inventory"], self.item)
        elif phase == "confirm":
            assert self.slot is not None
            images["slot"] = slot_closeup(frame, *slot_centre(self.slot))
            jobs["slot"] = slot_request(images["slot"])
        elif phase == "spot":
            x, y = self._spot_px(frame)
            images["cursor"] = cursor_closeup(frame, round(x), round(y) + 60)
            jobs["preview"] = preview_request(images["cursor"], self.ore)
        elif phase == "verify_placed":
            images["panel"] = info_panel(frame)
            jobs["panel"] = panel_says_request(images["panel"], self.title, bool(self.ore))
        look: dict = self.brain.ask(jobs) if jobs else {"tokens": 0, "cost_usd": 0.0}
        self.total_cost += look["cost_usd"]
        handler = getattr(self, f"_{phase}")
        action, source, reason = handler(look, frame)
        info = {
            "objective": f"place_{self.item}",
            "phase": phase,
            "jev": look,
            "slot": self.slot,
            "spot_tiles": list(self.spots[self.spot]) if self.spot < len(self.spots) else None,
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
            return actions.wait(0), "opened", f"inventory open ({p:.2f}); find the {self.item}"
        return self._retry(f"inventory not open ({p:.2f})", self._tap("open_inventory", "e"))

    def _locate(self, look, frame):
        a = look["locate"]["answers"]
        slot, self.neighbour = slot_at(a["box"]["box"])
        self.tried_neighbour = False
        if slot is None:
            return self._fail(f"{self.item} box off the grid")
        self.slot, self.phase = slot, "confirm"
        conf = a["box"]["confidence"] or 0
        return (
            self._to(f"hover_slot_{slot}", slot_centre(slot), frame),
            "locate",
            f"{self.item} box on slot {slot} ({conf:.2f})",
        )

    def _confirm(self, look, frame):
        item = look["slot"]["answers"]["item"]
        p = item["probs"].get(self.item, 0.0)
        if p >= config.TOOLTIP_SAYS_MIN:
            assert self.slot is not None
            self.phase = "close"
            return (
                actions.Action(
                    f"pick_up_{self.item}",
                    "click",
                    button="left",
                    target=self._to("", slot_centre(self.slot), frame).target,
                    duration=0.1,
                ),
                "pick",
                f"slot {self.slot} is the {self.item} ({p:.2f}); pick it up",
            )
        why = f"slot {self.slot} says {item['choice']}, {self.item} {p:.2f}"
        if not self.tried_neighbour and self.neighbour is not None:
            self.slot, self.tried_neighbour = self.neighbour, True
            return (
                self._to(f"hover_slot_{self.slot}", slot_centre(self.slot), frame),
                "neighbour",
                f"{why}; try slot {self.slot}",
            )
        if self.state.inventory is not None:
            self.state.inventory[self.item] = 0
        return self._fail(f"{why}; no {self.item} in the inventory")

    def _close(self, look, frame):
        self.phase = "verify_closed"
        return self._tap("close_inventory", "e"), "close", f"press E ({self.item} on the cursor)"

    def _verify_closed(self, look, frame):
        p = look["open"]["answers"]["open"]["p"]
        if p < 1 - config.OPEN_MIN:
            if not self.spots:
                return self._fail("no spot to try (the drill's position is unknown)")
            self.phase, self.retries = "spot", 0
            return self._hover_spot(frame, f"inventory closed ({p:.2f})")
        return self._retry(f"inventory still open ({p:.2f})", self._tap("close_inventory", "e"))

    # ---- the ground ----
    def _hover_spot(self, frame, why: str):
        dx, dy = self.spots[self.spot]
        return (
            self._to(f"hover_spot_{dx:+g}_{dy:+g}", self._spot_px(frame), frame),
            "spot",
            f"{why}; try {dx:+g},{dy:+g} tiles from the player",
        )

    def _spot(self, look, frame):
        a = look["preview"]["answers"]
        c = a["preview"]
        green = c["probs"].get("green", 0.0)
        on_ore = a["on_ore"]["p"] if "on_ore" in a else 1.0
        dx, dy = self.spots[self.spot]
        # Green as the top answer is enough: next to a drill (its corner brackets and arrow
        # in the close-up) a green furnace read 0.72; red and empty previews read <= 0.02, and
        # the info panel checks the click anyway.
        if c["choice"] == "green" and on_ore >= config.ORE_UNDER_MIN:
            self.phase = "verify_placed"
            return (
                actions.Action(
                    f"place_{self.item}",
                    "click",
                    button="left",
                    target=self._to("", self._spot_px(frame), frame).target,
                    duration=0.1,
                ),
                "place",
                f"preview green ({green:.2f}), on ore {on_ore:.2f}, at {dx:+g},{dy:+g}; place",
            )
        if c["choice"] in ("none", "corners_only"):
            # Nothing on the cursor: the pick-up didn't take. Start over once.
            self.phase = "open"
            return self._retry(f"no {self.item} on the cursor ({c['choice']})", actions.wait(0))
        self.spot += 1
        why = f"preview {c['choice']} ({green:.2f} green, on ore {on_ore:.2f})"
        if self.spot >= len(self.spots):
            return self._fail(f"{why}; no spot left")
        return self._hover_spot(frame, why)

    def _verify_placed(self, look, frame):
        a = look["panel"]["answers"]
        p = a["says"]["p"]
        dx, dy = self.spots[self.spot]
        if p >= config.PANEL_SAYS_MIN:
            at = self.state.seen_at(self._spot_px(frame), frame)
            self.state.add(Building(self.item, at=at, site=self.site))
            inv = self.state.inventory
            if inv is not None:
                inv[self.item] = max(0, inv.get(self.item, 1) - 1)
            r = a.get("resources")
            ore = f", expected resources {r['choice']} ({r['confidence'] or 0:.2f})" if r else ""
            if r and self.ore and r["choice"] != self.ore.key:
                # Factorio's own word on what the drill will mine: not the ore it was for.
                return self._fail(f"drill placed but{ore}, not {self.ore.name}")
            self.done = self.success = True
            return (
                self._to("hover_off", NEUTRAL, frame),
                "placed",
                f"panel says {self.title} ({p:.2f}){ore} at {dx:+g},{dy:+g}",
            )
        return self._retry(f"panel doesn't say {self.title} ({p:.2f})", actions.wait(0))

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


def stone_furnace_at_drill(state: GameState, site: str) -> Callable[[], Spots]:
    """The spot of the furnace at the output of the drill on `site`, in tiles from the player:
    exact while the player hasn't moved since placing the drill (both snap to the same grid)."""

    def spots() -> Spots:
        drill = state.building("burner_mining_drill", site)
        if drill is None or drill.at is None:
            return []
        dx, dy = config.STONE_FURNACE_AT_DRILL
        px, py = state.player_at
        return [(drill.at[0] + dx - px, drill.at[1] + dy - py)]

    return spots
