"""What Jev is asked each tick, and the two requests (minimap, main view) sent in parallel.
Answers come back as plain dicts so they can go straight into decisions.jsonl."""

import time
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
from typesafe_sdk import Box, Choice
from typesafe_sdk import Image as JevImage
from typesafe_sdk import Noul

from . import config
from .geometry import turn
from .jev import make_client
from .targets import GROUND_LEGEND, MINIMAP_LEGEND, Target

DIRECTIONS = ["up", "down", "left", "right", "up_left", "up_right", "down_left", "down_right"]

GAME_CONTEXT = (
    "You are helping a player of the video game Factorio (version 2.0, top-down view). "
    "Up is north. The player's character is always at the centre of the image."
)

MINIMAP_CONTEXT = (
    "This is the minimap, centred on the player, who is marked with a red cross. " + MINIMAP_LEGEND
)
SCREEN_CONTEXT = "This is the main game view. " + GROUND_LEGEND


def minimap_questions(target: Target) -> dict:
    return {
        "on_minimap": Noul(instructions=f"Is a {target.name} patch visible on the map?"),
        "box_minimap": Box(
            instructions=f"The {target.minimap_colour} checkered {target.name} patch nearest "
            "the red cross (the player)"
        ),
        "direction": Choice(
            instructions="Which direction from the red cross (the player) is the nearest "
            f"{target.name} patch?",
            criteria={
                **{d: None for d in DIRECTIONS},
                "here": "Under the red cross",
                "not_visible": f"No {target.name} on the map",
            },
        ),
    }


def screen_questions(target: Target) -> dict:
    return {
        "on_screen": Noul(instructions=f"Is {target.name} visible in the screenshot?"),
        "box_screen": Box(instructions=f"The {target.name} nearest the player in the screenshot"),
        "standing_on": Noul(
            instructions="Is the player's character, at the centre of the screenshot, standing "
            f"on or right next to {target.name}?"
        ),
    }


CLOSEUP_CONTEXT = (
    "This is a close-up of the area around the player's character, who is at the centre. "
    "Trees, rocks, cliffs, water, buildings and the crashed spaceship block walking; ground, "
    "grass, small plants and ore do not."
)


def detour_options(heading: str) -> dict[str, str]:
    """The ways around an obstacle when walking `heading` is blocked: either side, or back."""
    left, right, back = turn(heading, -2), turn(heading, 2), turn(heading, 4)
    return {
        left: f"Step {left.replace('_', '-')}, to pass the obstacle on that side",
        right: f"Step {right.replace('_', '-')}, to pass the obstacle on that side",
        back: f"Step back {back.replace('_', '-')}, away from the obstacle",
    }


def detour_request(
    closeup: Image.Image, target: Target, heading: str, tried: list[str]
) -> tuple[list, dict]:
    way = heading.replace("_", "-")
    situation = (
        f"The player is walking {way} towards {target.name}, but the last move "
        "did not move the player at all, so something is in the way."
    )
    if tried:
        situation += f" Already tried stepping {', '.join(tried)}: also blocked."
    questions = {
        "obstacle_visible": Noul(
            instructions=f"Is there an obstacle right next to the player on the {way} side?"
        ),
        "obstacle_box": Box(instructions=f"The obstacle blocking the player from walking {way}"),
        "detour": Choice(
            instructions="Which way should the player step to get around the obstacle?",
            criteria=detour_options(heading),
        ),
    }
    return [GAME_CONTEXT, CLOSEUP_CONTEXT, situation, JevImage.from_pil(closeup)], questions


# ---- Mining (CP3). These read Factorio's own text and bar, not rock colours (O28). ----
AIM_CONTEXT = (
    "This is a close-up of the area around the player's character, who is at the centre. "
    + GROUND_LEGEND
)
PANEL_CONTEXT = (
    "This is the right-hand side panel of the game's interface. When the mouse cursor hovers "
    "over something in the world, an info panel appears here with its name in the title bar."
)
BAR_CONTEXT = (
    "This is a strip of the game's interface just above the quickbar. While the player mines "
    "by hand, an orange progress bar appears here and fills up as each item is mined."
)
TEXT_CONTEXT = (
    "This is a close-up around the mouse cursor while the player mines by hand. Each time an "
    "item is mined, a floating text like '+1 Coal (5)' rises from the cursor; the number in "
    "brackets is how many the player now has in total."
)
CORNERS_CONTEXT = (
    "This is a close-up around the mouse cursor. When the cursor hovers over something, four "
    "corner brackets are drawn around it: yellow if the player can reach it, red if it is too "
    "far away."
)
ITEM_TITLES = {"coal": "Coal", "iron_ore": "Iron ore", "copper_ore": "Copper ore", "stone": "Stone"}


