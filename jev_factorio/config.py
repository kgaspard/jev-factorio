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
# The minimap panel's top border (a flat grey line) was at y=136 when MINIMAP_TOP was measured.
# An extra row of buttons above it showed up mid-game and pushed it (and the info panel
# under it) 16 px down, so the border is found in every frame and everything shifts with it.
MINIMAP_BORDER_Y = 136
MINIMAP_BORDER_SEARCH = (100, 300)  # rows to look for it in
# Upscaled before sending. At 448 px Jev's boxes missed the patch (too high); at 1024 px they
# land on it, for about 2,200 more tokens and no extra wait (the main view is slower anyway).
MINIMAP_JEV_SIZE = 1024
KILL_SWITCH_VK = 0x23  # End key: stops the loop even while Factorio has focus
VIEW_TILES = (40, 22.5)  # tiles visible in the main view (48 px per tile, TILE_PX)

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
REACH_TILES = 1.67  # a main-view box this close counts as in reach (tuned as 80 px)
STANDING_MIN = 0.7  # "standing on <target>" needed to count a tick as arrived
ARRIVED_STREAK = 3  # arrived ticks in a row before stopping
STUCK_MOVED_TILES = 0.67  # a move that shifts the view less than this counts as blocked
# Close-up sent to Jev when blocked: this region around the player, upscaled 2x.
CLOSEUP_SIZE = (640, 360)

# ---- Mining (CP3) ----
# Measured at 1920x1080: the entity info panel (offset of its left edge from the client's
# right edge, top, bottom), the strip above the quickbar where the mining bar shows, and the
# area above the cursor the "+1 Coal (N)" text rises through (width, above, below).
INFO_PANEL = (256, 390, 710)
PROGRESS_BAR = (690, 870, 1180, 1070)
CURSOR_TEXT_AREA = (480, 230, 90)
PANEL_SAYS_MIN = 0.8  # "panel says <target>" needed before holding right-click
CORNERS_YELLOW_MIN = 0.5  # selection corners yellow (in reach), also needed
MINING_BAR_MIN = 0.5
NO_BAR_TICKS = 2  # ticks without the mining bar before releasing and aiming again
COUNT_MIN_CONFIDENCE = 0.7  # count choice confidence needed to accept a reading
MAX_AIMS = 4  # aims that fail the hover check in a row before giving up
AIM_TILES = 1.0  # how far out from the player to hover on the chosen side
AIM_UP_TILES = 1.6  # straight up the character sprite is in the way (it is ~1.5 tiles tall)
AIM_MAX_SIDES = 4  # sides tried (best first) per aim request
AIM_SIDE_MIN = 0.08  # sides less likely than this aren't tried
AIM_NONE_MIN = 0.5  # "none within two tiles" this likely: step closer instead

# ---- Jev ----
JEV_MODEL = "jev-1.14.0"  # Box needs 1.14 (alias: jev-preview)
JEV_HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}
JEV_MAX_IMAGE_SIDE = 1568  # API rejects images with a side > 1568 px
JEV_PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000  # USD; output tokens are free

# ---- Inventory check ----
# Measured at 1920x1080 with default UI scale: the "Character" panel when the inventory is
# open, and the centre of its first slot. Slots are 40 px apart, 10 per row.
INVENTORY_PANEL = (520, 280, 955, 705)
INVENTORY_SLOT0 = (562, 382)
INVENTORY_SLOT_PITCH = 40
INVENTORY_COLUMNS = 10
INVENTORY_SLOTS = 80
INVENTORY_TAP_SECONDS = 0.1  # a 50 ms tap didn't always open it
OPEN_MIN = 0.7  # "inventory open" needed to start reading
INVENTORY_RETRIES = 3  # failed opens/closes before giving up
SLOT_CANDIDATES = 3  # slots under a box whose tooltips get checked, nearest first
TOOLTIP_SAYS_MIN = 0.8  # tooltip title = wanted item; present items read 1.00, absent <= 0.03

# ---- Placing the furnace (CP4) ----
# Spots tried for the furnace, in tiles from the player (x right, y down), first fitting one
# wins. 2 tiles keeps the 2x2 furnace clear of the character.
PLACE_SPOTS = [(2, 0), (-2, 0), (0, 2), (2, 2), (-2, 2)]

