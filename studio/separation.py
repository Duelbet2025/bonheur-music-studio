"""Séparation voix / musique avec Demucs (licence MIT)."""
import os
import shutil
import subprocess
import sys
from pathlib import Path


class ErreurSeparation(Exception):
    pass


def separer(fichier: Path, dossier_sortie: Path, quatre_pistes=False, journal=print, modele="htdemucs"):
    """Sépare un fichier audio.

    - deux pistes : voix + accompagnement
    - quatre pistes (Ultra) : voix, batterie, basse, autres instruments
    Retourne un dictionnaire {nom_piste: chemin}.
    """
    dossier_sortie.mkdir(parents=True, exist_ok=True)
    tmp = dossier_sortie / "_demucs"
    cmd = [os.environ.get("BMS_PYTHON_SEPARATION", sys.executable), "-m", "demucs", "-n", modele, "-o", str(tmp), "--float32"]
    if not quatre_pistes:
        cmd += ["--two-stems", "vocals"]
    cmd.append(str(fichier))
    journal(f"Séparation de la voix et de la musique ({fichier.name})…")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise ErreurSeparation(proc.stderr[-1500:])

    source = tmp / modele / fichier.stem
    noms = {"vocals": "voix", "no_vocals": "accompagnement", "drums": "batterie",
            "bass": "basse", "other": "instruments"}
    pistes = {}
    for f in source.glob("*.wav"):
        nom = noms.get(f.stem, f.stem)
        cible = dossier_sortie / f"{fichier.stem}_{nom}.wav"
        shutil.move(str(f), cible)
        pistes[nom] = cible
    shutil.rmtree(tmp, ignore_errors=True)
    if "voix" not in pistes:
        raise ErreurSeparation("La piste voix n'a pas été produite.")
    return pistes
