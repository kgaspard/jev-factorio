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
from .state import ICONS, ITEM_NAMES
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


# ---- Mining (CP3). These read Factorio's own text and bar, not rock colours. ----
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


ORES = ("iron_ore", "copper_ore", "coal", "stone")


def panel_says_request(
    panel: Image.Image, title: str, resources: bool = False
) -> tuple[list, dict]:
    """Does the hovered-entity info panel's title say `title`? With `resources`: which ore a
    drill's "Expected resources:" line shows. It is an icon, not text: asking whether the
    panel mentions 'Iron ore' read 0.02 on a drill on iron."""
    questions: dict = {"says": Noul(instructions=f"Does the info panel's title say '{title}'?")}
    if resources:
        questions["resources"] = Choice(
            instructions="Which item icon follows 'Expected resources:'?",
            criteria={
                **{k: f"{ITEM_NAMES[k].capitalize()}: {ICONS[k]}" for k in ORES},
                "none": "No 'Expected resources' line, or no icon after it",
            },
        )
    return [GAME_CONTEXT, PANEL_CONTEXT, JevImage.from_pil(panel)], questions


PREVIEW_CONTEXT = (
    "This is a close-up around the mouse cursor. While the player holds a building on the "
    "cursor, a preview of it is drawn there: green if it can be placed, red if something is "
    "in the way."
)


def preview_request(cursor: Image.Image, ore: Target | None = None) -> tuple[list, dict]:
    """Factorio's own placement check. "corners_only" keeps red out-of-reach selection
    corners from reading as a red building. With `ore`: is the preview on that ore (a
    drill only mines what is under it)?"""
    context: list = [GAME_CONTEXT, PREVIEW_CONTEXT]
    questions = {}
    if ore is not None:
        context.append(GROUND_LEGEND)
        questions["on_ore"] = Noul(
            instructions=f"Is the ground under the building preview covered with {ore.name} "
            f"({ore.ground_colour} rocks)?"
        )
    return [*context, JevImage.from_pil(cursor)], {
        **questions,
        "preview": Choice(
            instructions="What colour is the building preview at the cursor?",
            criteria={
                "green": "Green: can be placed",
                "red": "Red: blocked",
                "corners_only": "Only four small corner brackets around a tile, no building",
                "none": "No building preview at the cursor",
            },
        ),
    }


BUILDING_LOOKS = {
    "stone_furnace": "a small square building of grey stone blocks with yellow sides, about "
    "two tiles wide. An unfuelled one shows a red triangle warning icon with a fuel pump on it",
    "burner_mining_drill": "a dark grey square machine about two tiles wide with a drill head "
    "and a small chimney. An unfuelled one shows a red triangle warning icon with a fuel pump "
    "on it",
}
WINDOW_CONTEXT = (
    "This is the middle of the game screen. Clicking a building opens its window here: the "
    "character's inventory on the left, the building's slots on the right."
)
STONE_FURNACE_SIDE_CONTEXT = (
    "This is the right half of an open stone furnace window, with a status line at the top "
    "next to a coloured dot."
)
STONE_FURNACE_SLOT_CONTEXT = (
    "This is a close-up of one item slot in a Factorio building window. An empty slot is a "
    "plain dark square (a fuel slot shows a faint fuel pump outline). A slot holding items "
    "shows the item's icon with its count in the bottom-right corner."
)
STONE_FURNACE_STATUS = {
    "no_fuel": "'No fuel'",
    "working": "'Working'",
    "no_ingredients": "'No ingredients' or 'No input'",
    "output_full": "'Output full'",
    "other": "Something else",
}
SLOT_COUNTS = {"0": "Empty", **{str(n): None for n in range(1, 101)}}


def building_box_request(view: Image.Image, kind: str) -> tuple[list, dict]:
    """Where is the building? The Noul reads low even when the box is right; the info
    panel decides."""
    return [GAME_CONTEXT, "This is the main game view.", JevImage.from_pil(view)], {
        "box": Box(instructions=f"The {ITEM_NAMES[kind]}. It looks like {BUILDING_LOOKS[kind]}."),
    }


WINDOWS = {
    "stone_furnace_window": "A window titled 'Stone furnace'",
    "burner_mining_drill_window": "A window titled 'Burner mining drill'",
    "inventory": "A window titled 'Character' next to one titled 'Crafting'",
    "nothing": "No window: only the game world (buildings standing on the ground don't count)",
}


def window_request(window: Image.Image) -> tuple[list, dict]:
    """Which window is open. A yes/no "is a furnace window open?" read 0.44-0.70 on a closed
    day view with the furnace on the ground in the crop, and 0.51-0.56 on the open inventory;
    this Choice read the right answer at 0.92-1.00 on all of them."""
    return [GAME_CONTEXT, WINDOW_CONTEXT, JevImage.from_pil(window)], {
        "which": Choice(
            instructions="Which window is open in the middle of the screen?", criteria=WINDOWS
        ),
    }


def stone_furnace_status_request(side: Image.Image) -> tuple[list, dict]:
    return [GAME_CONTEXT, STONE_FURNACE_SIDE_CONTEXT, JevImage.from_pil(side)], {
        "status": Choice(
            instructions="What does the status line say?", criteria=STONE_FURNACE_STATUS
        ),
    }


def stone_furnace_panel_request(panel: Image.Image) -> tuple[list, dict]:
    """The hover info panel of a furnace: its status line and lifetime product count."""
    return [GAME_CONTEXT, PANEL_CONTEXT, JevImage.from_pil(panel)], {
        "status": Choice(
            instructions="What does the status line (next to the coloured dot) say?",
            criteria=STONE_FURNACE_STATUS,
        ),
        "finished": Choice(
            instructions="What number follows 'Products finished:'?",
            criteria={
                **{str(n): None for n in range(0, 101)},
                "none": "No 'Products finished' line",
            },
        ),
    }


