"""Checkpoint 3: mine a resource by hand until the inventory holds `goal` of it.

aim:    Jev says on which side of the player, within about two tiles, the target is (a box on
        "the nearest rock" kept landing on the character). The cursor goes 1.5 tiles out on
        the likeliest side. None nearby: step towards the likeliest side.
verify: hovering opens Factorio's info panel and draws corner brackets round the hovered
        tile, yellow if in reach and red if not. Jev reads the title and the colour. Right
        name and yellow: hold right-click. Otherwise: hover the next likeliest side, then
        ask again.
mining: keep right-click held. Each tick Jev checks the mining progress bar and reads the
        "+1 Coal (N)" floating text, where N is the total in the inventory (O28). No bar for a
        couple of ticks: release and aim again. N >= goal: release, done.
Everything is read from the screen; the walk policy (CP2) is expected to have brought the
player onto the patch.
"""

from PIL import Image

from . import actions, config
from .actions import Action
from .brain import Brain, aim_request, corners_request, mining_requests, panel_request
from .capture import closeup, cursor_closeup, info_panel, progress_bar
from .targets import Target

TILE_PX = 32  # main view at default zoom
# Unit steps on screen (y down) for each side.
_STEP = {
    "up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0),
    "up_left": (-0.7071, -0.7071), "up_right": (0.7071, -0.7071),
    "down_left": (-0.7071, 0.7071), "down_right": (0.7071, 0.7071),
}  # fmt: skip


def side_point(side: str, width: int, height: int) -> tuple[float, float]:
    """Where to hover for `side`, as fractions of the game area."""
    ux, uy = _STEP[side]
    dist = config.AIM_UP_TILES if side == "up" else config.AIM_TILES
    return 0.5 + ux * dist * TILE_PX / width, 0.5 + uy * dist * TILE_PX / height


