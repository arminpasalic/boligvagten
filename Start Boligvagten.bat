@echo off
rem Double-click to start Boligvagten (Windows).
rem
rem Opens Boligvagten in your browser. Closing the browser tab stops it.
rem Uses the Python already on this computer when it is new enough (3.9+).
rem Otherwise it downloads a temporary copy of uv + Python into a temp folder
rem and deletes that folder again when Boligvagten stops. Nothing is installed.
rem Your settings are kept in %USERPROFILE%\.config\boligvagten\.

setlocal
set "UV_VERSION=0.12.22"
cd /d "%~dp0"

echo Boligvagten is starting. It opens in your browser.
echo Closing the browser tab stops it. You can also close this window.
echo.

if defined BOLIGVAGTEN_FORCE_UV goto useuv

rem "py" is the official Python launcher. The "python" fallback can be the
rem Microsoft Store placeholder, which fails the version check below.
py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1
if not errorlevel 1 (
    py -3 -m boligvagten --web
    goto end
)
python -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1
if not errorlevel 1 (
    python -m boligvagten --web
    goto end
)

:useuv
rem No suitable Python: borrow one for this session only. A fixed folder
rem name means a window closed mid-run is cleaned up on the next start.
set "RUNTIME=%TEMP%\boligvagten-runtime"
if exist "%RUNTIME%" rmdir /s /q "%RUNTIME%"
set "UV_UNMANAGED_INSTALL=%RUNTIME%\bin"
set "UV_CACHE_DIR=%RUNTIME%\cache"
set "UV_PYTHON_INSTALL_DIR=%RUNTIME%\python"
set "UV_NO_CONFIG=1"
set "UV_PYTHON_PREFERENCE=only-managed"

echo Downloading a temporary Python (this happens only when none is installed)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/%UV_VERSION%/install.ps1 | iex" >nul
if errorlevel 1 (
    echo Could not download Python. Check your internet connection and try again.
    pause
    goto cleanup
)

rem Auto-contact can use this uv to fetch its temporary browser.
set "BOLIGVAGTEN_UV=%RUNTIME%\bin\uv.exe"
"%RUNTIME%\bin\uv.exe" run --quiet --no-project --python 3.12 python -m boligvagten --web

:cleanup
if exist "%RUNTIME%" rmdir /s /q "%RUNTIME%"

:end
endlocal
