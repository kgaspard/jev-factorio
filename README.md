# Jev plays Factorio

Jev (a vision model behind the Typesafe SDK) plays Factorio from screenshots alone: each tick
it looks at the screen, decides, and presses keys or moves the mouse. The current goal: from a
fresh freeplay game, craft 10 automation science packs (red science).

**See it in action:** [Jev reaches 10 red science in one run for $0.11](https://youtu.be/8x3GphnIgWk)

## Requirements

- Windows (input and window handling use the Win32 API).
- Factorio 2.0 (+ Space Age), **windowed with a 1920x1080 client area at the top-left** of
  the screen, default UI scale and key bindings. The live panel opens to the right of it
  (640x1080), so a 2560x1440 screen fits both.
- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- `ffmpeg` on the PATH (recording and rendering).
- A Typesafe API key.

## Setup

```
uv sync
cp .env.example .env    # then put your key in TYPESAFE_API_KEY
uv run pre-commit install
```

## Run

Start a new freeplay game, then:

```
uv run python -m jev_factorio.loop --policy play --goal red_science --seconds 1800
```

The loop brings Factorio to the front and pauses whenever it loses focus. Press End to stop.
Each run gets a folder in `runs/` with every decision (`decisions.jsonl`), the screenshots,
the game state (`state.json`) and a recording (`video.mp4`). `--resume` carries on from the
latest run's state.

Other policies (walk, mine, craft, place a building, ...) are listed at the top of
`jev_factorio/loop.py`.

## Video

The recording with Jev's panel next to it, in real time or sped up (here 5x, and 8x while
hand-mining coal or waiting for the furnaces):

```
uv run python -m jev_factorio.render runs/<run-folder>
uv run python -m jev_factorio.render runs/<run-folder> --speed 5 --fast mine_coal=8,wait=8
```

## Checks

```
uv run ruff check jev_factorio && uv run ruff format jev_factorio
uv run pre-commit run mypy --files jev_factorio/*.py
```
