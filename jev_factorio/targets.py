"""Things the player can walk to. Descriptions matter: Jev recognises resources from the
colours we give it, not from knowing Factorio."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    key: str
    name: str  # as used in questions, e.g. "iron ore"
    minimap_colour: str  # colour of its checkered patches on the minimap
    ground_colour: str  # colour of its rocks in the main view


TARGETS = {
    t.key: t
    for t in [
        Target("iron_ore", "iron ore", "grey-blue", "grey-blue"),
        Target("copper_ore", "copper ore", "orange", "orange-brown"),
        Target("coal", "coal", "black", "black"),
        Target("stone", "stone", "light beige-grey", "sandy beige"),
    ]
}


def _listing(pairs: list[str]) -> str:
    return ", ".join(pairs[:-1]) + " and " + pairs[-1]


MINIMAP_LEGEND = (
    "Resource patches show as checkered areas: "
    + _listing([f"{t.name} is {t.minimap_colour}" for t in TARGETS.values()])
    + ". Water is solid dark blue."
)
# "Clusters" and the boulder/spaceship note cut false "iron on screen" at the crash site from
# 0.57 to 0.46.
GROUND_LEGEND = (
    "Resources on the ground look like clusters of rocks: "
    + _listing([f"{t.name} is {t.ground_colour}" for t in TARGETS.values()])
    + ". Single grey boulders and the crashed spaceship are not resources."
)
