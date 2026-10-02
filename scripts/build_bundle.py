"""Build the double-click download: dist/boligvagten-<version>.zip.

The zip is for people who don't use git or a terminal. It holds the package
source, the config template and the two launchers. Unzip it, double-click
"Start Boligvagten", and the settings page opens in the browser.

    python scripts/build_bundle.py

Standard library only. File modes are set explicitly so the macOS launcher
stays executable after unzipping, whatever the build machine's umask.
"""
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAUNCHERS = ("Start Boligvagten.command", "Start Boligvagten.bat")
EXTRA_FILES = ("config.example.py", "LICENSE")

README = """\
Boligvagten
===========

English
-------
1. Double-click "Start Boligvagten".
   macOS: "Start Boligvagten.command". Windows: "Start Boligvagten.bat".
2. Boligvagten opens in your web browser. Set up your searches and phone
   alerts there.
3. Keep the browser tab open while you want alerts. Closing the tab stops
   Boligvagten. Your settings are kept for next time.

Nothing is installed. If this computer has no Python 3.9 or newer, a
temporary copy is downloaded and deleted again when Boligvagten stops.

The first time you open it:
- macOS may say the file "cannot be opened" or "could not be verified".
  Click Done, open System Settings > Privacy & Security, scroll down and
  click "Open Anyway" next to "Start Boligvagten.command".
- Windows may show "Windows protected your PC". Click "More info", then
  "Run anyway".

Settings are stored in ~/.config/boligvagten/ (on Windows:
C:\\Users\\<you>\\.config\\boligvagten\\).

Dansk
-----
1. Dobbeltklik på "Start Boligvagten".
   macOS: "Start Boligvagten.command". Windows: "Start Boligvagten.bat".
2. Boligvagten åbner i din browser. Sæt dine søgninger og beskeder til
   telefonen op dér.
3. Lad fanen være åben, så længe du vil have besked. Lukker du fanen,
   stopper Boligvagten. Dine indstillinger gemmes til næste gang.

Der installeres ingenting. Har computeren ikke Python 3.9 eller nyere,
hentes en midlertidig kopi, som slettes igen, når Boligvagten stopper.

Første gang du åbner den:
- macOS siger måske, at filen "ikke kan åbnes" eller "ikke kunne
  bekræftes". Klik OK, åbn Systemindstillinger > Anonymitet og sikkerhed,
  rul ned og klik "Åbn alligevel" ud for "Start Boligvagten.command".
- Windows viser måske "Windows har beskyttet din pc". Klik "Flere
  oplysninger" og derefter "Kør alligevel".

Indstillingerne gemmes i ~/.config/boligvagten/ (på Windows:
C:\\Users\\<dig>\\.config\\boligvagten\\).

https://github.com/arminpasalic/boligvagten
"""


def version():
    text = (ROOT / "boligvagten" / "__init__.py").read_text()
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def package_files():
    for path in sorted((ROOT / "boligvagten").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            yield path


def _add(zf, arcname, data, mode=0o644):
    info = zipfile.ZipInfo(arcname, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100000 | mode) << 16  # regular file + permissions
    zf.writestr(info, data)


def build(out_dir=None):
    out_dir = Path(out_dir) if out_dir else ROOT / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    top = f"boligvagten-{version()}"
    target = out_dir / f"{top}.zip"
    with zipfile.ZipFile(target, "w") as zf:
        for path in package_files():
            _add(zf, f"{top}/{path.relative_to(ROOT).as_posix()}", path.read_bytes())
        for name in EXTRA_FILES:
            _add(zf, f"{top}/{name}", (ROOT / name).read_bytes())
        for name in LAUNCHERS:
            mode = 0o755 if name.endswith(".command") else 0o644
            _add(zf, f"{top}/{name}", (ROOT / name).read_bytes(), mode)
        _add(zf, f"{top}/README.txt", README.encode("utf-8"))
    return target


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else None))
