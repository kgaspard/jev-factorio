"""Live Jev panel: a borderless window right of the game that follows a run's decisions.jsonl.
It never takes focus, so keys keep going to Factorio. The loop starts it in its own process.

Run by hand:  uv run python -m jev_factorio.live_view runs/<run-folder>
"""

import argparse
import ctypes
import json
import time
import tkinter as tk
from pathlib import Path

from PIL import ImageDraw, ImageTk

from . import config, hud
from .window import factorio_is_active, user32  # importing also makes this process DPI aware

GWL_EXSTYLE = -20
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x8, 0x80, 0x08000000
SW_SHOWNOACTIVATE = 4
REFRESH_MS = 100


class LiveView:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.jsonl = run_dir / "decisions.jsonl"
        self._offset = 0
        self.record: dict | None = None

        previous = user32.GetForegroundWindow()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        (w, h), (x, y) = config.PANEL_SIZE, config.PANEL_POS
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.label = tk.Label(self.root, bd=0, bg="black")
        self.label.pack()
        self.root.update_idletasks()

        # No activation on show or click, no taskbar button, always on top.
        hwnd = int(self.root.wm_frame(), 16)
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ctypes.c_long(style))
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        HWND_TOPMOST, SWP_NOMOVE_NOSIZE_NOACTIVATE = -1, 0x0001 | 0x0002 | 0x0010
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE_NOSIZE_NOACTIVATE)
        # Creating the Tk window still takes focus once; hand it back to whoever had it.
        self.root.update()
        if previous and user32.GetForegroundWindow() != previous:
            user32.SetForegroundWindow(previous)

    def _read_new(self):
        if not self.jsonl.is_file():
            return
        with open(self.jsonl, "rb") as f:  # binary: byte offsets stay exact with \r\n
            f.seek(self._offset)
            for line in f:
                if not line.endswith(b"\n"):
                    break  # half-written; read it next time
                self._offset += len(line)
                self.record = json.loads(line)

    def _refresh(self):
        self._read_new()
        img = hud.render(self.record, self.run_dir, time.time())
        if not factorio_is_active():
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, img.width, 92), fill=(170, 30, 30))
            draw.text((hud.PAD, 10), "PAUSED", fill=(255, 255, 255), font=hud.font(38, bold=True))
            draw.text(
                (hud.PAD, 56), "Factorio isn't focused - click into it", fill=(255, 255, 255),
                font=hud.font(20),
            )  # fmt: skip
        self._photo = ImageTk.PhotoImage(img)  # keep a reference or Tk drops the image
        self.label.configure(image=self._photo)
        self.root.after(REFRESH_MS, self._refresh)

    def run(self):
        self._refresh()
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    LiveView(args.run_dir).run()


if __name__ == "__main__":
    main()
