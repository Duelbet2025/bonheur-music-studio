"""Modules vidéo IA facultatifs (installés seulement si la carte graphique le permet).

- Animation des photos : Wan 2.2 TI2V-5B (Apache 2.0), environnement « env_video ».
- Synchro des lèvres : MuseTalk 1.5 (MIT, modèles utilisables commercialement), dans « moteurs/MuseTalk ».
- Performance (le chanteur chante avec lèvres + gestes, ou danse) : EchoMimicV3-Flash (Apache 2.0),
  dans « moteurs/EchoMimicV3 » (version en ligne, cartes NVIDIA de 12 Go et plus).
Si un module manque ou échoue, le clip est fait avec l'animation classique : rien n'est bloqué.
"""
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from config import DOSSIER_MOTEURS, RACINE
from outils import lancer_ffmpeg

PY_VIDEO = RACINE / "env_video" / "Scripts" / "python.exe"
DOSSIER_MUSETALK = DOSSIER_MOTEURS / "MuseTalk"
PY_MUSETALK = DOSSIER_MUSETALK / "env" / "Scripts" / "python.exe"
DOSSIER_FFMPEG = RACINE / "outils" / "ffmpeg"
SCRIPT_ANIMATION = Path(__file__).resolve().parent / "moteurs_video" / "animer_photos.py"
SCRIPT_PERFORMANCE = Path(__file__).resolve().parent / "moteurs_video" / "performance.py"
DOSSIER_ECHOMIMIC = Path(os.environ.get("BMS_ECHOMIMIC") or DOSSIER_MOTEURS / "EchoMimicV3")


def _python_echomimic():
    for p in (os.environ.get("BMS_PYTHON_ECHOMIMIC"), DOSSIER_ECHOMIMIC / "env" / "bin" / "python",
              DOSSIER_ECHOMIMIC / "env" / "Scripts" / "python.exe"):
        if p and Path(p).exists():
            return Path(p)
    return None


def performance_disponible() -> bool:
    return _python_echomimic() is not None and (DOSSIER_ECHOMIMIC / "PRET.json").exists()


def generer_performances(taches, dossier: Path, journal=print, delai_max=None):
    """Fabrique les plans où la personne chante ou danse.

    taches : liste de dicts {cle, image, audio, prompt, graine}. Retourne {cle: vidéo mp4 sans son}.
    """
    if not taches or not performance_disponible():
        return {}
    import json
    import time
    dossier.mkdir(parents=True, exist_ok=True)
    modeles = json.loads((DOSSIER_ECHOMIMIC / "PRET.json").read_text(encoding="utf-8"))
    fin = time.time() + delai_max if delai_max else None
    liste = []
    for k, t in enumerate(taches):
        liste.append({**{c: str(v) for c, v in t.items() if c != "cle"},
                      "sortie": str((dossier / f"perf_{k:02d}.mp4").resolve()), "fin_avant": fin})
    fichier = dossier / "taches_performance.json"
    fichier.write_text(json.dumps({"modeles": modeles, "taches": liste}, ensure_ascii=False), encoding="utf-8")
    journal(f"Le chanteur prend vie : {len(liste)} plan(s) chantés / dansés par l'IA "
            f"(quelques minutes par plan)…")
    code, derniers = _executer([_python_echomimic(), SCRIPT_PERFORMANCE, fichier], DOSSIER_ECHOMIMIC, journal)
    if code != 0:
        journal("Moteur de performance arrêté (" + (derniers[-1] if derniers else "erreur") +
                ") : les plans manquants sont faits avec les photos.")
    resultats = {}
    for t, l in zip(taches, liste):
        f = Path(l["sortie"])
        if f.exists() and f.stat().st_size > 10_000:
            resultats[t["cle"]] = f
    return resultats


def animation_disponible() -> bool:
    # le fichier PRET.txt est écrit par l'installateur seulement si tout s'est bien passé
    return PY_VIDEO.exists() and (RACINE / "env_video" / "PRET.txt").exists()


def levres_disponible() -> bool:
    return PY_MUSETALK.exists() and (DOSSIER_MUSETALK / "PRET.txt").exists()


def _environnement():
    env = dict(os.environ)
    env["PATH"] = str(DOSSIER_FFMPEG) + os.pathsep + env.get("PATH", "")
    env.setdefault("HF_HOME", str(RACINE / "cache" / "huggingface"))
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _executer(cmd, cwd, journal, filtre=("PROGRES", "OK", "ECHEC", "Error", "error")):
    proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=_environnement(), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    derniers = []
    for ligne in proc.stdout:
        ligne = ligne.rstrip()
        if ligne:
            derniers = (derniers + [ligne])[-25:]
            if any(m in ligne for m in filtre):
                journal("   " + ligne[:180])
    return proc.wait(), derniers


def boucle_aller_retour(video: Path, sortie: Path):
    """Lecture aller puis retour : la vidéo peut tourner en boucle sans saut visible."""
    lancer_ffmpeg(["-i", video, "-filter_complex", "[0:v]split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1[v]",
                   "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", 18,
                   "-pix_fmt", "yuv420p", sortie], "Boucle vidéo")
    return sortie


