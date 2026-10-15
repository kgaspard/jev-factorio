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
# Upscaled before sending. At 448 px Jev's boxes missed the patch (too high); at 1024 px they
# land on it, for about 2,200 more tokens and no extra wait (the main view is slower anyway).
MINIMAP_JEV_SIZE = 1024
KILL_SWITCH_VK = 0x23  # End key: stops the loop even while Factorio has focus
VIEW_TILES = (60, 33.75)  # tiles visible in the main view at default zoom (32 px per tile)

# ---- Recording and live panel ----
RECORD_FPS = 20
PANEL_SIZE = (640, 1080)  # same height as the game, so the video is game | panel
PANEL_POS = (1920, 0)  # right of the game window; the terminal goes below

# ---- Navigation (CP2) ----
SMOOTH_TICKS = 3  # minimap direction probabilities are averaged over this many ticks
DIRECTION_MIN_PROB = 0.3  # smoothed probability needed to follow the minimap direction
MINIMAP_BOX_MIN_CONFIDENCE = 0.6  # to steer by the minimap box once the choice says "here"
# A grey rock scored "iron on screen" 0.42-0.65 with box confidence up to 0.50.
SCREEN_SEEN_MIN = 0.7  # "<target> on screen" needed to steer by the main-view box
SCREEN_BOX_MIN_CONFIDENCE = 0.4
SCREEN_MAX_ANGLE_OFF = 67.5  # main-view box must roughly agree with the minimap direction
SCREEN_STREAK = 2  # ticks in a row of the above before switching to the main view
REACH_TILES = 2.5  # hand mining reach is about 2.7 tiles
STANDING_MIN = 0.7  # "standing on <target>" needed to count a tick as arrived
ARRIVED_STREAK = 3  # arrived ticks in a row before stopping
STUCK_MOVED_TILES = 1.0  # a move that shifts the view less than this counts as blocked
# Close-up sent to Jev when blocked: this region around the player, upscaled 2x.
CLOSEUP_SIZE = (640, 360)

# ---- Jev ----
JEV_MODEL = "jev-1.14.0"  # Box needs 1.14 (alias: jev-preview)
JEV_HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}
JEV_MAX_IMAGE_SIDE = 1568  # API rejects images with a side > 1568 px
JEV_PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000  # USD; output tokens are free
