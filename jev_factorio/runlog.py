"""A run folder: runs/<timestamp>/ with tick screenshots and decisions.jsonl.
Timestamps are time.time() so the video renderer can sync decisions to recorded frames."""

import json
import time
from datetime import datetime

from PIL import Image

from . import config


class RunLog:
    def __init__(self, tag: str):
        self.dir = config.RUNS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{tag}"
        (self.dir / "ticks").mkdir(parents=True)
        self._jsonl = open(self.dir / "decisions.jsonl", "a", encoding="utf-8")

    def save_tick_frame(self, tick: int, img: Image.Image) -> str:
        name = f"ticks/{tick:05d}.jpg"
        img.save(self.dir / name, quality=90)
        return name

    def write(self, record: dict):
        self._jsonl.write(json.dumps({"t": time.time(), **record}) + "\n")
        self._jsonl.flush()

    def close(self):
        self._jsonl.close()
