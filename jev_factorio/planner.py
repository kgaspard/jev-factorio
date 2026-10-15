"""Jev's `next_objective` decision: given the goal and what the state says so far, which
objective comes next. Text only, no image: everything it needs is in the state."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from typesafe_sdk import Choice

from . import config
from .brain import GAME_CONTEXT
from .craft import plan_craft
from .state import ITEM_NAMES, PLATES, Building, GameState, _plural

ORES = {plate: ore for ore, plate in PLATES.items()}

RULES = (
    "A stone furnace smelts ore into plates, one plate per ore, and burns coal as fuel. It "
    "smelts one kind of ore at a time: take its plates out before loading a different ore. A "
    "stone furnace is crafted from 5 stone."
)
DRILL_RULES = (
    "A burner mining drill placed on ore mines it by itself, about 15 ore a minute, and drops "
    "it into the stone furnace at its output, which smelts it as it comes: the plates pile up "
    "in that furnace's output until taken out. Both burn coal: 10 coal lasts a drill about 66 "
    "ore. A burner mining drill is crafted from 3 iron gear wheels, 3 iron plates and 1 stone "
    "furnace (9 iron plates and 5 stone in all): crafting it uses a stone furnace from the "
    "inventory, or makes one from 5 stone."
)

Count = int | Callable[[GameState], int]


@dataclass(frozen=True)
class Goal:
    text: str
    mine: dict[str, Count]  # mine_* objective -> how many of that ore to have
    craft: dict[str, tuple[str, Count]] = field(default_factory=dict)  # objective -> item, count
    check: list[str] = field(default_factory=list)  # items check_inventory looks for
    rules: tuple[str, ...] = (RULES,)
    sites: bool = False  # set up mining sites: say whether one can be set up now

    def count(self, n: Count, state: GameState) -> int:
        return n(state) if callable(n) else n


# ---- red science: two drill sites (iron, copper), each a drill and a stone furnace ----
SITES = 2


def _held(state: GameState, item: str) -> int:
    return (state.inventory or {}).get(item, 0)


def _at_sites(state: GameState, kind: str) -> int:
    return sum(1 for b in state.buildings if b.kind == kind and b.site)


def drills_missing(state: GameState) -> int:
    kind = "burner_mining_drill"
    return max(0, SITES - _at_sites(state, kind) - _held(state, kind))


def stone_furnaces_missing(state: GameState) -> int:
    """Furnaces still to craft: one per site without one, plus one inside each drill to craft,
    less those in the inventory."""
    want = SITES - _at_sites(state, "stone_furnace") + drills_missing(state)
    return max(0, want - _held(state, "stone_furnace"))


def stone_needed(state: GameState) -> int:
    return max(5, 5 * stone_furnaces_missing(state))


def iron_ore_needed(state: GameState) -> int:
    """Hand-mined iron ore: only for the drills' 9 plates each, less the plates held."""
    return max(5, 9 * drills_missing(state) - _held(state, "iron_plate"))