# ---- The furnace window (CP5) ----
BUILDING_WINDOW = (500, 270, 1420, 710)  # where a building's window opens (stone furnace)
STONE_FURNACE_SIDE = (965, 320, 1395, 690)  # its right half: status, ore/output slots, fuel slot
STONE_FURNACE_GRID_DY = -4  # its character grid sits 4 px higher than the inventory's
WINDOW_OPEN_MIN = 0.8  # "stone_furnace_window" read 1.00 when open
# Furnace slot centres. Each is read from its own close-up: on the whole half-window Jev
# mixed the slots up (fuel 0.53 with 10 coal in it), one slot at a time it reads every count.
STONE_FURNACE_SLOTS = {"input": (997, 537), "output": (1357, 537), "fuel": (997, 597)}
STONE_FURNACE_STACK = 50  # ore and coal stack size: what one furnace slot holds
FUEL_COUNT = 10  # coal put into a building: picked up, then right-clicked in one at a time
STONE_FURNACE_EMPTY_MAX = 0.2  # P(count 0) at most this = the slot holds something
STATUS_MIN = 0.8  # furnace status line read; "Working"/"No fuel"/"No ingredients" read 1.00
SMELT_POLL_SECONDS = 3.0  # between info panel looks while smelting (16 plates take ~51 s)
SMELT_MAX_POLLS = 40

# ---- Burner mining drills ----
# Its window: TODO measure. Guessed from the furnace window until a screenshot of one.
BURNER_MINING_DRILL_SLOTS = {"fuel": (997, 597)}
BURNER_MINING_DRILL_GRID_DY = -4
# Spots tried for a drill, in tiles from the player. Its furnace goes 2 tiles above it, so no
# spot straight below the player (the furnace would land on the character).
BURNER_MINING_DRILL_SPOTS = [(2, 0), (-2, 0), (2, 2), (-2, 2), (0, -3), (2, -2), (-2, -2)]
# A drill faces north as placed and drops its ore 1.3 tiles above its centre (0.3 left): a
# 2x2 furnace centred 2 tiles up covers that spot.
STONE_FURNACE_AT_DRILL = (0, -2)
ORE_UNDER_MIN = 0.6  # "the preview stands on <ore>" needed to place a drill there
BURNER_MINING_DRILL_ORE_PER_SECOND = 0.25
BURNER_MINING_DRILL_ORE_PER_COAL = 6.67  # 150 kW, 4 s per ore, 4 MJ per coal
STONE_FURNACE_PLATES_PER_SECOND = 0.3125  # 3.2 s per plate
WAIT_SECONDS = 30.0  # the `wait` objective
COLLECT_MIN_PLATES = 10  # collect_* is offered once a drill's furnace has about this many
WAIT_POLL_SECONDS = 3.0

# ---- Crafting (the panel right of the inventory when E is open) ----
CRAFTING_PANEL = (965, 320, 1395, 690)  # tabs and recipe grid
# The recipe grid alone: with the tabs in the crop, a recipe box landed on the Production
# tab's icon (0.07-0.15); without them it found the stone furnace (0.30-0.44).
RECIPE_PANEL = (965, 398, 1395, 690)
CRAFT_TAB0 = (1018, 352)  # first of 4 tabs: logistics, production, intermediate products, combat
CRAFT_TAB_PITCH = 106
RECIPE_SLOT0 = (998, 421)
RECIPE_COLUMNS = 10
RECIPE_SLOTS = 70
CRAFT_POLL_SECONDS = 1.0  # between inventory looks while the crafting queue runs
CRAFT_EXTRA_POLLS = 5  # looks beyond the recipe's crafting time

# ---- Where things are ----
# Pixels per tile in the main view: the red overlap squares of a blocked furnace preview are
# 48 px apart, and a 0.25 s move (107 px) is then 2.2 tiles, the character's 9 tiles/s.
TILE_PX = 48
ODOMETRY_AREA = (100, 100, 1600, 950)  # game view without the HUD, for visual odometry
GO_TO_NEAR_TILES = 3.5  # go_to_<building> stops this close (reach is about 10 tiles)
GO_TO_MOVE_SECONDS = 0.25  # one move: 2.2 tiles
GO_TO_STUCK_TILES = 0.33  # a move that walked less than this is blocked
