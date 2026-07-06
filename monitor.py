#!/usr/bin/env python3
"""Boligvagten launcher for the clone-and-run workflow.

    git clone … && cd boligvagten && python3 monitor.py

The actual code lives in the boligvagten/ package; installing via pip/uvx
gives you the same entry point as the `boligvagten` command.
"""
from boligvagten.monitor import main

if __name__ == "__main__":
    main()
