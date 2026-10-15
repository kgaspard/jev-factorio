"""Objective `wait`: let the drills and furnaces work for a while. No Jev call."""

import time

from PIL import Image

from . import actions, config
from .actions import Action


class WaitPolicy:
    def __init__(self, seconds: float = config.WAIT_SECONDS) -> None:
        self.seconds = seconds
        self.started: float | None = None
        self.total_cost = 0.0
        self.done = False
        self.success = False

    def decide(self, frame: Image.Image, tick: int) -> tuple[Action, dict]:
        now = time.time()
        if self.started is None:
            self.started = now
        left = self.seconds - (now - self.started)
        if left <= 0:
            self.done = self.success = True
            reason = f"waited {self.seconds:.0f} s"
        else:
            reason = f"{left:.0f} s to go"
        info = {
            "objective": "wait",
            "jev": {"tokens": 0, "cost_usd": 0.0},
            "decision": {"source": "wait", "reason": reason},
            "total_cost_usd": 0.0,
        }
        return actions.wait(0 if self.done else min(left, config.WAIT_POLL_SECONDS)), info

    def cleanup(self) -> list[Action]:
        return []
