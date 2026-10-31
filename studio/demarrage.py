"""Démarrage automatique du moteur musical avec le studio, et arrêt propre.

Le moteur ACE-Step tourne en arrière-plan, sans fenêtre. Sous Windows, il est rattaché
au studio par un « job » : si le studio se ferme (même brutalement), le moteur s'arrête aussi.
"""
import os
import socket
import subprocess
import sys

from config import DOSSIER_MOTEURS, RACINE

DOSSIER_ACESTEP = DOSSIER_MOTEURS / "ACE-Step-1.5"
JOURNAL_MOTEUR = RACINE / "logs" / "moteur_musical.log"
_processus = None
_job = None


def port_occupe(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def carte_ancienne() -> bool:
    """Vraie pour les cartes NVIDIA d'avant 2020 (T4, GTX 10xx/16xx, RTX 20xx) : pas de demi-précision fiable."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=10)
        return any(float(x) < 8.0 for x in r.stdout.split())
    except Exception:
        return False


def environnement():
    env = dict(os.environ)
    if carte_ancienne():  # T4, GTX… : réglages sûrs pour le moteur musical
        env.setdefault("ACESTEP_DTYPE", "float32")             # sinon son vide (NaN)
        env.setdefault("ACESTEP_OFFLOAD_TO_CPU", "true")       # float32 prend 2x plus de mémoire
        env.setdefault("ACESTEP_USE_FLASH_ATTENTION", "false") # non prise en charge avant 2020
        env.setdefault("ACESTEP_LM_BACKEND", "pt")             # moteur de texte standard (vllm exige une carte récente)
        env.setdefault("ACESTEP_LM_MODEL_PATH", "acestep-5Hz-lm-0.6B")  # le plus léger, plus rapide
    env.setdefault("UV_CACHE_DIR", str(RACINE / "cache" / "uv"))
    env.setdefault("UV_PYTHON_INSTALL_DIR", str(RACINE / "outils" / "python"))
    env.setdefault("HF_HOME", str(RACINE / "cache" / "huggingface"))
    env.setdefault("TORCH_HOME", str(RACINE / "cache" / "torch"))
    env.setdefault("ACESTEP_INIT_LLM", "auto")
    env["PYTHONIOENCODING"] = "utf-8"
    env["MPLBACKEND"] = "Agg"  # Kaggle/Jupyter imposent un réglage incompatible avec les moteurs
    env["PATH"] = str(RACINE / "outils" / "ffmpeg") + os.pathsep + env.get("PATH", "")
    if os.environ.get("BMS_GPU_MUSIQUE"):  # en ligne (2 cartes) : le moteur musical a sa propre carte
        env["CUDA_VISIBLE_DEVICES"] = os.environ["BMS_GPU_MUSIQUE"]
    return env


def _rattacher_au_studio(pid):
    """Windows : le moteur est tué automatiquement quand le studio se termine."""
    global _job
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class LIMITES_BASE(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class COMPTEURS_IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("a", "b", "c", "d", "e", "f")]

    class LIMITES_ETENDUES(ctypes.Structure):
        _fields_ = [("Base", LIMITES_BASE), ("Io", COMPTEURS_IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    job = k32.CreateJobObjectW(None, None)
    info = LIMITES_ETENDUES()
    info.Base.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
    proc = k32.OpenProcess(0x0001 | 0x0100, False, pid)  # TERMINATE | SET_QUOTA
    k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(proc))
    _job = job  # garder la référence : le job se ferme avec le studio


def demarrer_moteur_musical():
    """Lance ACE-Step s'il ne tourne pas déjà. Retourne True si lancé ou déjà actif."""
    global _processus
    if port_occupe(8001):
        return True
    uv = RACINE / "outils" / "uv" / ("uv.exe" if os.name == "nt" else "uv")
    if not uv.exists() or not DOSSIER_ACESTEP.exists():
        return False
    JOURNAL_MOTEUR.parent.mkdir(exist_ok=True)
    sortie = open(JOURNAL_MOTEUR, "w", encoding="utf-8", errors="replace")
    options = {"creationflags": 0x08000000} if os.name == "nt" else {}  # sans fenêtre
    _processus = subprocess.Popen(
        [str(uv), "run", "--no-sync", "acestep-api", "--host", "127.0.0.1", "--port", "8001"],
        cwd=DOSSIER_ACESTEP, env=environnement(), stdout=sortie, stderr=subprocess.STDOUT, **options)
    try:
        _rattacher_au_studio(_processus.pid)
    except Exception as e:  # sans gravité : le bouton « Fermer le studio » arrête aussi le moteur
        print("Rattachement du moteur impossible :", e)
    return True


def arreter_moteur_musical():
    if _processus and _processus.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(_processus.pid), "/T", "/F"], capture_output=True)
        else:
            _processus.terminate()


def derniere_ligne_moteur() -> str:
    """Dernière ligne utile du journal du moteur (pour suivre le premier téléchargement)."""
    try:
        lignes = JOURNAL_MOTEUR.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for ligne in reversed(lignes):
        ligne = ligne.strip()
        if ligne:
            return ligne[-160:]
    return ""


def rediriger_sorties_si_sans_console():
    """Lancé sans fenêtre (pythonw) : les messages vont dans logs/studio.log."""
    if sys.stdout is None or sys.stderr is None:
        (RACINE / "logs").mkdir(exist_ok=True)
        f = open(RACINE / "logs" / "studio.log", "a", encoding="utf-8", errors="replace", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f
