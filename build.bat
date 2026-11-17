@echo off
REM Builds dist\ytdl-sub-win-gui.exe (single file, no console window).
REM Needs Python 3.10 - 3.13 (PySide6/PyYAML ship prebuilt Windows wheels for these).
REM Very new Pythons (3.14+) may have no wheels yet and fail asking for "Visual C++ 14.0".
setlocal
cd /d "%~dp0"

set "PY="
for %%V in (3.13 3.12 3.11 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    echo No supported Python found. Install Python 3.13, e.g. run:  py install 3.13
    echo or download it from https://www.python.org/downloads/windows/
    exit /b 1
)
echo Using: %PY%

REM Recreate the venv if it was made with a different Python version.
if exist .venv (
    .venv\Scripts\python.exe -c "import sys; sys.exit(0 if sys.version_info < (3, 14) else 1)" >nul 2>&1 || (
        echo Existing .venv uses an unsupported Python - recreating it.
        rmdir /s /q .venv
    )
)
if not exist .venv (
    %PY% -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install --only-binary=:all: -r requirements.txt pyinstaller || goto :error
pyinstaller --noconfirm --clean --onefile --windowed --name ytdl-sub-win-gui launcher.py || goto :error
echo.
echo Built: %CD%\dist\ytdl-sub-win-gui.exe
exit /b 0
:error
echo Build failed.
exit /b 1
