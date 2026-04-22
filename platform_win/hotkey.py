"""Windows default push-to-talk trigger.

Right Alt is AltGr on Polish/ISO layouts (used for ą ć ę ł ń ó ś ź ż), so
we cannot reuse the macOS default. Right Ctrl is the safest common choice.
Override with the VD_TRIGGER env var if you have a preferred dead key.
"""


def default_trigger() -> str:
    return "ctrl_r"