class MinePolicy:
    def __init__(self, target: Target, goal: int) -> None:
        self.target = target
        self.goal = goal
        self.max_count = goal + 10  # count choices offered to Jev; above that is "more"
        self.brain = Brain()
        self.state = "aim"
        self.aim: tuple[float, float] | None = None  # cursor, as fractions of the game area
        self.side: str | None = None  # the side being tried
        self.sides: list[str] = []  # sides still to try, likeliest first
        self.failed_aims = 0
        self.no_bar = 0
        self.count: int | None = None  # last accepted reading of N
        self.total_cost = 0.0
        self.done = False
        self.success = False

    def paused(self) -> None:
        """Called by the loop when Factorio lost focus; the loop has released the mouse and
        the cursor may have moved, so start over from aiming."""
        self.state = "aim"

    def decide(self, frame: Image.Image, tick: int) -> tuple[Action, dict]:
        state = self.state
        images: dict[str, Image.Image] = {}
        jobs: dict = {}
        region = None
        if state == "aim":
            images["closeup"], region = closeup(frame)
            jobs["aim"] = aim_request(images["closeup"], self.target)
        elif state == "verify":
            assert self.aim is not None
            x, y = round(self.aim[0] * frame.width), round(self.aim[1] * frame.height)
            images["panel"] = info_panel(frame)
            images["cursor"] = cursor_closeup(frame, x, y)
            jobs["panel"] = panel_request(images["panel"], self.target)
            jobs["corners"] = corners_request(images["cursor"])
        else:  # mining
            assert self.aim is not None
            x, y = round(self.aim[0] * frame.width), round(self.aim[1] * frame.height)
            images["panel"] = info_panel(frame)
            images["bar"] = progress_bar(frame)
            images["text"] = cursor_closeup(frame, x, y)
            jobs["panel"] = panel_request(images["panel"], self.target)
            jobs.update(mining_requests(images["bar"], images["text"], self.max_count))

        look = self.brain.ask(jobs)
        self.total_cost += look["cost_usd"]
        reading = None
        if state == "aim":
            action, source, reason = self._aim(look["aim"]["answers"], frame)
        elif state == "verify":
            action, source, reason = self._verify(
                look["panel"]["answers"], look["corners"]["answers"]["corners"], frame
            )
        else:
            reading = self._read_count(look["text"]["answers"])
            action, source, reason = self._mine(look, reading)

        info = {
            "objective": f"mine_{self.target.key}",
            "target": self.target.key,
            "target_name": self.target.name,
            "goal": self.goal,
            "state": state,
            "jev": look,
            "aim": self.aim,
            "side": self.side,
            "sides_left": list(self.sides),
            "closeup_region": region,
            "count": self.count,
            "count_reading": reading,
            "failed_aims": self.failed_aims,
            "no_bar": self.no_bar,
            "decision": {"source": source, "reason": reason},
            "total_cost_usd": self.total_cost,
            "_images": images,
        }
        return action, info

    def _aim(self, a: dict, frame: Image.Image):
        probs = a["side"]["probs"]
        ranked = sorted((d for d in _STEP), key=lambda d: -probs.get(d, 0.0))
        if probs.get("none", 0.0) >= config.AIM_NONE_MIN:
            best = ranked[0]
            return (
                actions.move(best, config.MOVE_HOLD_SECONDS),
                "approach",
                f"no {self.target.name} within 2 tiles ({probs['none']:.2f}); step {best}",
            )
        self.sides = [d for d in ranked if probs.get(d, 0.0) >= config.AIM_SIDE_MIN]
        self.sides = self.sides[: config.AIM_MAX_SIDES] or ranked[:1]
        odds = ", ".join(f"{d} {probs.get(d, 0.0):.2f}" for d in self.sides)
        return self._hover_next(frame, "aim", f"Jev: {odds}")

    def _hover_next(self, frame: Image.Image, source: str, why: str):
        self.side = self.sides.pop(0)
        self.aim = side_point(self.side, frame.width, frame.height)
        self.state = "verify"
        return actions.hover(f"hover_{self.side}", self.aim), source, f"{why}; hover {self.side}"

    def _verify(self, a: dict, corners: dict, frame: Image.Image):
        says = a["says_target"]["p"]
        yellow = corners["probs"].get("yellow", 0.0)
        if says >= config.PANEL_SAYS_MIN and yellow >= config.CORNERS_YELLOW_MIN:
            assert self.aim is not None
            self.state, self.no_bar, self.failed_aims = "mining", 0, 0
            return (
                actions.press("start_mining", "right", self.aim),
                "verified",
                f"panel says {self.target.name} ({says:.2f}), corners yellow ({yellow:.2f}), "
                "hold right-click",
            )
        if says < config.PANEL_SAYS_MIN:
            why = (
                f"{self.side}: panel doesn't say {self.target.name} "
                f"({says:.2f}, panel shown {a['panel_shown']['p']:.2f})"
            )
        else:
            why = f"{self.side}: {self.target.name} but corners {corners['choice']}, out of reach"
        if self.sides:
            return self._hover_next(frame, "next side", why)
        self.state = "aim"
        return self._failed(why)

    def _read_count(self, a: dict) -> int | None:
        """N from '+1 <item> (N)', or None if it isn't readable this tick."""
        count = a["count"]
        if (
            a["text_shown"]["p"] < 0.7
            or a["item"]["choice"] != self.target.key
            or (count["confidence"] or 0) < config.COUNT_MIN_CONFIDENCE
            or count["choice"] == "none"
        ):
            return None
        return self.max_count + 1 if count["choice"] == "more" else int(count["choice"])

    def _mine(self, look: dict, reading: int | None):
        if reading is not None:
            # Older floating texts can still be on screen, so never count down.
            self.count = max(self.count or 0, reading)
        bar = look["bar"]["answers"]["mining"]["p"]
        says = look["panel"]["answers"]["says_target"]["p"]
        have = "?" if self.count is None else self.count
        if self.count is not None and self.count >= self.goal:
            self.done = self.success = True
            self.state = "aim"
            return (
                actions.release("stop_mining", "right"),
                "done",
                f"have {have} {self.target.name}, goal {self.goal}",
            )
        self.no_bar = 0 if bar >= config.MINING_BAR_MIN else self.no_bar + 1
        if self.no_bar >= config.NO_BAR_TICKS:
            self.state = "aim"
            return (
                actions.release("stop_mining", "right"),
                "no bar",
                f"no mining bar {self.no_bar} ticks (bar {bar:.2f}, panel {says:.2f}), re-aim",
            )
        return (
            actions.wait(0),
            "mining",
            f"bar {bar:.2f}, have {have}/{self.goal}"
            + ("" if reading is None else f" (read {reading})"),
        )

    def _failed(self, why: str):
        self.failed_aims += 1
        if self.failed_aims >= config.MAX_AIMS:
            self.done = True
            return actions.wait(0), "give up", f"{why}; {self.failed_aims} failed aims"
        return actions.wait(0), "retry", f"{why} ({self.failed_aims}/{config.MAX_AIMS})"

    def cleanup(self) -> list[Action]:
        self.brain.close()
        return [actions.release("stop_mining", "right")]
