@echo off
REM Regera o WaspFiber.exe a partir do waspfiber.py (opcional - o .exe
REM ja vem pronto). Precisa de Python instalado com "Add Python to PATH".
setlocal
cd /d "%~dp0"
python -m pip install pyinstaller || goto :erro
python -m PyInstaller --noconfirm --onefile --windowed --name WaspFiber --icon waspfiber.ico ^
  --hidden-import waspfiber_ui --hidden-import waspfiber_icones ^
  --exclude-module matplotlib --exclude-module numpy --exclude-module PIL waspfiber.py || goto :erro
echo.
echo Pronto: dist\WaspFiber.exe
pause
exit /b 0
:erro
echo.
echo Falhou - leia a mensagem acima.
pause
exit /b 1
