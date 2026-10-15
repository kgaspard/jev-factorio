"""Main loop: screenshot -> policy decides -> execute -> sleep so each tick lasts >= L.

Run:  uv run python -m jev_factorio.loop --policy random --seconds 5
Click into Factorio within the countdown. Press End (or Ctrl+C in the console) to stop.
"""

import argparse
import random
import time

from . import actions, config
from .actions import Action
from .capture import Screen
from .runlog import RunLog
from .window import (
    client_rect,
    factorio_is_active,
    find_factorio,
    kill_switch_pressed,
    place_client,
)


class RandomPolicy:
    """Checkpoint 1: random moves, sometimes toggling the inventory."""

    def __init__(self):
        self.inventory_open = False

    def decide(self, frame, tick: int) -> tuple[Action, dict]:
        if random.random() < 0.2:
            self.inventory_open = not self.inventory_open
            return actions.tap("toggle_inventory", "e"), {}
        direction = random.choice(["up", "down", "left", "right"])
        return actions.move(direction, config.MOVE_HOLD_SECONDS), {}

    def cleanup(self) -> list[Action]:
        return [actions.tap("toggle_inventory", "e")] if self.inventory_open else []


POLICIES = {"random": RandomPolicy}


def run(policy, seconds: float, tick_seconds: float, countdown: float):
    hwnd = find_factorio()
    if hwnd is None:
        raise SystemExit("Factorio window not found. Is the game running?")
    place_client(hwnd, *config.GAME_CLIENT_SIZE)
    time.sleep(0.5)
    game = client_rect(hwnd)
    if (game.width, game.height) != config.GAME_CLIENT_SIZE:
        print(
            f"Warning: Factorio client area is {game.width}x{game.height}, "
            f"expected {config.GAME_CLIENT_SIZE[0]}x{config.GAME_CLIENT_SIZE[1]}. "
            "Is Factorio in windowed mode?"
        )

    print(f"Click into Factorio. Starting in {countdown:.0f} s...")
    time.sleep(countdown)

    log = RunLog(type(policy).__name__.lower())
    screen = Screen()
    print(f"Logging to {log.dir}")
    start = time.time()
    tick = 0
    try:
        while time.time() - start < seconds and not kill_switch_pressed():
            tick_start = time.time()
            game = client_rect(hwnd)  # follow the window if it moves
            frame = screen.grab(game)
            t_shot = time.time()

            action, info = policy.decide(frame, tick)
            t_decided = time.time()

            executed = actions.execute(action, game)
            t_acted = time.time()

            log.write(
                {
                    "tick": tick,
                    "t_shot": t_shot,  # what the video renderer syncs on
                    "frame": log.save_tick_frame(tick, frame),
                    "action": action.to_dict(),
                    "executed": executed,
                    "decide_ms": round((t_decided - t_shot) * 1000),
                    "act_ms": round((t_acted - t_decided) * 1000),
                    **info,
                }
            )
            status = "ok" if executed else "SKIPPED (Factorio not focused)"
            print(
                f"[{tick:03d}] {action.name:<18} {status}  "
                f"tick={round((time.time() - tick_start) * 1000)}ms"
            )

            tick += 1
            time.sleep(max(0.0, tick_seconds - (time.time() - tick_start)))
    except KeyboardInterrupt:
        pass
    finally:
        if factorio_is_active():
            for action in policy.cleanup():
                actions.execute(action, game)
        actions.release_all()
        screen.close()
        log.close()
        print(f"Stopped after {tick} ticks. Run saved to {log.dir}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", choices=POLICIES, default="random")
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--tick", type=float, default=config.TICK_SECONDS, help="L in seconds")
    parser.add_argument("--countdown", type=float, default=2)
    args = parser.parse_args()
    run(POLICIES[args.policy](), args.seconds, args.tick, args.countdown)


if __name__ == "__main__":
    main()