def aim_request(closeup: Image.Image, target: Target) -> tuple[list, dict]:
    """Which side of the character to mine on. A box on "the nearest rock" landed on the
    character itself whatever the wording, so ask for a side and let the info panel confirm."""
    return [GAME_CONTEXT, AIM_CONTEXT, JevImage.from_pil(closeup)], {
        "side": Choice(
            instructions="In which direction from the player's character, within about two "
            f"tiles, is there {target.name}?",
            criteria={
                **{d: None for d in DIRECTIONS},
                "none": f"No {target.name} within about two tiles",
            },
        ),
    }


def panel_request(panel: Image.Image, target: Target) -> tuple[list, dict]:
    title = ITEM_TITLES[target.key]
    return [GAME_CONTEXT, PANEL_CONTEXT, JevImage.from_pil(panel)], {
        "panel_shown": Noul(instructions="Is an info panel for a hovered object shown?"),
        "says_target": Noul(instructions=f"Does the info panel's title say '{title}'?"),
    }


def corners_request(cursor: Image.Image) -> tuple[list, dict]:
    """Factorio's own reach check: the selection corners are red when it is too far."""
    return [GAME_CONTEXT, CORNERS_CONTEXT, JevImage.from_pil(cursor)], {
        "corners": Choice(
            instructions="What colour are the four corner brackets around the hovered object?",
            criteria={
                "yellow": "Yellow: in reach",
                "red": "Red: out of reach",
                "none": "No corner brackets",
            },
        ),
    }


def count_options(max_count: int) -> dict[str, str | None]:
    return {
        **{str(n): None for n in range(1, max_count + 1)},
        "more": f"A number larger than {max_count}",
        "none": "No floating text",
    }


def mining_requests(bar: Image.Image, text: Image.Image, max_count: int) -> dict:
    return {
        "bar": (
            [GAME_CONTEXT, BAR_CONTEXT, JevImage.from_pil(bar)],
            {
                "mining": Noul(
                    instructions="Is an orange progress bar shown, at least partly filled?"
                )
            },
        ),
        "text": (
            [GAME_CONTEXT, TEXT_CONTEXT, JevImage.from_pil(text)],
            {
                "text_shown": Noul(
                    instructions="Is a floating '+1 <item> (<number>)' text visible?"
                ),
                "item": Choice(
                    instructions="Which item does the floating text name?",
                    criteria={
                        **{k: f"'{v}'" for k, v in ITEM_TITLES.items()},
                        "none": "No floating text",
                    },
                ),
                "count": Choice(
                    instructions="What number is in brackets in the floating text?",
                    criteria=count_options(max_count),
                ),
            },
        ),
    }


def _plain(answer) -> dict:
    if answer.type == "noul":
        return {"type": "noul", "p": answer.noul}
    if answer.type == "choice":
        return {
            "type": "choice",
            "choice": answer.choice,
            "confidence": answer.confidence,
            "probs": dict(answer.probabilities),
        }
    if answer.type == "box":
        b = answer.box
        return {
            "type": "box",
            "box": [b.left, b.top, b.right, b.bottom],
            "confidence": answer.confidence,
        }
    raise ValueError(f"unexpected answer type {answer.type!r}")


class Brain:
    def __init__(self):
        self._client = make_client()  # httpx client underneath, safe to share across threads
        self._pool = ThreadPoolExecutor(max_workers=3)

    def _ask(self, state: list, questions: dict) -> dict:
        t0 = time.perf_counter()
        resp = self._client.system_one(state=state, questions=questions)
        tokens = resp.usage.input_tokens or 0
        return {
            "ms": round((time.perf_counter() - t0) * 1000),
            "tokens": tokens,
            "answers": {k: _plain(a) for k, a in resp.answers.items()},
        }

    def look(
        self,
        screenshot: Image.Image,
        minimap: Image.Image,
        objective: str,
        target: Target,
        detour: tuple[list, dict] | None = None,
    ) -> dict:
        """Ask about the minimap and the main view at the same time, plus the detour question
        when the player is blocked. Returns {"minimap", "screen", ["detour"], "tokens",
        "cost_usd"}."""
        jobs = {
            "minimap": (
                [GAME_CONTEXT, MINIMAP_CONTEXT, objective, JevImage.from_pil(minimap)],
                minimap_questions(target),
            ),
            "screen": (
                [GAME_CONTEXT, SCREEN_CONTEXT, objective, JevImage.from_pil(screenshot)],
                screen_questions(target),
            ),
        }
        if detour:
            jobs["detour"] = detour
        return self.ask(jobs)

    def ask(self, jobs: dict[str, tuple[list, dict]]) -> dict:
        """Send several (state, questions) requests at the same time. Returns each one's
        result by name, plus the total "tokens" and "cost_usd"."""
        futures = {name: self._pool.submit(self._ask, *job) for name, job in jobs.items()}
        result = {name: f.result() for name, f in futures.items()}
        tokens = sum(r["tokens"] for r in result.values())
        return {**result, "tokens": tokens, "cost_usd": tokens * config.JEV_PRICE_PER_INPUT_TOKEN}

    def close(self):
        self._pool.shutdown()
        self._client.close()
