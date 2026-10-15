"""Run policies one after another: when one is done, the next one starts on the next tick.
A step that finished without success (e.g. mining gave up) stops the whole sequence."""

from PIL import Image

from .actions import Action


class SequencePolicy:
    def __init__(self, name: str, steps: list) -> None:
        self.name = name
        self.steps = steps
        self.index = 0
        self.cost_before = 0.0  # Jev cost of the finished steps
        self.done = False
        self.success = False

    @property
    def current(self):
        return self.steps[self.index]

    def paused(self) -> None:
        if hasattr(self.current, "paused"):
            self.current.paused()

    def decide(self, frame: Image.Image, tick: int) -> tuple[Action, dict]:
        step = self.current
        action, info = step.decide(frame, tick)
        info["sequence"] = {
            "name": self.name,
            "step": self.index,
            "steps": [s.__class__.__name__ for s in self.steps],
        }
        info["total_cost_usd"] = self.cost_before + info.get("total_cost_usd", 0.0)
        if step.done:
            self.cost_before += step.total_cost
            if not getattr(step, "success", True):
                self.done = True
            elif self.index + 1 < len(self.steps):
                step.cleanup()
                self.index += 1
            else:
                self.done = self.success = True
        return action, info

    def cleanup(self) -> list[Action]:
        # Only the step that was running can have something to undo (e.g. a held button);
        # the others just close their Jev clients.
        actions: list[Action] = []
        for i, step in enumerate(self.steps):
            if i == self.index:
                actions = step.cleanup()
            elif i > self.index:
                step.cleanup()
        return actions