def building_slot_request(slot: Image.Image, kinds: list[str] | None = None) -> tuple[list, dict]:
    """The count, and with `kinds` which of those items it is. Mostly the slot decides the kind
    (fuel or ore; naming the coal icon was unsure, 0.52-0.57, while the count read 1.00), but
    the two sites' furnaces look the same: only their plates tell them apart."""
    questions: dict = {
        "count": Choice(instructions="What number is on the item icon?", criteria=SLOT_COUNTS),
    }
    if kinds:
        questions["item"] = Choice(
            instructions="Which item is in the slot?",
            criteria={
                **{k: f"{ITEM_NAMES[k].capitalize()}: {ICONS[k]}" for k in kinds},
                "none": "The slot is empty",
            },
        )
    return [GAME_CONTEXT, STONE_FURNACE_SLOT_CONTEXT, JevImage.from_pil(slot)], questions


CRAFT_CONTEXT = (
    "This is the crafting panel. Four tabs at the top pick a recipe group; below them is a "
    "grid of recipe icons. A number on a recipe icon is how many the player can craft now. Red "
    "recipes can't be crafted by hand."
)
CRAFT_TABS = {
    "logistics": "'Logistics'",
    "production": "'Production'",
    "intermediate_products": "'Intermediate products'",
    "combat": "'Combat'",
}
TIP_CONTEXT = (
    "This is a close-up of the crafting panel around the mouse cursor, which hovers the {} at "
    "the top-left; its tooltip appears below and to the right."
)


def crafting_box_request(panel: Image.Image, what: str) -> tuple[list, dict]:
    return [GAME_CONTEXT, CRAFT_CONTEXT, JevImage.from_pil(panel)], {
        "box": Box(instructions=what),
    }


def tab_request(closeup: Image.Image) -> tuple[list, dict]:
    return [GAME_CONTEXT, TIP_CONTEXT.format("tab"), JevImage.from_pil(closeup)], {
        "tab": Choice(
            instructions="What does the tooltip say?",
            criteria={**CRAFT_TABS, "none": "No tooltip"},
        ),
    }


def recipe_request(closeup: Image.Image, recipes: list[str]) -> tuple[list, dict]:
    """The hovered recipe's tooltip title, and the number on its icon (how many can be
    crafted now)."""
    return [GAME_CONTEXT, TIP_CONTEXT.format("recipe icon"), JevImage.from_pil(closeup)], {
        "recipe": Choice(
            instructions="What name is in the tooltip's title bar?",
            criteria={
                **{r: f"'{ITEM_NAMES[r].capitalize()} (Recipe)'" for r in recipes},
                "other": "Another name",
                "none": "No tooltip",
            },
        ),
        "craftable": Choice(
            instructions="What number is on the hovered recipe icon?",
            criteria={"0": "No number", **{str(n): None for n in range(1, 101)}},
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


# ---- Inventory check. Item names come from hover tooltips, not icons. ----
INVENTORY_CONTEXT = (
    "This is the middle of the game screen. When the character inventory is open, a window "
    "titled 'Character' shows here with a grid of item slots."
)
SLOT_CONTEXT = (
    "This is a close-up of the open character inventory. The mouse cursor hovers over the "
    "inventory slot at the top-left of the image. If the slot holds an item, its icon shows "
    "the number of that item in its bottom-right corner, and a tooltip with the item's name "
    "in its title bar appears next to it."
)
SLOT_TITLES = {k: v[0].upper() + v[1:] for k, v in ITEM_NAMES.items()}


INVENTORY_BOX_CONTEXT = (
    "This is the open character inventory: a grid of item slots, 10 per row. Each slot shows "
    "an item's icon with the number of that item in the bottom-right corner. Item icons: "
    + "; ".join(f"{ITEM_NAMES[k]} is {d}" for k, d in ICONS.items())
    + "."
)


def inventory_box_request(panel: Image.Image, item: str) -> tuple[list, dict]:
    """Where is `item`? Paired with a Noul for the panel, but neither is trusted for absence:
    the hovered tooltip decides."""
    name = ITEM_NAMES[item]
    return [GAME_CONTEXT, INVENTORY_BOX_CONTEXT, JevImage.from_pil(panel)], {
        "there": Noul(instructions=f"Is there {name} in the inventory?"),
        "box": Box(instructions=f"The inventory slot holding {name}"),
    }


def inventory_open_request(panel: Image.Image) -> tuple[list, dict]:
    return [GAME_CONTEXT, INVENTORY_CONTEXT, JevImage.from_pil(panel)], {
        "open": Noul(instructions="Is the character inventory window open?"),
    }


def slot_request(slot: Image.Image, extra: list[str] | None = None) -> tuple[list, dict]:
    """Tooltip title as a Choice over all item names, so 'Stone' can't match 'Stone furnace'
    (a yes/no "does it say 'Stone'?" scored 0.60 on a stone furnace)."""
    titles = dict(SLOT_TITLES)
    for k in extra or []:
        titles.setdefault(k, ITEM_NAMES[k].capitalize())
    return [GAME_CONTEXT, SLOT_CONTEXT, JevImage.from_pil(slot)], {
        "slot_empty": Noul(instructions="Is the hovered slot empty (no item icon)?"),
        "item": Choice(
            instructions="What name is in the tooltip's title bar?",
            criteria={
                **{k: f"'{v}'" for k, v in titles.items()},
                "other": "Another name",
                "none": "No tooltip",
            },
        ),
        "count": Choice(
            instructions="What number is on the hovered slot's icon?",
            criteria={
                **{str(n): None for n in range(1, 101)},
                "more": "More than 100",
                "none": "No item in the slot",
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
