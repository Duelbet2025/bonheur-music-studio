@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Installation de Bonheur Music Studio
cd /d "%~dp0.."
set "RACINE=%cd%\"

echo.
echo  ==========================================================
echo     Installation de Bonheur Music Studio
echo  ==========================================================
echo   Tout est installe DANS ce dossier uniquement.
echo   Rien n'est installe ailleurs sur votre ordinateur.
echo   Duree : 1 a 3 heures selon votre connexion.
echo   Si la connexion coupe, relancez : l'installation reprend.
echo  ==========================================================
echo.

rem ---- Tout reste dans le dossier du studio ----
set "UV_INSTALL_DIR=%RACINE%outils\uv"
set "UV_NO_MODIFY_PATH=1"
set "UV_CACHE_DIR=%RACINE%cache\uv"
set "UV_PYTHON_INSTALL_DIR=%RACINE%outils\python"
set "UV_LINK_MODE=copy"
set "HF_HOME=%RACINE%cache\huggingface"
set "TORCH_HOME=%RACINE%cache\torch"
set "UV=%RACINE%outils\uv\uv.exe"
set "CU128=https://download.pytorch.org/whl/cu128"
if not exist "logs" mkdir logs

rem ---- 1. Carte graphique ----
echo [1/7] Carte graphique...
set VRAM=0
for /f "tokens=1" %%v in ('nvidia-smi --query-gpu^=memory.total --format^=csv^,noheader^,nounits 2^>nul') do if !VRAM! EQU 0 set VRAM=%%v
if !VRAM! EQU 0 (
    echo.
    echo   ATTENTION : aucune carte graphique NVIDIA detectee.
    echo   Le studio a besoin d'une carte NVIDIA ^(6 Go minimum conseilles^).
    echo.
    set /p CONTINUER="  Continuer quand meme ? (O/N) : "
    if /i not "!CONTINUER!"=="O" exit /b 1
) else (
    echo   Memoire de la carte : !VRAM! Mo
)

rem ---- 2. Outil d'installation uv (local) ----
echo.
echo [2/7] Outil d'installation...
if not exist "%UV%" powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
if not exist "%UV%" goto :erreur
if not exist "moteurs" mkdir moteurs

rem ---- 3. Moteur musical ACE-Step 1.5 ----
echo.
echo [3/7] Moteur musical (ACE-Step 1.5)...
call :telecharger "https://github.com/ace-step/ACE-Step-1.5/archive/refs/heads/main.zip" "ACE-Step-1.5-main" "ACE-Step-1.5" "pyproject.toml" || goto :erreur
pushd "moteurs\ACE-Step-1.5"
"%UV%" sync
if errorlevel 1 ( popd & goto :erreur )
popd

rem ---- 4. Moteur de voix Applio ----
echo.
echo [4/7] Moteur de voix (Applio)...
call :telecharger "https://github.com/IAHispano/Applio/archive/refs/heads/main.zip" "Applio-main" "Applio" "core.py" || goto :erreur
pushd "moteurs\Applio"
if not exist "env\Scripts\python.exe" "%UV%" venv env --python 3.12
"%UV%" pip install --python env\Scripts\python.exe -r requirements.txt --extra-index-url %CU128% --index-strategy unsafe-best-match
if errorlevel 1 ( popd & goto :erreur )
env\Scripts\python.exe core.py prerequisites
popd

rem ---- 5. Studio ----
echo.
echo [5/7] Studio (interface, separation, clips, karaoke)...
if not exist "env_studio\Scripts\python.exe" "%UV%" venv env_studio --python 3.12
"%UV%" pip install --python env_studio\Scripts\python.exe -r studio\requirements.txt --extra-index-url %CU128% --index-strategy unsafe-best-match
if errorlevel 1 goto :erreur
env_studio\Scripts\python.exe -c "import imageio_ffmpeg,shutil,os; os.makedirs('outils/ffmpeg',exist_ok=True); shutil.copy(imageio_ffmpeg.get_ffmpeg_exe(),'outils/ffmpeg/ffmpeg.exe')"

rem ---- 6. Synchro des levres (MuseTalk) : carte de 6 Go et plus ----
echo.
echo [6/7] Synchro des levres (formule Ultra)...
if !VRAM! LSS 6000 (
    echo   Carte trop petite : module ignore ^(le studio fonctionne sans^).
) else if exist "moteurs\MuseTalk\PRET.txt" (
    echo   Deja installe.
) else (
    call :musetalk > "logs\installation_musetalk.log" 2>&1
    if exist "moteurs\MuseTalk\PRET.txt" (echo   Installe.) else (echo   Echec : le studio fonctionne sans. Details : logs\installation_musetalk.log)
)

