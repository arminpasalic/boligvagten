"""Where config and state live — supports both ways of running boligvagten.

* From a clone: `python3 monitor.py` inside the checkout. config.py and
  seen_listings.json sit in the current directory, exactly as before.
* Installed (pipx/uvx/pip): the `boligvagten` command can run from anywhere;
  config lives in ~/.config/boligvagten/ (XDG_CONFIG_HOME respected).

config.py resolution order:
  1. $BOLIGVAGTEN_CONFIG — explicit path, wins always
  2. ./config.py — the clone workflow (also lets a cron job keep one
     config per working directory)
  3. ~/.config/boligvagten/config.py

First run (no config anywhere yet): it is created in the current directory
when ./config.example.py exists (you're inside a checkout), otherwise in
~/.config/boligvagten/ from the template shipped inside the package.

State (seen_listings.json, contact-form screenshots) always sits next to
whichever config.py is in use.
"""
import os
from pathlib import Path


def _xdg_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "boligvagten"


def config_file():
    """The config.py to use — existing one if found, else where to create it."""
    env = os.environ.get("BOLIGVAGTEN_CONFIG")
    if env:
        return Path(env).expanduser()
    cwd_cfg = Path.cwd() / "config.py"
    if cwd_cfg.exists():
        return cwd_cfg
    xdg_cfg = _xdg_dir() / "config.py"
    if xdg_cfg.exists():
        return xdg_cfg
    # No config yet: prefer the checkout when we're standing in one.
    if (Path.cwd() / "config.example.py").exists():
        return cwd_cfg
    return xdg_cfg


def state_dir():
    """Directory for seen_listings.json etc. — always next to the active config."""
    return config_file().parent


def example_file():
    """The config.example.py template: checkout copy, wheel copy, or repo root."""
    candidates = (
        Path.cwd() / "config.example.py",                    # running inside a checkout
        Path(__file__).parent / "config.example.py",         # installed wheel (force-included)
        Path(__file__).parent.parent / "config.example.py",  # editable install / clone import
    )
    for c in candidates:
        if c.exists():
            return c
    return candidates[1]  # nothing found — let the caller fail with a clear path
