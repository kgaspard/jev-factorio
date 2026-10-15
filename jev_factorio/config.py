"""All tunables in one place."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"

# ---- Loop ----
TICK_SECONDS = 0.5  # L: minimum tick length; a tick lasts max(L, decide + act)
MOVE_HOLD_SECONDS = 0.25  # how long a WASD move is held

# ---- Factorio window ----
FACTORIO_EXE = "factorio.exe"  # matched against the window's process, case-insensitive
GAME_CLIENT_SIZE = (1920, 1080)  # windowed client area (width, height); panel gets the rest
# Minimap position inside the client area, measured at 1920x1080 with default UI scale:
# offset of its right edge from the client's right edge, its top, and its side length.
MINIMAP_RIGHT, MINIMAP_TOP, MINIMAP_SIZE = 17, 152, 224
MINIMAP_JEV_SIZE = 448  # upscaled before sending (API minimum side is 256 px)
KILL_SWITCH_VK = 0x23  # End key: stops the loop even while Factorio has focus

# ---- Jev ----
JEV_MODEL = "jev-1.14.0"  # Box needs 1.14 (alias: jev-preview)
JEV_HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}
JEV_MAX_IMAGE_SIDE = 1568  # API rejects images with a side > 1568 px
JEV_PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000  # USD; output tokens are free
