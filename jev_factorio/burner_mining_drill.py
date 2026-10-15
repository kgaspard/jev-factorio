"""Objective `fuel_burner_mining_drill`: put 10 coal into a placed burner mining drill (the
steps are in building_window.py). The drill starts mining as soon as it has fuel."""

import time

from . import config
from .building_window import BuildingRef, BuildingWindowPolicy, WindowSpec
from .state import GameState

KIND = "burner_mining_drill"
SPEC = WindowSpec(
    KIND,
    "Burner mining drill",
    config.BURNER_MINING_DRILL_SLOTS,
    config.BURNER_MINING_DRILL_GRID_DY,
)


class BurnerMiningDrillPolicy(BuildingWindowPolicy):
    SPEC = SPEC

    def __init__(self, state: GameState, drill: BuildingRef = None) -> None:
        super().__init__(state, "fuel_burner_mining_drill", "coal", drill)

    def _moved(self, n: int) -> None:
        """Mining starts (again) now: keep the ore mined so far, mined at the drill's rate
        from a start time moved forward past the time it stood without fuel."""
        b, now = self._building(), time.time()
        if b.started_at is None:
            b.started_at = now
            return
        b.contents["coal"] -= n  # what it had before this fuel
        mined = b.mined(now)
        b.contents["coal"] += n
        b.started_at = now - mined / config.BURNER_MINING_DRILL_ORE_PER_SECOND