GOALS = {
    "iron_plates": Goal(
        "Goal: have 16 iron plates. So the player needs one stone furnace placed on the "
        "ground, 16 iron ore and a few coal.",
        {"mine_iron": 16, "mine_coal": 5, "mine_stone": 5},
        check=["stone_furnace", "iron_ore", "coal", "stone", "iron_plate"],
    ),
    "gears_copper": Goal(
        "Goal: have 5 iron gear wheels and 10 copper plates. A gear is crafted from 2 iron "
        "plates. So the player needs one stone furnace placed on the ground, 10 iron plates "
        "(16 iron ore is plenty), 10 copper ore and a few coal.",
        {"mine_iron": 16, "mine_copper": 10, "mine_coal": 5, "mine_stone": 5},
        {"craft_gears": ("iron_gear_wheel", 5)},
        [
            "stone_furnace",
            "iron_ore",
            "copper_ore",
            "coal",
            "iron_plate",
            "copper_plate",
            "iron_gear_wheel",
        ],
    ),
    "red_science": Goal(
        "Goal: have 10 automation science packs (red science). Their recipe is locked until "
        "the player crafts a lab: crafting one researches 'Automation science pack'. A lab is "
        "crafted from 10 electronic circuits, 10 iron gear wheels and 4 transport belts; "
        "crafting it by hand makes those parts too, from 36 iron plates and 15 copper plates. "
        "Then each pack is crafted from 1 copper plate and 1 iron gear wheel (2 iron plates): "
        "20 iron plates and 10 copper plates for 10 packs. That is 56 iron plates and 25 "
        "copper plates in all: too many to mine by hand, so get them from burner mining "
        "drills, in these steps. 1. Mine 45 coal. 2. Set up iron mining (a burner mining "
        "drill on iron ore with a stone furnace at its output, each given 10 coal) with the "
        "drill and stone furnace the player has. (Only if the player has no burner mining "
        "drill: first mine 18 iron ore and 20 stone, smelt the iron in a stone furnace placed "
        "on the ground, and craft 2 burner mining drills and 2 stone furnaces.) 3. Mine stone "
        "for the copper site (5 for its "
        "furnace, 5 for the furnace inside its drill). 4. Craft a burner mining drill and a "
        "stone furnace. 5. Set up copper mining the same way. 6. Take plates out of the two "
        "furnaces until the inventory holds 36 iron and 15 copper plates (wait when too few "
        "have piled up), craft the lab; then 20 iron and 10 copper plates more, and craft the "
        "packs. Only take plates out when the next craft needs more plates than the inventory "
        "holds: a furnace keeps its plates safe until then. A furnace slot holds at most 50 "
        "ore and its output 100 plates.",
        {
            "mine_iron": iron_ore_needed,
            "mine_copper": 10,
            "mine_coal": 45,
            "mine_stone": stone_needed,
        },
        {
            "craft_stone_furnace": ("stone_furnace", stone_furnaces_missing),
            "craft_burner_mining_drill": ("burner_mining_drill", drills_missing),
            # Gears for the packs only (the lab makes its own); 0 once held: offered every time,
            # it crafted 4 x 10 and left 25 over.
            "craft_gears": ("iron_gear_wheel", lambda s: max(0, 10 - _held(s, "iron_gear_wheel"))),
            "craft_lab": ("lab", 1),
            "craft_red_science": ("automation_science_pack", 10),
        },
        [
            "burner_mining_drill",
            "stone_furnace",
            "coal",
            "stone",
            "iron_ore",
            "copper_ore",
            "iron_plate",
            "copper_plate",
            "iron_gear_wheel",
        ],
        (RULES, DRILL_RULES),
        sites=True,
    ),
}

OBJECTIVES = {
    "check_inventory": "Open the inventory to see what the player has",
    "mine_coal": "Mine coal, the fuel for furnaces and drills",
    "mine_stone": "Mine stone, to craft stone furnaces from",
    "mine_iron": "Mine iron ore by hand, to smelt in a furnace placed on the ground",
    "mine_copper": "Mine copper ore by hand, to smelt into copper plates",
    "craft_burner_mining_drill": "Craft burner mining drills from iron plates and stone",
    "craft_stone_furnace": "Craft stone furnaces from stone (5 each)",
    "place_stone_furnace": "Place a stone furnace on the ground, to smelt ore loaded by hand",
    "set_up_iron_mining": (
        "Walk to iron ore, place a burner mining drill from the inventory on it and a stone "
        "furnace at its output, and give each 10 coal"
    ),
    "set_up_copper_mining": (
        "Walk to copper ore, place a burner mining drill from the inventory on it and a stone "
        "furnace at its output, and give each 10 coal"
    ),
    "fuel_stone_furnace": "Put 10 coal into a placed stone furnace that has no fuel",
    "fuel_burner_mining_drill": "Put 10 coal into a burner mining drill whose fuel is used up",
    "load_iron_ore": "Put the iron ore mined by hand into a stone furnace",
    "load_copper_ore": "Put the copper ore mined by hand into a stone furnace",
    "wait_for_smelting": "Wait while the hand-loaded furnace smelts its ore",
    "collect_iron_plates": "Take the iron plates out of the furnace that made them",
    "collect_copper_plates": "Take the copper plates out of the furnace that made them",
    "wait": "Wait 30 seconds, only when nothing else on the plan can be done until more plates "
    "are made",
    "craft_gears": "Craft iron gear wheels from iron plates",
    "craft_lab": "Craft a lab (makes its circuits, gears and belts from plates)",
    "craft_red_science": "Craft automation science packs from copper plates and gears",
    "done": "The goal is reached",
}


