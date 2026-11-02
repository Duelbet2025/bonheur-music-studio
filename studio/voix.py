"""Voix du client : entraînement d'un modèle vocal et conversion avec Applio (RVC, licence MIT).

Le modèle de chaque client est gardé dans « voix_clients/<nom> » pour être réutilisé
quand le client revient (pas besoin de réentraîner).
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from config import DOSSIER_APPLIO, DOSSIER_VOIX
from outils import convertir_audio
from separation import separer


class ErreurVoix(Exception):
    pass


def _python_applio() -> Path:
    for candidat in (DOSSIER_APPLIO / "env" / "Scripts" / "python.exe", DOSSIER_APPLIO / "env" / "python.exe",
                     DOSSIER_APPLIO / "env" / "bin" / "python",
                     DOSSIER_APPLIO / ".venv" / "Scripts" / "python.exe",
                     DOSSIER_APPLIO / ".venv" / "bin" / "python"):
        if candidat.exists():
            return candidat
    raise ErreurVoix("Applio n'est pas installé. Relancez « installer.bat ».")


def _applio(args, journal):
    cmd = [str(_python_applio()), "core.py", *map(str, args)]
    journal("Applio : " + args[0])
    proc = subprocess.Popen(cmd, cwd=DOSSIER_APPLIO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    derniers = []
    for ligne in proc.stdout:
        ligne = ligne.rstrip()
        if not ligne:
            continue
        derniers = (derniers + [ligne])[-30:]
        m = re.search(r"epoch=(\d+)", ligne)
        if m:  # une ligne toutes les 25 époques (sinon le journal est noyé)
            if "time=" in ligne and int(m.group(1)) % 25 == 0:
                journal("   " + ligne[:160])
        elif re.search(r"Saved|saved|index|completed|Lowest|Error|error", ligne):
            journal("   " + ligne[:160])
    if proc.wait() != 0:
        raise ErreurVoix("Applio a échoué :\n" + "\n".join(derniers))


def nom_modele(nom_client: str) -> str:
    import unicodedata
    ascii_ = unicodedata.normalize("NFKD", nom_client.strip()).encode("ascii", "ignore").decode()
    propre = re.sub(r"[^A-Za-z0-9_-]+", "_", ascii_).strip("_") or "client"
    return f"bms_{propre.lower()}"


def modele_existant(nom_client: str):
    """Retourne (pth, index) si le client a déjà un modèle vocal, sinon None."""
    dossier = DOSSIER_VOIX / nom_modele(nom_client)
    pth, index = dossier / "voix.pth", dossier / "voix.index"
    if pth.exists() and index.exists():
        return pth, index
    return None


def entrainer_voix(nom_client: str, enregistrements, epoques: int, nettoyer=True, journal=print):
    """Entraîne le modèle vocal du client à partir de ses enregistrements.

    Durée conseillée : 5 à 10 minutes de chant (ou de parole) sans musique.
    """
    modele = nom_modele(nom_client)
    dossier_client = DOSSIER_VOIX / modele
    jeu = dossier_client / "enregistrements"
    jeu.mkdir(parents=True, exist_ok=True)

    for i, source in enumerate(enregistrements, start=1):
        source = Path(source)
        brut = jeu / f"brut_{i}.wav"
        convertir_audio(source, brut, frequence=44100, mono=True)
        if nettoyer:
            # Retire la musique ou le bruit de fond : on ne garde que la voix.
            pistes = separer(brut, jeu / "_nettoyage", journal=journal)
            shutil.move(str(pistes["voix"]), jeu / f"voix_{i}.wav")
            shutil.rmtree(jeu / "_nettoyage", ignore_errors=True)
            brut.unlink(missing_ok=True)
        else:
            brut.rename(jeu / f"voix_{i}.wav")

    frequence = "40000"
    sauvegarde = max(1, min(100, epoques // 5))
    journal(f"Entraînement de la voix de {nom_client} ({epoques} époques). Cela peut prendre 20 à 90 minutes…")
    _applio(["preprocess", "--model-name", modele, "--dataset-path", jeu.resolve(),
             "--sample-rate", frequence, "--cut-preprocess", "Automatic"], journal)
    _applio(["extract", "--model-name", modele, "--sample-rate", frequence,
             "--f0-method", "rmvpe", "--gpu", "0"], journal)
    _applio(["train", "--model-name", modele, "--sample-rate", frequence,
             "--total-epoch", epoques, "--save-every-epoch", sauvegarde,
             "--save-only-latest", "--batch-size", 8, "--gpu", "0"], journal)

    # Récupère le dernier modèle produit dans Applio/logs/<modele>/
    dossier_logs = DOSSIER_APPLIO / "logs" / modele
    poids = sorted(dossier_logs.glob(f"{modele}_*e_*s.pth"), key=lambda p: p.stat().st_mtime)
    index = list(dossier_logs.glob(f"{modele}.index")) or list(dossier_logs.glob("*.index"))
    if not poids or not index:
        raise ErreurVoix("Le modèle vocal n'a pas été trouvé après l'entraînement.")
    shutil.copy(poids[-1], dossier_client / "voix.pth")
    shutil.copy(index[0], dossier_client / "voix.index")
    (dossier_client / "infos.json").write_text(
        json.dumps({"client": nom_client, "epoques": epoques}, ensure_ascii=False, indent=2), encoding="utf-8")
    journal("Modèle vocal prêt et enregistré pour les prochaines commandes.")
    return dossier_client / "voix.pth", dossier_client / "voix.index"


def convertir_voix(voix_ia: Path, sortie: Path, pth: Path, index: Path, transposition=0, journal=print,
                   genre="Homme"):
    """Remplace la voix chantée par l'IA par la voix du client.

    - hauteur adaptée automatiquement à la tessiture du client (« proposed pitch ») ;
    - index plus présent (timbre plus fidèle), consonnes et souffles protégés ;
    - enveloppe de volume en partie celle de l'original (phrasé naturel), légère correction de justesse.
    """
    args = ["infer", "--input-path", voix_ia.resolve(), "--output-path", sortie.resolve(),
            "--pth-path", pth.resolve(), "--index-path", index.resolve(),
            "--pitch", int(transposition), "--f0-method", "rmvpe",
            "--index-rate", 0.75, "--protect", 0.4, "--volume-envelope", 0.6,
            "--f0-autotune", "--f0-autotune-strength", 0.3, "--export-format", "WAV"]
    if int(transposition) == 0:  # pas de réglage manuel : l'outil cale la hauteur sur la voix du client
        args += ["--proposed-pitch", "--proposed-pitch-threshold", 155.0 if genre == "Homme" else 255.0]
    try:
        _applio(args, journal)
    except ErreurVoix:  # ancienne version d'Applio : réglages de base
        _applio(["infer", "--input-path", voix_ia.resolve(), "--output-path", sortie.resolve(),
                 "--pth-path", pth.resolve(), "--index-path", index.resolve(), "--pitch", int(transposition),
                 "--f0-method", "rmvpe", "--index-rate", 0.75, "--protect", 0.4, "--export-format", "WAV"], journal)
    if not sortie.exists():
        raise ErreurVoix("La conversion de voix n'a pas produit de fichier.")
    return sortie
