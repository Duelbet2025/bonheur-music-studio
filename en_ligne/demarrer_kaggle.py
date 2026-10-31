"""Bonheur Music Studio — démarrage complet sur Kaggle (cartes graphiques gratuites).

Appelé par la cellule unique du notebook Kaggle, avec CLE (clé d'accès privée) et CANAL (canal
privé ntfy.sh par lequel la page de lancement de l'utilisateur reçoit le lien du studio).
Étapes : vérifications, installation des moteurs, lancement du studio web, lien public protégé,
puis attente jusqu'à « Fermer le studio » (ou 50 min sans activité, ou 11 h 40).
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

CODE = Path(BMS_CODE)          # noqa: F821  (dossier du dépôt, fourni par la cellule)
CLE = BMS_CLE                  # noqa: F821
CANAL = BMS_CANAL              # noqa: F821
RACINE = Path("/kaggle/tmp/bms") if Path("/kaggle").exists() else Path("/tmp/bms")
SORTIES = Path("/kaggle/working") if Path("/kaggle/working").exists() else RACINE / "sorties"
LOGS = RACINE / "logs"
DEBUT = time.time()
DUREE_MAX = 11 * 3600 + 40 * 60  # Kaggle coupe à 12 h
CU128 = "https://download.pytorch.org/whl/cu128"
for d in (RACINE, LOGS, SORTIES):
    d.mkdir(parents=True, exist_ok=True)


def signal(msg, titre=None):
    """Envoie un message à la page de lancement (et l'affiche ici)."""
    print(msg, flush=True)
    try:
        req = urllib.request.Request(f"https://ntfy.sh/{CANAL}", data=msg.encode("utf-8"), method="POST")
        if titre:
            req.add_header("Title", titre)
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        print("   (message non transmis :", e, ")", flush=True)


def lancer(cmd, nom, cwd=None, env=None):
    journal = LOGS / f"installation_{nom}.log"
    with open(journal, "w") as f:
        r = subprocess.run(cmd, shell=True, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        fin = "".join(journal.read_text(errors="replace").splitlines(True)[-20:])
        print(fin)
        signal(f"ERREUR installation « {nom} » :\n{fin[-1500:]}")
        raise RuntimeError(f"Échec de l'étape « {nom} ». Relancez ; si l'erreur revient, montrez ce message à Claude.")


def etape(n, total, texte):
    signal(f"ETAT {n}/{total} {texte}")


def espace():
    try:
        u = shutil.disk_usage(RACINE)
        return f"{u.free / 1e9:.0f} Go libres"
    except Exception:
        return "?"


TOTAL = 7
# ---------------------------------------------------------------- 1. vérifications
etape(1, TOTAL, "Vérification de la carte graphique et d'internet")
gpu = subprocess.run("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader", shell=True,
                     capture_output=True, text=True).stdout.strip()
if not gpu:
    signal("ERREUR Pas de carte graphique : Settings ▸ Accelerator ▸ GPU T4 x2, puis relancez.")
    raise SystemExit("Pas de carte graphique.")
if "P100" in gpu:
    signal("ERREUR Carte P100 incompatible : Settings ▸ Accelerator ▸ GPU T4 x2.")
    raise SystemExit("P100 incompatible.")
NB_GPU = len(gpu.splitlines())
print("   Cartes :", gpu.replace("\n", " | "), "—", espace(), flush=True)

# ---------------------------------------------------------------- 2. fichiers du studio
etape(2, TOTAL, "Fichiers du studio")
shutil.rmtree(RACINE / "studio", ignore_errors=True)
shutil.copytree(CODE / "studio", RACINE / "studio")
(SORTIES / "commandes").mkdir(exist_ok=True)
env = dict(os.environ, UV_CACHE_DIR=str(RACINE / "cache/uv"), UV_PYTHON_INSTALL_DIR=str(RACINE / "outils/python"),
           UV_LINK_MODE="copy", HF_HOME=str(RACINE / "cache/huggingface"), TORCH_HOME=str(RACINE / "cache/torch"),
           MPLBACKEND="Agg")

# ---------------------------------------------------------------- 3. outils système
etape(3, TOTAL, "Outils système")
lancer("apt-get update -qq && apt-get install -y -qq portaudio19-dev ffmpeg psmisc", "apt")
lancer(f"{sys.executable} -m pip install -q --no-cache-dir uv faster-whisper flask requests", "pip_noyau")
uv_dest = RACINE / "outils/uv/uv"
uv_dest.parent.mkdir(parents=True, exist_ok=True)
shutil.copy(shutil.which("uv") or Path(sys.executable).parent / "uv", uv_dest)
UV = str(uv_dest)

# le moteur « le chanteur chante et danse » s'installe en parallèle (il ne bloque pas le studio)
ETAT_PERF = RACINE / "etat_performance.txt"
ETAT_PERF.write_text("en attente", encoding="utf-8")
perf = subprocess.Popen([sys.executable, str(RACINE / "studio/moteurs_video/installer_performance.py"),
                         str(RACINE / "moteurs/EchoMimicV3"), str(ETAT_PERF), UV], env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ---------------------------------------------------------------- 4. moteur musical
etape(4, TOTAL, "Moteur musical ACE-Step 1.5 (le plus long, ~8 min)")
ace = RACINE / "moteurs/ACE-Step-1.5"
if not (ace / "pyproject.toml").exists():
    lancer(f"git clone -q --depth 1 https://github.com/ace-step/ACE-Step-1.5.git {ace}", "acestep_git")
lancer(f"{UV} sync -q", "acestep_sync", cwd=ace, env=env)

# ---------------------------------------------------------------- 5. voix
etape(5, TOTAL, "Moteur de voix (Applio)")
applio = RACINE / "moteurs/Applio"
if not (applio / "core.py").exists():
    lancer(f"git clone -q --depth 1 https://github.com/IAHispano/Applio.git {applio}", "applio_git")
if not (applio / "env/bin/python").exists():
    lancer(f"{UV} venv env --python 3.12 --seed -q", "applio_venv", cwd=applio, env=env)
lancer(f"{UV} pip install -q --python env/bin/python -r requirements.txt --extra-index-url {CU128} "
       f"--index-strategy unsafe-best-match", "applio_pip", cwd=applio, env=env)
lancer("env/bin/python core.py prerequisites --models --exe --pretraineds-hifigan", "applio_modeles",
       cwd=applio, env=env)

# ---------------------------------------------------------------- 6. séparation
etape(6, TOTAL, "Séparation voix / musique (Demucs)")
sep = RACINE / "env_separation"
if not (sep / "bin/python").exists():
    lancer(f"{UV} venv {sep} --python 3.11 -q", "sep_venv", env=env)
lancer(f"{UV} pip install -q --python {sep}/bin/python torch==2.7.1 torchaudio==2.7.1 demucs==4.0.1 soundfile "
       f"--extra-index-url {CU128} --index-strategy unsafe-best-match", "sep_pip", env=env)
subprocess.run([UV, "cache", "clean"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ---------------------------------------------------------------- 7. lancement du studio
etape(7, TOTAL, "Lancement du studio")
env_studio = dict(env, BMS_EN_LIGNE="1", BMS_CLE=CLE, BMS_COMMANDES=str(SORTIES / "commandes"),
                  BMS_ECHOMIMIC=str(RACINE / "moteurs/EchoMimicV3"), BMS_ETAT_PERFORMANCE=str(ETAT_PERF),
                  BMS_PYTHON_SEPARATION=str(sep / "bin/python"), ACESTEP_DTYPE="float32", PYTHONUNBUFFERED="1")
if NB_GPU >= 2:  # carte 0 : musique ; carte 1 : voix, séparation, karaoké, chant/danse
    env_studio.update(BMS_GPU_MUSIQUE="0", CUDA_VISIBLE_DEVICES="1")
journal_studio = open(LOGS / "studio.log", "a")
studio = subprocess.Popen([sys.executable, "serveur.py", "--sans-navigateur"], cwd=RACINE / "studio",
                          env=env_studio, stdout=journal_studio, stderr=subprocess.STDOUT)
for _ in range(60):
    time.sleep(2)
    try:
        urllib.request.urlopen("http://127.0.0.1:7870/", timeout=3)
    except urllib.error.HTTPError:
        break  # 401 : le studio répond (il demande la clé)
    except Exception:
        if studio.poll() is not None:
            break
        continue
    break
if studio.poll() is not None:
    fin = (LOGS / "studio.log").read_text(errors="replace")[-1500:]
    signal("ERREUR Le studio n'a pas démarré :\n" + fin)
    raise RuntimeError(fin)


# ---------------------------------------------------------------- lien public protégé
def tunnel_gradio():
    tun = RACINE / "env_tunnel"
    if not (tun / "bin/python").exists():
        lancer(f"{UV} venv {tun} --python 3.11 -q", "tunnel_venv", env=env)
        lancer(f"{UV} pip install -q --python {tun}/bin/python gradio==4.44.1", "tunnel_pip", env=env)
    code = ("import secrets,time\nfrom gradio import networking\n"
            "print(networking.setup_tunnel('127.0.0.1',7870,secrets.token_urlsafe(32),None),flush=True)\n"
            "while True: time.sleep(3600)\n")
    p = subprocess.Popen([str(tun / "bin/python"), "-c", code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True)
    minuteur = threading.Timer(150, p.kill)
    minuteur.start()
    for ligne in p.stdout:
        print("   [lien]", ligne.rstrip()[:150], flush=True)
        m = re.search(r"https://[a-z0-9.-]+\.gradio\.live", ligne)
        if m:
            minuteur.cancel()
            threading.Thread(target=lambda: [None for _ in p.stdout], daemon=True).start()
            return p, m.group(0)
    p.kill()
    raise RuntimeError("lien gradio indisponible")


def tunnel_cloudflare():
    cf = RACINE / "outils/cloudflared"
    if not cf.exists():
        urllib.request.urlretrieve("https://github.com/cloudflare/cloudflared/releases/latest/download/"
                                   "cloudflared-linux-amd64", cf)
        cf.chmod(0o755)
    p = subprocess.Popen([str(cf), "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:7870"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    minuteur = threading.Timer(120, p.kill)
    minuteur.start()
    for ligne in p.stdout:
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", ligne)
        if m:
            minuteur.cancel()
            threading.Thread(target=lambda: [None for _ in p.stdout], daemon=True).start()
            return p, m.group(0)
    p.kill()
    raise RuntimeError("lien cloudflare indisponible")


def ouvrir_tunnel():
    for fabrique in (tunnel_gradio, tunnel_cloudflare):
        try:
            return fabrique()
        except Exception as e:
            print("   lien :", fabrique.__name__, "a échoué :", e, flush=True)
    return None, None


tunnel, lien = ouvrir_tunnel()
if not lien:
    signal("ERREUR Impossible de créer le lien du studio (gradio et cloudflare refusés).")
    raise RuntimeError("pas de lien")
signal(f"LIEN {lien}", titre="Studio prêt")
print(f"\n✅ STUDIO EN LIGNE : ouvrez votre page « Bonheur Music Studio » (elle s'ouvre toute seule).\n"
      f"   Lien direct (privé) : {lien}/?cle={CLE}\n", flush=True)

# ---------------------------------------------------------------- surveillance
dernier_envoi, etat_perf_signale = time.time(), ""
while studio.poll() is None:
    time.sleep(20)
    if tunnel is not None and tunnel.poll() is not None:  # lien tombé : on en refait un
        tunnel, nouveau = ouvrir_tunnel()
        if nouveau:
            lien = nouveau
            signal(f"LIEN {lien}", titre="Nouveau lien du studio")
    try:
        etat_perf = ETAT_PERF.read_text(encoding="utf-8").strip()
    except OSError:
        etat_perf = ""
    if etat_perf != etat_perf_signale:
        etat_perf_signale = etat_perf
        print("   moteur chant/danse :", etat_perf, flush=True)
    if time.time() - dernier_envoi > 600:  # rappel régulier du lien pour la page de lancement
        signal(f"LIEN {lien}")
        dernier_envoi = time.time()
    if time.time() - DEBUT > DUREE_MAX:
        signal("ETAT Fin de session Kaggle proche : téléchargez vos livraisons.")
        time.sleep(600)
        studio.terminate()
        break

signal("FERME", titre="Studio fermé")
for p in (tunnel, perf):
    try:
        p.kill()
    except Exception:
        pass
subprocess.run("pkill -f acestep-api", shell=True)
print("Studio fermé. Les commandes sont dans Output ▸ commandes.", flush=True)
