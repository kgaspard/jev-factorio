"""Render a run's video: the recorded game area with the Jev panel to its right, as the live
view showed it. Each recorded frame gets the panel for the last decision written by then
(decisions.jsonl "t" vs video_frames.csv).

  uv run python -m jev_factorio.render runs/<run-folder> [--seconds N]

Writes video_panel.mp4 next to video.mp4.
"""

import argparse
import bisect
import json
import subprocess
from pathlib import Path

from PIL import Image

from . import config, hud


def read_times(run_dir: Path) -> list[float]:
    lines = (run_dir / "video_frames.csv").read_text(encoding="utf-8").splitlines()[1:]
    return [float(line.split(",")[1]) for line in lines if line]


def read_records(run_dir: Path) -> list[dict]:
    with open(run_dir / "decisions.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.endswith("\n")]


def render(run_dir: Path, seconds: float | None = None) -> Path:
    times = read_times(run_dir)
    records = read_records(run_dir)
    written = [r["t"] for r in records]
    if seconds is not None:
        times = times[: round(seconds * config.RECORD_FPS)]
    game_w, game_h = config.GAME_CLIENT_SIZE
    panel_w, _ = config.PANEL_SIZE
    out = run_dir / "video_panel.mp4"
    decode = subprocess.Popen(
        [
            "ffmpeg", "-v", "error", "-i", str(run_dir / "video.mp4"),
            "-frames:v", str(len(times)), "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        stdout=subprocess.PIPE,
    )  # fmt: skip
    encode = subprocess.Popen(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{game_w + panel_w}x{game_h}",
            "-r", str(config.RECORD_FPS), "-i", "-",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            str(out),
        ],
        stdin=subprocess.PIPE,
    )  # fmt: skip
    assert decode.stdout is not None and encode.stdin is not None
    size = game_w * game_h * 3
    canvas = Image.new("RGB", (game_w + panel_w, game_h))
    try:
        for i, t in enumerate(times):
            raw = decode.stdout.read(size)
            if len(raw) < size:
                break
            canvas.paste(Image.frombytes("RGB", (game_w, game_h), raw), (0, 0))
            k = bisect.bisect_right(written, t)
            record = records[k - 1] if k else None
            canvas.paste(hud.render(record, run_dir, t), (game_w, 0))
            encode.stdin.write(canvas.tobytes())
            if i % (10 * config.RECORD_FPS) == 0:
                print(f"{i / config.RECORD_FPS:.0f} s of {len(times) / config.RECORD_FPS:.0f} s")
    finally:
        encode.stdin.close()
        encode.wait()
        decode.stdout.close()
        decode.wait()
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--seconds", type=float, help="only the first N seconds")
    args = parser.parse_args()
    print(f"Wrote {render(args.run_dir, args.seconds)}")


if __name__ == "__main__":
    main()
