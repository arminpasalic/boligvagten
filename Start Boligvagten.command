#!/bin/bash
# Double-click to start Boligvagten (macOS). On Linux: bash "Start Boligvagten.command"
#
# Opens Boligvagten in your browser. Closing the browser tab stops it.
# Uses the Python already on this computer when it is new enough (3.9+).
# Otherwise it downloads a temporary copy of uv + Python into a temp folder
# and deletes that folder again when Boligvagten stops. Nothing is installed.
# Your settings are kept in ~/.config/boligvagten/.

UV_VERSION="0.12.22"

cd "$(dirname "$0")" || exit 1

echo "Boligvagten is starting. It opens in your browser."
echo "Closing the browser tab stops it. You can also close this window."
echo

usable_python() {
    candidate="$(command -v python3 2>/dev/null)" || return 1
    # On a Mac without the developer tools, /usr/bin/python3 is only a stub
    # that pops up an install dialog. Don't trigger that.
    if [ "$(uname)" = "Darwin" ] && [ "$candidate" = "/usr/bin/python3" ] \
        && ! xcode-select -p >/dev/null 2>&1; then
        return 1
    fi
    "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null || return 1
    PYTHON="$candidate"
}

if [ -z "${BOLIGVAGTEN_FORCE_UV:-}" ] && usable_python; then
    exec "$PYTHON" -m boligvagten --web
fi

# No suitable Python: borrow one for this session only.
RUNTIME="$(mktemp -d "${TMPDIR:-/tmp}/boligvagten-runtime.XXXXXX")" || exit 1
cleanup() { rm -rf "$RUNTIME"; }
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

export UV_UNMANAGED_INSTALL="$RUNTIME/bin"
export UV_CACHE_DIR="$RUNTIME/cache"
export UV_PYTHON_INSTALL_DIR="$RUNTIME/python"
export UV_NO_CONFIG=1
# Only ever use the Python uv downloads: probing system interpreters could
# hit the same macOS developer-tools stub avoided above.
export UV_PYTHON_PREFERENCE=only-managed

echo "Downloading a temporary Python (this happens only when none is installed)..."
if ! curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | sh -s -- --quiet; then
    echo "Could not download Python. Check your internet connection and try again."
    read -r -p "Press Enter to close." _
    exit 1
fi

# Auto-contact can use this uv to fetch its temporary browser.
export BOLIGVAGTEN_UV="$RUNTIME/bin/uv"
"$RUNTIME/bin/uv" run --quiet --no-project --python 3.12 python -m boligvagten --web
