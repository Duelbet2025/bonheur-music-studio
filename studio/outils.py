"""Petits outils communs : FFmpeg, conversion audio, durée."""
import shutil
import subprocess
from pathlib import Path


def ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        chemin = shutil.which("ffmpeg")
        if not chemin:
            raise RuntimeError("FFmpeg est introuvable. Relancez « installer.bat ».")
        return chemin


def lancer_ffmpeg(args, description="FFmpeg"):
    cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"{description} a échoué : {proc.stderr[-1500:]}")


def convertir_audio(source: Path, cible: Path, frequence=44100, mono=False):
    args = ["-i", source, "-vn", "-ar", frequence]
    if mono:
        args += ["-ac", 1]
    lancer_ffmpeg([*args, cible], "Conversion audio")
    return cible


def duree_audio(fichier: Path) -> float:
    try:
        import soundfile as sf
        info = sf.info(str(fichier))
        return info.frames / info.samplerate
    except ImportError:
        import re
        sortie = subprocess.run([ffmpeg(), "-i", str(fichier)], capture_output=True, text=True,
                                encoding="utf-8", errors="replace").stderr
        h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", sortie).groups()
        return int(h) * 3600 + int(m) * 60 + float(s)
