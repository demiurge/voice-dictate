"""macOS paste: clipboard + synthetic ⌘V.

The 80 ms sleep before the synthetic ⌘V lets the trigger-key release finish
propagating; removing it causes the held modifier to interfere with the
paste.
"""
import time

import pyperclip
from pynput import keyboard


_kb = keyboard.Controller()


def paste_text(text: str) -> None:
    pyperclip.copy(text)
    time.sleep(0.08)
    _kb.press(keyboard.Key.cmd)
    _kb.press("v")
    _kb.release("v")
    _kb.release(keyboard.Key.cmd)
