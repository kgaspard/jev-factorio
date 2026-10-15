"""Checkpoint 2: walk to the nearest patch of a resource (iron ore, coal, ...), steered by Jev.

Far away: follow Jev's minimap direction choice, averaged over the last few ticks.
Target on screen (a couple of ticks in a row): walk towards the main-view box instead.
Stop once Jev says the player is standing on it (or the box is in reach) a few ticks in a row.
Blocked (a move didn't shift the view): Jev looks at a close-up and picks the way around.
"""

import math
from collections import deque

from PIL import Image

from . import actions, config
from .actions import Action
from .brain import DIRECTIONS, Brain, detour_request
from .capture import closeup, for_jev, minimap
from .geometry import angle_off, compass, direction_to, screen_offset_tiles
from .motion import moved_tiles, world_thumb
from .targets import Target


class WalkPolicy:
    def __init__(self, target: Target) -> None:
        self.target = target
        self.objective = f"Current objective: walk to the nearest {target.name} patch."
        self.brain = Brain()
        self.history: deque[dict[str, float]] = deque(maxlen=config.SMOOTH_TICKS)
        self.recent_moves: deque[str] = deque(maxlen=5)
        self.screen_streak = 0
        self.arrived_streak = 0
        self.total_cost = 0.0
        self.done = False
        # Blocked detection and detours
        self.prev_thumb = None
        self.last_move: str | None = None  # direction moved last tick, if it was a move
        self.last_was_detour = False
        self.heading: str | None = None  # where the player was going when it got blocked
        self.tried: list[str] = []  # detour steps that were blocked too

    def decide(self, frame: Image.Image, tick: int) -> tuple[Action, dict]:
        mini = minimap(frame)
        images = {"minimap": mini}

        # Did the last move actually move the player? The camera follows the player.
        thumb = world_thumb(frame)
        moved = None
        if self.prev_thumb is not None and self.last_move:
            moved = moved_tiles(self.prev_thumb, thumb)
        self.prev_thumb = thumb
        blocked = moved is not None and moved < config.STUCK_MOVED_TILES
        detour = region = None
        if blocked and self.last_move:
            if self.last_was_detour:
                self.tried.append(self.last_move)
            else:
                self.heading, self.tried = self.last_move, []
            images["closeup"], region = closeup(frame)
            assert self.heading is not None
            detour = detour_request(images["closeup"], self.target, self.heading, self.tried)
        elif moved is not None and not self.last_was_detour:
            self.tried = []  # walking freely again

        moves = ", ".join(self.recent_moves) or "none yet"
        look = self.brain.look(
            for_jev(frame),
            mini,
            f"{self.objective} Recent moves: {moves}.",
            self.target,
            detour=detour,
        )
        self.total_cost += look["cost_usd"]
        m, s = look["minimap"]["answers"], look["screen"]["answers"]

        # Minimap direction, averaged over the last few ticks (single calls are noisy).
        self.history.append(m["direction"]["probs"])
        smoothed = {
            label: sum(h.get(label, 0.0) for h in self.history) / len(self.history)
            for label in self.history[-1]
        }

        # Main view: where is the nearest target, in tiles from the player? Similar-looking
        # rocks fool it (grey rocks for iron), so the box must also roughly agree with the
        # minimap direction.
        box = s["box_screen"]
        left, top, right, bottom = box["box"]
        dx, dy = screen_offset_tiles((left + right) / 2, (top + bottom) / 2)
        box_dist = math.hypot(dx, dy)
        best = max(smoothed, key=lambda label: smoothed[label])
        agrees = best not in DIRECTIONS or angle_off(best, dx, dy) <= config.SCREEN_MAX_ANGLE_OFF
        screen_sure = (
            s["on_screen"]["p"] >= config.SCREEN_SEEN_MIN
            and (box["confidence"] or 0) >= config.SCREEN_BOX_MIN_CONFIDENCE
            and (agrees or box_dist <= config.REACH_TILES)
        )
        self.screen_streak = self.screen_streak + 1 if screen_sure else 0

        in_reach = screen_sure and box_dist <= config.REACH_TILES
        arrived = s["standing_on"]["p"] >= config.STANDING_MIN or in_reach
        self.arrived_streak = self.arrived_streak + 1 if arrived else 0

        action, source, reason = self._choose(
            smoothed, dx, dy, box_dist, m["box_minimap"], look.get("detour")
        )
        self.last_move = action.name.removeprefix("move_") if action.kind == "keys" else None
        self.last_was_detour = source == "detour"
        if self.last_move:
            self.recent_moves.append(self.last_move)

        obstacle_box = None
        if region and "detour" in look:
            # Close-up box -> fractions of the full frame, for drawing on the video.
            b = look["detour"]["answers"]["obstacle_box"]["box"]
            rl, rt, rr, rb = region
            obstacle_box = [
                rl + b[0] * (rr - rl), rt + b[1] * (rb - rt),
                rl + b[2] * (rr - rl), rt + b[3] * (rb - rt),
            ]  # fmt: skip

        info = {
            "objective": f"walk_to_{self.target.key}",
            "target": self.target.key,
            "target_name": self.target.name,
            "jev": look,
            "smoothed_direction": smoothed,
            "screen_box_tiles": [round(dx, 1), round(dy, 1)],
            "screen_agrees_with_minimap": agrees,
            "screen_streak": self.screen_streak,
            "arrived_streak": self.arrived_streak,
            "decision": {"source": source, "reason": reason},
            "moved_tiles": None if moved is None else round(moved, 2),
            "blocked": blocked,
            "heading": self.heading if blocked else None,
            "tried": list(self.tried) if blocked else [],
            "obstacle_box_frame": obstacle_box,
            "total_cost_usd": self.total_cost,
            "_images": images,
        }
        return action, info

    def _choose(
        self,
        smoothed: dict,
        dx: float,
        dy: float,
        box_dist: float,
        mini_box: dict,
        detour: dict | None,
    ):
        stride = config.MOVE_HOLD_SECONDS
        if self.arrived_streak >= config.ARRIVED_STREAK:
            self.done = True
            return (
                actions.wait(0),
                "arrived",
                f"on {self.target.name} {self.arrived_streak} ticks in a row",
            )
        if self.arrived_streak > 0:
            return (
                actions.wait(0),
                "confirming",
                f"looks like {self.target.name} is here "
                f"({self.arrived_streak}/{config.ARRIVED_STREAK})",
            )
        if detour:
            d = detour["answers"]["detour"]
            ranked = sorted(d["probs"].items(), key=lambda kv: -kv[1])
            return (
                actions.move(d["choice"], stride),
                "detour",
                f"blocked going {self.heading}; Jev: "
                + ", ".join(f"{k} {p:.2f}" for k, p in ranked),
            )
        if self.screen_streak >= config.SCREEN_STREAK:
            direction = compass(dx, dy)
            return (
                actions.move(direction, stride),
                "screen",
                f"{self.target.name} on screen {box_dist:.0f} tiles {direction}",
            )

        best = max(smoothed, key=lambda label: smoothed[label])
        if best in DIRECTIONS and smoothed[best] >= config.DIRECTION_MIN_PROB:
            return (
                actions.move(best, stride),
                "minimap",
                f"minimap says {best} ({smoothed[best]:.2f} over {len(self.history)} ticks)",
            )
        # "here" on the minimap still means up to about 10 tiles away. Near the patch the
        # minimap box (accurate at 1024 px) says which side it is on.
        if best == "here" and (mini_box["confidence"] or 0) >= config.MINIMAP_BOX_MIN_CONFIDENCE:
            left, top, right, bottom = mini_box["box"]
            toward = direction_to((left + right) / 2, (top + bottom) / 2, arrived_radius=0.01)
            if toward != "here":
                return (
                    actions.move(toward, stride),
                    "minimap box",
                    f"minimap says here ({smoothed[best]:.2f}); its box is {toward}",
                )
        if self.recent_moves:
            last = self.recent_moves[-1]
            return (
                actions.move(last, stride),
                "repeat",
                f"unsure (best {best} {smoothed[best]:.2f}), keep going {last}",
            )
        return actions.wait(0), "wait", f"unsure (best {best} {smoothed[best]:.2f})"

    def cleanup(self) -> list[Action]:
        self.brain.close()
        return []
