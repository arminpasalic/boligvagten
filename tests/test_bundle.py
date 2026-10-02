"""The double-click download: zip contents, launcher modes, launcher syntax."""
import importlib.util
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_bundle", ROOT / "scripts" / "build_bundle.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bundle_contains_package_launchers_and_template(tmp_path):
    builder = _builder()
    target = builder.build(tmp_path)
    top = f"boligvagten-{builder.version()}"
    assert target.name == f"{top}.zip"
    with zipfile.ZipFile(target) as zf:
        names = set(zf.namelist())
        for required in (
            "boligvagten/__main__.py",
            "boligvagten/web.py",
            "boligvagten/web_ui.html",
            "boligvagten/sources/boligportal.py",
            "config.example.py",
            "Start Boligvagten.command",
            "Start Boligvagten.bat",
            "README.txt",
            "LICENSE",
        ):
            assert f"{top}/{required}" in names, required
        assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
        command = zf.getinfo(f"{top}/Start Boligvagten.command")
        assert stat.S_IMODE(command.external_attr >> 16) == 0o755
        assert zf.read(f"{top}/Start Boligvagten.bat").count(b"\r\n") > 10


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="needs bash")
def test_macos_launcher_is_valid_bash():
    subprocess.run(["bash", "-n", str(ROOT / "Start Boligvagten.command")], check=True)
