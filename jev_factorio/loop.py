"""Main loop: screenshot -> policy decides -> execute -> sleep so each tick lasts >= L.

Run:  uv run python -m jev_factorio.loop --policy walk --target iron_ore --seconds 120
      uv run python -m jev_factorio.loop --policy mine --target coal --count 10
      uv run python -m jev_factorio.loop --policy gather --target iron_ore --count 16
The loop brings Factorio to the front itself and pauses whenever it loses focus.
Press End (or Ctrl+C in the console) to stop.
The live panel opens right of the game and the game area is recorded to the run folder.
"""

import argparse
import random
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Protocol

from PIL import Image

from . import actions, config
from .actions import Action
from .capture import Screen
from .mine import MinePolicy
from .navigate import WalkPolicy
from .recorder import Recorder
from .runlog import RunLog
from .sequence import SequencePolicy
from .targets import TARGETS
from .window import (
    client_rect,
    factorio_is_active,
    find_factorio,
    focus,
    foreground_owner,
    kill_switch_pressed,
    place_client,
)


class Policy(Protocol):
    done: bool  # set once the policy has reached its goal; the loop then stops

    def decide(self, frame: Image.Image, tick: int) -> tuple[Action, dict]: ...

    def cleanup(self) -> list[Action]: ...


class RandomPolicy:
    """Checkpoint 1: random moves, sometimes toggling the inventory."""

    def __init__(self):
        self.inventory_open = False
        self.done = False

    def decide(self, frame, tick: int) -> tuple[Action, dict]:
        if random.random() < 0.2:
            self.inventory_open = not self.inventory_open
            return actions.tap("toggle_inventory", "e"), {}
        direction = random.choice(["up", "down", "left", "right"])
        return actions.move(direction, config.MOVE_HOLD_SECONDS), {}

    def cleanup(self) -> list[Action]:
        return [actions.tap("toggle_inventory", "e")] if self.inventory_open else []


POLICIES: dict[str, Callable[[argparse.Namespace], Policy]] = {
    "random": lambda args: RandomPolicy(),
    "walk": lambda args: WalkPolicy(TARGETS[args.target]),
    "mine": lambda args: MinePolicy(TARGETS[args.target], args.count),
    "gather": lambda args: SequencePolicy(
        f"gather_{args.target}",
        [WalkPolicy(TARGETS[args.target]), MinePolicy(TARGETS[args.target], args.count)],
    ),
}


def run(
    policy: Policy, tag: str, seconds: float, tick_seconds: float, countdown: float, extras: bool
):
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

    log = RunLog(tag)
    print(f"Logging to {log.dir}")
    panel = recorder = None
    if extras:
        panel = subprocess.Popen([sys.executable, "-m", "jev_factorio.live_view", str(log.dir)])

    time.sleep(1)  # let the panel appear first, so it can't take focus after Factorio gets it
    if not focus(hwnd):
        print(f"Couldn't bring Factorio to the front ({foreground_owner()}). Click into it.")
    print(f"Starting in {countdown:.0f} s. Press End to stop.")
    time.sleep(countdown)

    if extras:
        recorder = Recorder(game, log.dir)
        recorder.start()
    screen = Screen()
    start = time.time()
    tick = 0
    try:
        paused_since = None
        while time.time() - start < seconds and not kill_switch_pressed() and not policy.done:
            # Without focus, keys would go to another window and screenshots may show it, so
            # don't ask Jev at all until Factorio is back in front.
            if not factorio_is_active():
                if paused_since is None:
                    paused_since = time.time()
                    actions.release_all()  # don't keep a button held on another window
                    if hasattr(policy, "paused"):
                        policy.paused()
                    print(f"PAUSED: Factorio lost focus to {foreground_owner()}. Click into it.")
                time.sleep(0.2)
                continue
            if paused_since is not None:
                print(f"Resumed after {time.time() - paused_since:.1f} s")
                paused_since = None
            tick_start = time.time()
            game = client_rect(hwnd)  # follow the window if it moves
            frame = screen.grab(game)
            t_shot = time.time()

            action, info = policy.decide(frame, tick)
            t_decided = time.time()

            executed = actions.execute(action, game)
            t_acted = time.time()

            images = {
                label: log.save_tick_image(tick, label, img)
                for label, img in info.pop("_images", {}).items()
            }
            log.write(
                {
                    "tick": tick,
                    "t_shot": t_shot,  # what the video renderer syncs on
                    "frame": log.save_tick_frame(tick, frame),
                    "images": images,
                    "action": action.to_dict(),
                    "executed": executed,
                    "decide_ms": round((t_decided - t_shot) * 1000),
                    "act_ms": round((t_acted - t_decided) * 1000),
                    **info,
                }
            )
            status = "ok" if executed else f"SKIPPED (focus: {foreground_owner()})"
            reason = info.get("decision", {}).get("reason", "")
            print(
                f"[{tick:03d}] {action.name:<18} {status}  "
                f"tick={round((time.time() - tick_start) * 1000)}ms  {reason}"
            )

            tick += 1
            time.sleep(max(0.0, tick_seconds - (time.time() - tick_start)))
    except KeyboardInterrupt:
        pass
    finally:
        cleanup = policy.cleanup()
        if factorio_is_active():
            for action in cleanup:
                actions.execute(action, game)
        actions.release_all()
        screen.close()
        log.close()
        if recorder:
            recorder.stop()
            print(f"Recorded {recorder.frames} frames to {recorder.video_path}")
        if panel:
            time.sleep(1)  # let the panel show the last decision before closing it
            panel.terminate()
        if not policy.done:
            outcome = "stopped"
        else:
            outcome = "policy finished" if getattr(policy, "success", True) else "policy gave up"
        print(f"{outcome} after {tick} ticks. Run saved to {log.dir}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", choices=POLICIES, default="walk")
    parser.add_argument("--target", choices=TARGETS, default="iron_ore", help="walk/mine target")
    parser.add_argument("--count", type=int, default=10, help="mine/gather: how many to have")
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--tick", type=float, default=config.TICK_SECONDS, help="L in seconds")
    parser.add_argument("--countdown", type=float, default=2)
    parser.add_argument("--no-extras", action="store_true", help="no live panel, no recording")
    args = parser.parse_args()
    targeted = ("walk", "mine", "gather")
    tag = f"{args.policy}-{args.target}" if args.policy in targeted else args.policy
    policy = POLICIES[args.policy](args)
    run(policy, tag, args.seconds, args.tick, args.countdown, not args.no_extras)


if __name__ == "__main__":
    main()
