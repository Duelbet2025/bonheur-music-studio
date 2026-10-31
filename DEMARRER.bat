@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Bonheur Music Studio

rem ---- Premiere fois : installation automatique ----
if not exist "installation\INSTALLE.txt" (
    call "installation\installer.bat"
    if not exist "installation\INSTALLE.txt" exit /b 1
)

rem ---- Une seule fois : proposer un raccourci sur le Bureau ----
if not exist "installation\RACCOURCI_PROPOSE.txt" (
    echo.> "installation\RACCOURCI_PROPOSE.txt"
    echo.
    set /p RACC="Creer un raccourci Bonheur Music Studio sur le Bureau ? (O/N) : "
    if /i "!RACC!"=="O" (
        powershell -NoProfile -Command "$b=[Environment]::GetFolderPath('Desktop'); $r=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $b 'Bonheur Music Studio.lnk')); $r.TargetPath='%~dp0DEMARRER.bat'; $r.WorkingDirectory='%~dp0'; $r.IconLocation='%~dp0studio\interface\icone.ico'; $r.WindowStyle=7; $r.Save()"
        echo   Raccourci cree sur le Bureau.
    )
)

rem ---- Ouvrir le studio (sans fenetre noire) ----
if not exist "env_studio\Scripts\pythonw.exe" (
    echo Installation incomplete : supprimez installation\INSTALLE.txt puis relancez DEMARRER.bat
    pause
    exit /b 1
)
start "" "env_studio\Scripts\pythonw.exe" "studio\serveur.py"
exit /b 0