def missing_for(item: str, count: int, have: dict[str, int]) -> dict[str, int]:
    """Raw materials short for crafting `count` of `item` by hand from `have`."""
    used = plan_craft(item, count, have).used  # a missing raw material counts as used too
    return {k: n - have.get(k, 0) for k, n in used.items() if n > have.get(k, 0)}


def readiness(state: GameState, goal: Goal) -> str:
    """What the inventory allows right now: the sums Jev got wrong (crafting a drill with 8 of
    its 9 plates). Only what is possible: listing what each craft lacked ("1 iron plate more")
    sent Jev mining iron with a drill ready to place. Facts only; the choice stays Jev's."""
    if state.inventory is None:
        return ""
    have = state.inventory
    can = []
    for ore in ("iron_ore", "copper_ore") if goal.sites else ():
        kit = site_kit(state, ore)
        if kit and all(have.get(k, 0) >= n for k, n in kit.items()):
            name = ITEM_NAMES[ore].split()[0]
            what = "finish setting up" if len(kit) < 3 else "set up"
            can.append(f"{what} {name} mining (the inventory has what it needs)")
    for item, count in goal.craft.values():
        n = goal.count(count, state)
        if n > 0 and not missing_for(item, n, have):
            can.append(f"craft {_plural(n, item)}")
    text = (
        "With the inventory as it is, the player can: " + "; ".join(can) + "."
        if can
        else "With the inventory as it is, nothing on the plan can be crafted or set up yet."
    )
    return " ".join([text, *sites_missing(state)]) if goal.sites else text


def sites_missing(state: GameState) -> list[str]:
    """For each mining site not set up yet: what its drill and furnace still need. Unlike
    per-craft shortfalls, this names the next step of the plan (the stone for the copper
    site)."""
    have = dict(state.inventory or {})
    lines = []
    for ore in ("iron_ore", "copper_ore"):
        if state.building("burner_mining_drill", ore) is not None:
            continue
        name = ITEM_NAMES[ore].split()[0].capitalize()
        short: dict[str, int] = {}
        for item in ("burner_mining_drill", "stone_furnace"):
            if have.get(item, 0) > 0:
                have[item] -= 1
                continue
            for k, n in missing_for(item, 1, have).items():
                short[k] = short.get(k, 0) + n
            used = plan_craft(item, 1, have).used
            have = {k: max(0, n - used.get(k, 0)) for k, n in have.items()}
        if have.get("coal", 0) < 20:  # 10 for the drill, 10 for the furnace
            short["coal"] = 20 - have.get("coal", 0)
        have["coal"] = max(0, have.get("coal", 0) - 20)
        if not short:
            lines.append(
                f"{name} mining isn't set up yet; its drill, furnace and coal are in hand."
            )
        else:
            needs = ", ".join(_plural(n, k) for k, n in short.items())
            lines.append(
                f"{name} mining isn't set up yet: its drill, furnace and their coal need "
                f"{needs} more."
            )
    return lines


