"""Background screen recorder: grabs the game area at RECORD_FPS and pipes it to ffmpeg.
Each frame's time.time() goes to video_frames.csv, so the video renderer can line frames
up with decisions.jsonl (t_shot)."""

import subprocess
import threading
import time
from pathlib import Path

import mss

from . import config
from .window import Rect


class Recorder(threading.Thread):
    def __init__(self, rect: Rect, out_dir: Path, fps: int = config.RECORD_FPS):
        super().__init__(name="recorder", daemon=True)
        self.rect, self.fps = rect, fps
        self.video_path = out_dir / "video.mp4"
        self.times_path = out_dir / "video_frames.csv"
        self.frames = 0
        self._stop_event = threading.Event()

    def run(self):
        ffmpeg = subprocess.Popen(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "rawvideo", "-pix_fmt", "bgra",
                "-s", f"{self.rect.width}x{self.rect.height}", "-r", str(self.fps), "-i", "-",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p",
                str(self.video_path),
            ],
            stdin=subprocess.PIPE,
        )  # fmt: skip
        assert ffmpeg.stdin is not None
        sct = mss.mss()  # mss handles are per thread
        period = 1 / self.fps
        next_t = time.time()
        try:
            with open(self.times_path, "w", encoding="utf-8") as times:
                times.write("frame,t\n")
                while not self._stop_event.is_set():
                    t = time.time()
                    raw = sct.grab(self.rect.as_mss())
                    ffmpeg.stdin.write(raw.bgra)
                    times.write(f"{self.frames},{t:.4f}\n")
                    self.frames += 1
                    # If a grab ran late, skip ahead instead of bursting to catch up.
                    next_t = max(next_t + period, time.time())
                    self._stop_event.wait(max(0.0, next_t - time.time()))
        finally:
            sct.close()
            ffmpeg.stdin.close()
            ffmpeg.wait()

    def stop(self):
        self._stop_event.set()
        self.join()
