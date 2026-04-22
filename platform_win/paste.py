"""Windows paste: clipboard + synthetic Ctrl+V.

Same 80 ms settle sleep as macOS — releasing the trigger key just before
the synthetic Ctrl+V risks the held modifier interfering with the paste.
"""
import time

import pyperclip
from pynput import keyboard


_kb = keyboard.Controller()


def paste_text(text: str) -> None:
    pyperclip.copy(text)
    time.sleep(0.08)
    _kb.press(keyboard.Key.ctrl)
    _kb.press("v")
    _kb.release("v")
    _kb.release(keyboard.Key.ctrl)