def site_kit(state: GameState, ore: str) -> dict[str, int]:
    """What setting up the mining site on `ore` still takes from the inventory (empty: it is
    done). A site left half done (the drill placed, the furnace not) needs only the rest."""
    drill = state.building("burner_mining_drill", ore)
    furnace = state.building("stone_furnace", ore)
    kit: dict[str, int] = {}
    if drill is None:
        kit["burner_mining_drill"] = 1
    if furnace is None:
        kit["stone_furnace"] = 1
    coal = (drill is None or drill.started_at is None) + (
        furnace is None or not furnace.contents.get("coal")
    )
    if coal:
        kit["coal"] = config.FUEL_COUNT * coal
    return kit


def drill_needing_fuel(state: GameState, now: float) -> Building | None:
    """A drill with about 2 coal or less left (13 ore), the emptiest first."""
    low = [
        b
        for b in state.buildings
        if b.kind == "burner_mining_drill"
        and b.started_at is not None
        and b.fuel_for() - b.mined(now) <= 2 * config.BURNER_MINING_DRILL_ORE_PER_COAL
    ]
    return min(low, key=lambda b: b.fuel_for() - b.mined(now), default=None)


def available(state: GameState, goal: Goal) -> dict[str, str]:
    """The objectives that make sense now; Jev chooses among these. Offered everything, it
    took 1-2 plates out of the iron furnace 25 times in a row (4 s a trip) instead of mining
    the stone the copper site needed."""
    have = state.inventory or {}
    now = time.time()
    furnaces = [b for b in state.buildings if b.kind == "stone_furnace"]
    drills = [b for b in state.buildings if b.kind == "burner_mining_drill"]

    def ok(objective: str) -> bool:
        if objective in ("check_inventory", "done") or objective in goal.mine:
            return True
        if objective in goal.craft:
            item, count = goal.craft[objective]
            n = goal.count(count, state)  # 0: none needed (a drill would eat a site's furnace)
            return state.inventory is not None and n > 0 and not missing_for(item, n, have)
        if objective == "place_stone_furnace":
            # With drill sites, a held furnace is for a site (or a drill), unless there is no
            # drill to make plates with.
            no_drill = not drills and not have.get("burner_mining_drill")
            return have.get("stone_furnace", 0) > 0 and (not goal.sites or no_drill)
        if objective.startswith("set_up_"):
            ore = objective.removeprefix("set_up_").removesuffix("_mining") + "_ore"
            kit = site_kit(state, ore)
            return goal.sites and bool(kit) and all(have.get(k, 0) >= n for k, n in kit.items())
        if objective == "fuel_stone_furnace":
            return have.get("coal", 0) > 0 and any(not b.contents.get("coal") for b in furnaces)
        if objective == "fuel_burner_mining_drill":
            return have.get("coal", 0) > 0 and bool(drill_needing_fuel(state, now))
        if objective.startswith("load_"):
            return have.get(objective.removeprefix("load_"), 0) > 0 and bool(furnaces)
        if objective == "wait_for_smelting":
            return any(b.site is None and b.holds(PLATES) for b in furnaces)
        if objective.startswith("collect_"):
            plate = objective.removeprefix("collect_").removesuffix("s")
            ore = ORES[plate]
            return any(
                (b.site == ore and state.plates_ready(b, now) >= config.COLLECT_MIN_PLATES)
                or (b.site is None and b.contents.get(plate, 0) > 0)
                for b in furnaces
            )
        if objective == "wait":
            # Only once both sites run: before that there is always stone, coal or a craft
            # to get on with (offered earlier, it waited instead of mining stone).
            return not any(site_kit(state, o) for o in ("iron_ore", "copper_ore"))
        return False

    return {k: v for k, v in OBJECTIVES.items() if ok(k)}


def next_objective_request(state: GameState, goal: Goal) -> tuple[list, dict]:
    facts = [state.describe(), readiness(state, goal)]
    return [GAME_CONTEXT, goal.text, *goal.rules, *[f for f in facts if f]], {
        "next_objective": Choice(
            instructions="What should the player do next to reach the goal?",
            criteria=available(state, goal),
        ),
    }
