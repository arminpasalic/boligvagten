#!/usr/bin/env python3
"""Fail a release when its Git tag and package version disagree."""
import argparse
import re
import runpy
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parents[1] / "boligvagten" / "__init__.py"
__version__ = runpy.run_path(str(VERSION_FILE))["__version__"]

SEMVER_TAG = re.compile(
    r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)


def validate(tag, version):
    if not SEMVER_TAG.fullmatch(tag):
        raise ValueError(f"release tag must be SemVer with a leading 'v': {tag!r}")
    expected = f"v{version}"
    if tag != expected:
        raise ValueError(f"release tag {tag!r} does not match package version {version!r}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", help="Git tag being released, for example v1.2.3")
    args = parser.parse_args(argv)
    validate(args.tag, __version__)
    print(f"release version validated: {args.tag}")


if __name__ == "__main__":
    main()
