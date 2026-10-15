"""Render a run's video: the recorded game area with the Jev panel to its right, as the live
view showed it. Each recorded frame gets the panel for the last decision written by then
(decisions.jsonl "t" vs video_frames.csv).

  uv run python -m jev_factorio.render runs/<run-folder> [--seconds N]
      [--speed 5 --fast mine_coal=8,wait=8]

Writes video_panel.mp4 next to video.mp4 (video_panel_<speed>x.mp4 when sped up).

Speed-up: recorded frames are kept, not blended: stepping through the recording's time, each
kept frame moves it on by speed / fps, so 5x keeps every 5th frame. `--fast` gives the
objectives that are mostly waiting (hand-mining coal, waiting for the furnaces) their own
speed; a badge in the panel shows the speed.
"""

import argparse
import bisect
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from . import config, hud


def read_times(run_dir: Path) -> list[float]:
    lines = (run_dir / "video_frames.csv").read_text(encoding="utf-8").splitlines()[1:]
    return [float(line.split(",")[1]) for line in lines if line]


def read_records(run_dir: Path) -> list[dict]:
    with open(run_dir / "decisions.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.endswith("\n")]


def objective(record: dict) -> str:
    """The top-level objective a tick belongs to (the play policy's, not its current step)."""
    return (record.get("play") or {}).get("objective") or record.get("objective", "")


def keep_frames(
    times: list[float],
    records: list[dict],
    speed: float,
    fast: dict[str, float],
) -> list[tuple[int, float]]:
    """(frame index, speed there) for the frames to keep. The time up to a record being
    written belongs to that record's tick."""
    written = [r["t"] for r in records]
    step = 1 / config.RECORD_FPS
    kept = []
    next_t = times[0] if times else 0.0
    for i, t in enumerate(times):
        if t < next_t:
            continue
        k = bisect.bisect_left(written, t)
        s = fast.get(objective(records[k]), speed) if k < len(records) else speed
        kept.append((i, s))
        next_t += s * step
        if next_t <= t:  # a gap in the recording
            next_t = t + s * step
    return kept


def speed_badge(panel: Image.Image, speed: float) -> None:
    """A fast-forward icon and "5x" in the panel's top right corner."""
    draw = ImageDraw.Draw(panel)
    xy, text, font = (panel.width - hud.PAD, 14), f"{speed:g}x", hud.font(38, bold=True)
    draw.text(xy, text, fill=hud.ACCENT, font=font, anchor="ra")
    left, top, _, bottom = draw.textbbox(xy, text, font=font, anchor="ra")
    h, w, gap = 22, 13, 10  # one triangle's height and width, the gap before the text
    mid = (top + bottom) / 2
    for i in (1, 0):  # two triangles side by side, pointing right
        x = left - gap - (i + 1) * w
        draw.polygon([(x, mid - h / 2), (x + w, mid), (x, mid + h / 2)], fill=hud.ACCENT)


def render(
    run_dir: Path,
    seconds: float | None = None,
    speed: float = 1.0,
    fast: dict[str, float] | None = None,
) -> Path:
    fast = fast or {}
    times = read_times(run_dir)
    records = read_records(run_dir)
    written = [r["t"] for r in records]
    if seconds is not None:
        times = times[: round(seconds * config.RECORD_FPS)]
    kept = keep_frames(times, records, speed, fast)
    sped = speed != 1 or bool(fast)
    game_w, game_h = config.GAME_CLIENT_SIZE
    panel_w, _ = config.PANEL_SIZE
    out = run_dir / (f"video_panel_{speed:g}x.mp4" if sped else "video_panel.mp4")
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
    frame_i = -1
    try:
        for n, (i, s) in enumerate(kept):
            while frame_i < i:  # decode up to the kept frame, dropping the ones between
                raw = decode.stdout.read(size)
                frame_i += 1
            if len(raw) < size:
                break
            t = times[i]
            canvas.paste(Image.frombytes("RGB", (game_w, game_h), raw), (0, 0))
            k = bisect.bisect_right(written, t)
            panel = hud.render(records[k - 1] if k else None, run_dir, t)
            if sped:
                speed_badge(panel, s)
            canvas.paste(panel, (game_w, 0))
            encode.stdin.write(canvas.tobytes())
            if n % (10 * config.RECORD_FPS) == 0:
                done, total = n / config.RECORD_FPS, len(kept) / config.RECORD_FPS
                print(f"{done:.0f} s of {total:.0f} s")
        while decode.stdout.read(size):  # the frames after the last kept one
            pass
    finally:
        encode.stdin.close()
        encode.wait()
        decode.stdout.close()
        decode.wait()
    return out


def parse_fast(text: str) -> dict[str, float]:
    """ "mine_coal=8,wait=8" -> {"mine_coal": 8.0, "wait": 8.0}"""
    pairs = (item.split("=") for item in text.split(",") if item)
    return {k.strip(): float(v) for k, v in pairs}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--seconds", type=float, help="only the first N seconds recorded")
    parser.add_argument("--speed", type=float, default=1.0, help="speed-up, e.g. 5")
    parser.add_argument(
        "--fast", type=parse_fast, default={}, help="per-objective speed, e.g. mine_coal=8,wait=8"
    )
    args = parser.parse_args()
    print(f"Wrote {render(args.run_dir, args.seconds, args.speed, args.fast)}")


if __name__ == "__main__":
    main()