rem ---- 7. Animation IA des photos (Wan 2.2) : carte de 12 Go et plus ----
echo.
echo [7/7] Animation IA des photos (formules Pro et Ultra)...
if !VRAM! LSS 11000 (
    echo   Carte de moins de 12 Go : module ignore ^(les photos sont animees autrement^).
) else if exist "env_video\PRET.txt" (
    echo   Deja installe.
) else (
    echo   Telechargement d'environ 25 Go, patientez...
    call :animation > "logs\installation_animation.log" 2>&1
    if exist "env_video\PRET.txt" (echo   Installe.) else (echo   Echec : le studio fonctionne sans. Details : logs\installation_animation.log)
)

echo.
echo Liberation de l'espace des fichiers temporaires...
"%UV%" cache clean >nul 2>&1
echo.
echo  ==========================================================
echo   Installation terminee.
echo  ==========================================================
echo.> "installation\INSTALLE.txt"
exit /b 0

rem =====================================================================
:telecharger
rem %1 = adresse du zip, %2 = dossier dans le zip, %3 = nom final, %4 = fichier temoin
if exist "moteurs\%~3\%~4" exit /b 0
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%~1' -OutFile 'moteurs\%~3.zip'; Expand-Archive -Path 'moteurs\%~3.zip' -DestinationPath 'moteurs' -Force; Remove-Item 'moteurs\%~3.zip'; if (Test-Path 'moteurs\%~3') { Remove-Item -Recurse -Force 'moteurs\%~3' }; Rename-Item 'moteurs\%~2' '%~3'"
if exist "moteurs\%~3\%~4" exit /b 0
exit /b 1

:musetalk
call :telecharger "https://github.com/TMElyralab/MuseTalk/archive/refs/heads/main.zip" "MuseTalk-main" "MuseTalk" "README.md" || exit /b 1
pushd "moteurs\MuseTalk"
set "PYM=env\Scripts\python.exe"
if not exist "%PYM%" "%UV%" venv env --python 3.10
"%UV%" pip install --python %PYM% torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118 || (popd & exit /b 1)
"%UV%" pip install --python %PYM% diffusers==0.30.2 accelerate==0.28.0 numpy==1.23.5 opencv-python==4.9.0.80 soundfile==0.12.1 transformers==4.39.2 huggingface_hub==0.30.2 librosa==0.11.0 einops==0.8.1 omegaconf ffmpeg-python "imageio[ffmpeg]" requests tqdm || (popd & exit /b 1)
"%UV%" pip install --python %PYM% mmengine "mmcv==2.0.1" --find-links https://download.openmmlab.com/mmcv/dist/cu118/torch2.0/index.html || (popd & exit /b 1)
"%UV%" pip install --python %PYM% "mmdet==3.1.0" || (popd & exit /b 1)
"%UV%" pip install --python %PYM% --no-deps "mmpose==1.1.0" || (popd & exit /b 1)
"%UV%" pip install --python %PYM% json_tricks munkres xtcocotools matplotlib scipy || (popd & exit /b 1)
%PYM% "%RACINE%installation\telecharger_modeles_video.py" musetalk "%cd%" || (popd & exit /b 1)
%PYM% -c "import mmpose.apis, mmcv, torch; assert torch.cuda.is_available(); print('MuseTalk OK')" || (popd & exit /b 1)
echo ok> PRET.txt
popd
exit /b 0

:animation
if not exist "env_video\Scripts\python.exe" "%UV%" venv env_video --python 3.12
"%UV%" pip install --python env_video\Scripts\python.exe torch==2.7.1 torchvision==0.22.1 "diffusers>=0.35" "transformers>=4.51" accelerate ftfy sentencepiece protobuf "imageio[ffmpeg]" huggingface_hub pillow --extra-index-url %CU128% --index-strategy unsafe-best-match || exit /b 1
env_video\Scripts\python.exe "%RACINE%installation\telecharger_modeles_video.py" wan || exit /b 1
env_video\Scripts\python.exe -c "import torch; from diffusers import WanImageToVideoPipeline; assert torch.cuda.is_available(); print('Animation OK')" || exit /b 1
echo ok> "env_video\PRET.txt"
exit /b 0

:erreur
echo.
echo  !!! L'installation s'est arretee sur une erreur (voir ci-dessus).
echo  Verifiez votre connexion internet puis relancez DEMARRER.bat :
echo  l'installation reprendra la ou elle s'est arretee.
pause
exit /b 1
