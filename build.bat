@echo off
REM Builds a single Sama.exe (run on Windows). Needs: pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --onefile --windowed --name Sama --add-data "sama\ui;sama\ui" sama\__main__.py