# ---------------------------------------------------------------------------
# Animation IA des photos
# ---------------------------------------------------------------------------
def animer_photos(photos, description, dossier: Path, journal=print, secondes=3, pas=30):
    """Retourne {photo: vidéo en boucle} pour les photos réussies."""
    if not animation_disponible() or not photos:
        return {}
    dossier.mkdir(parents=True, exist_ok=True)
    prompt = ("A music video shot. The person in the photo moves naturally to the music, sways gently, "
              "smiles, blinks, hair and clothes move slightly, subtle camera motion, cinematic lighting, "
              "high quality, realistic. " + (description or ""))
    taches = [{"photo": str(Path(p).resolve()), "sortie": str((dossier / f"anim_{i}.mp4").resolve())}
              for i, p in enumerate(photos)]
    import json
    fichier = dossier / "taches_animation.json"
    fichier.write_text(json.dumps({"prompt": prompt, "taches": taches, "secondes": secondes, "pas": pas},
                                  ensure_ascii=False), encoding="utf-8")
    journal(f"Animation IA de {len(taches)} photo(s) : 3 à 10 minutes par photo selon la carte graphique…")
    code, derniers = _executer([PY_VIDEO, SCRIPT_ANIMATION, fichier], SCRIPT_ANIMATION.parent, journal)
    if code != 0:
        journal("Animation IA indisponible (" + (derniers[-1] if derniers else "erreur") +
                ") : animation classique utilisée.")
    resultats = {}
    for p, t in zip(photos, taches):
        brut = Path(t["sortie"])
        if brut.exists() and brut.stat().st_size > 10_000:
            resultats[Path(p)] = boucle_aller_retour(brut, brut.with_name(brut.stem + "_boucle.mp4"))
    journal(f"{len(resultats)} photo(s) animée(s) par l'IA.")
    return resultats


# ---------------------------------------------------------------------------
# Synchro des lèvres
# ---------------------------------------------------------------------------
def synchro_levres(photo_visage: Path, voix: Path, segments, journal=print):
    """Fait chanter le visage du client sur chaque segment (début, fin) de la piste voix.

    Retourne {index_segment: vidéo}. MuseTalk lance FFmpeg sans guillemets : on travaille
    donc dans un sous-dossier au nom simple, à l'intérieur du dossier MuseTalk.
    """
    if not levres_disponible() or not segments:
        return {}
    ident = uuid.uuid4().hex[:8]
    relatif = Path("bms_travail") / ident
    atelier = DOSSIER_MUSETALK / relatif
    atelier.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageOps
        img = ImageOps.exif_transpose(Image.open(photo_visage)).convert("RGB")
        img.thumbnail((1280, 1280))
        img.save(atelier / "visage.png")

        lignes_yaml = []
        for i, (debut, fin) in enumerate(segments):
            lancer_ffmpeg(["-ss", f"{debut:.3f}", "-t", f"{fin - debut:.3f}", "-i", voix,
                           "-ac", 1, "-ar", 16000, atelier / f"seg_{i:02d}.wav"], "Découpe voix")
            lignes_yaml += [f"task_{i}:",
                            f' video_path: "{(relatif / "visage.png").as_posix()}"',
                            f' audio_path: "{(relatif / f"seg_{i:02d}.wav").as_posix()}"',
                            f' result_name: "levres_{i:02d}.mp4"']
        (atelier / "taches.yaml").write_text("\n".join(lignes_yaml) + "\n", encoding="utf-8")

        journal(f"Synchro des lèvres sur {len(segments)} passage(s) chanté(s)…")
        cmd = [PY_MUSETALK, "-m", "scripts.inference",
               "--inference_config", (relatif / "taches.yaml").as_posix(),
               "--result_dir", (relatif / "resultats").as_posix(),
               "--unet_model_path", "models/musetalkV15/unet.pth",
               "--unet_config", "models/musetalkV15/musetalk.json",
               "--version", "v15", "--ffmpeg_path", str(DOSSIER_FFMPEG), "--use_float16"]
        code, derniers = _executer(cmd, DOSSIER_MUSETALK, journal, filtre=("Results saved", "Error", "error"))
        resultats = {}
        for i in range(len(segments)):
            f = atelier / "resultats" / "v15" / f"levres_{i:02d}.mp4"
            if f.exists() and f.stat().st_size > 10_000:
                resultats[i] = f
        if not resultats:
            journal("Synchro des lèvres impossible (visage non détecté ou erreur) : "
                    + (derniers[-1] if derniers else "") + " — clip fait sans.")
        return resultats
    except Exception as e:
        journal(f"Synchro des lèvres impossible : {e} — clip fait sans.")
        return {}


def nettoyer_levres(resultats, dossier_dest: Path):
    """Déplace les vidéos produites hors du dossier MuseTalk et nettoie l'atelier."""
    dossier_dest.mkdir(parents=True, exist_ok=True)
    deplaces = {}
    ateliers = set()
    for i, f in resultats.items():
        cible = dossier_dest / f.name
        shutil.move(str(f), cible)
        deplaces[i] = cible
        ateliers.add(f.parents[2])
    for a in ateliers:
        shutil.rmtree(a, ignore_errors=True)
    return deplaces
