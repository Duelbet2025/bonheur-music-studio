"""Bonheur Music Studio sur Modal : lien fixe, carte graphique puissante, données conservées.

Déployé automatiquement par GitHub Actions (.github/workflows/deployer_modal.yml) :
    modal deploy en_ligne/modal_app.py
- Image : tous les moteurs installés une fois pour toutes (ACE-Step, Applio, Demucs, EchoMimicV3, décors).
- Volume « bms-donnees » : modèles téléchargés, commandes, voix des clients apprises (gardées d'une fois sur l'autre).
- Le studio s'allume tout seul à la première visite (2 à 4 min) et s'éteint après 15 min sans visite.
"""
from pathlib import Path

import modal

RACINE = "/opt/bms"
CARTE = "L40S"  # 48 Go : ACE-Step, chant/danse et décors tiennent à l'aise (≈ 2 $/h, budget 30 $/mois)
CU128 = "https://download.pytorch.org/whl/cu128"
ICI = Path(__file__).resolve().parent
UV_ENV = {"UV_PYTHON_INSTALL_DIR": f"{RACINE}/outils/python", "UV_CACHE_DIR": "/tmp/uvcache",
          "UV_LINK_MODE": "copy"}

PAQUETS_ECHOMIMIC = ("diffusers==0.32.2 transformers==4.57.1 'accelerate>=1.0' omegaconf einops safetensors "
                     "librosa moviepy==2.2.1 pyloudnorm 'imageio[ffmpeg]' 'imageio[pyav]' opencv-python-headless "
                     "ftfy sentencepiece timm 'huggingface_hub>=0.30' scipy scikit-image func_timeout tomesd "
                     "torchdiffeq torchsde protobuf beautifulsoup4 rembg==2.0.67 onnxruntime")

image = (
    modal.Image.from_registry("nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04", add_python="3.11")
    .entrypoint([])
    .apt_install("git", "ffmpeg", "portaudio19-dev", "psmisc", "curl", "build-essential", "libsndfile1")
    .pip_install("uv", "flask", "requests", "numpy", "pillow", "librosa", "soundfile", "imageio-ffmpeg",
                 "faster-whisper", "transformers", "sentencepiece", "sacremoses", "huggingface_hub")
    .pip_install("torch==2.7.1", extra_index_url=CU128)
    .env(UV_ENV)
    .run_commands(
        f"mkdir -p {RACINE}/outils/uv {RACINE}/moteurs && cp $(which uv) {RACINE}/outils/uv/uv",
        # Moteur musical
        f"git clone -q --depth 1 https://github.com/ace-step/ACE-Step-1.5.git {RACINE}/moteurs/ACE-Step-1.5",
        f"cd {RACINE}/moteurs/ACE-Step-1.5 && {RACINE}/outils/uv/uv sync -q",
        # Voix
        f"git clone -q --depth 1 https://github.com/IAHispano/Applio.git {RACINE}/moteurs/Applio",
        f"cd {RACINE}/moteurs/Applio && {RACINE}/outils/uv/uv venv env --python 3.12 --seed -q && "
        f"{RACINE}/outils/uv/uv pip install -q --python env/bin/python -r requirements.txt "
        f"--extra-index-url {CU128} --index-strategy unsafe-best-match && "
        f"env/bin/python core.py prerequisites --models --exe --pretraineds-hifigan",
        # Séparation voix / musique
        f"{RACINE}/outils/uv/uv venv {RACINE}/env_separation --python 3.11 -q && "
        f"{RACINE}/outils/uv/uv pip install -q --python {RACINE}/env_separation/bin/python torch==2.7.1 "
        f"torchaudio==2.7.1 demucs==4.0.1 soundfile --extra-index-url {CU128} --index-strategy unsafe-best-match",
        # Chant / danse (EchoMimicV3) et décors (SDXL + détourage)
        f"git clone -q https://github.com/antgroup/echomimic_v3.git {RACINE}/moteurs/EchoMimicV3 && "
        f"cd {RACINE}/moteurs/EchoMimicV3 && git checkout -q 7e89489ca51c0d008fc1963ec6c03fc5bd0b9397",
        f"cd {RACINE}/moteurs/EchoMimicV3 && {RACINE}/outils/uv/uv venv env --python 3.11 --seed -q && "
        f"{RACINE}/outils/uv/uv pip install -q --python env/bin/python torch==2.7.1 torchvision==0.22.1 "
        f"torchaudio==2.7.1 {PAQUETS_ECHOMIMIC} --extra-index-url {CU128} --index-strategy unsafe-best-match",
        "rm -rf /tmp/uvcache /root/.cache/pip",
    )
    .add_local_dir(str(ICI.parent / "studio"), f"{RACINE}/studio", copy=True,
                   ignore=["**/__pycache__/**"])
    .add_local_dir(str(ICI), f"{RACINE}/en_ligne", copy=True, ignore=["**/__pycache__/**"])
    .run_commands(f"python {RACINE}/en_ligne/correctifs_acestep.py {RACINE}/moteurs/ACE-Step-1.5")
)

app = modal.App("bonheur-studio")
donnees = modal.Volume.from_name("bms-donnees", create_if_missing=True)


def _relier(source: str, cible: str):
    """Fait pointer un dossier du programme vers le volume (pour garder son contenu)."""
    import os
    import shutil
    src, dst = Path(source), Path(cible)
    dst.mkdir(parents=True, exist_ok=True)
    if src.is_symlink():
        return
    if src.exists():  # contenu livré avec l'image : recopié une fois dans le volume
        for f in src.iterdir():
            if not (dst / f.name).exists():
                (shutil.copytree if f.is_dir() else shutil.copy2)(f, dst / f.name)
        shutil.rmtree(src)
    src.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(dst, src)


@app.function(image=image, gpu=CARTE, cpu=8, memory=49152, volumes={"/data": donnees},
              secrets=[modal.Secret.from_name("bms")], timeout=24 * 3600, scaledown_window=15 * 60,
              max_containers=1)
@modal.concurrent(max_inputs=200)
@modal.web_server(port=7870, startup_timeout=10 * 60)
def studio():
    import os
    import subprocess
    _relier(f"{RACINE}/moteurs/ACE-Step-1.5/checkpoints", "/data/acestep_checkpoints")
    _relier(f"{RACINE}/moteurs/Applio/logs", "/data/applio_logs")          # voix des clients gardées
    _relier(f"{RACINE}/moteurs/EchoMimicV3/modeles", "/data/echomimic_modeles")
    Path(f"{RACINE}/logs").mkdir(exist_ok=True)
    env = dict(os.environ, BMS_EN_LIGNE="1", BMS_HOTE="0.0.0.0", BMS_COMMANDES="/data/commandes",
               BMS_ECHOMIMIC=f"{RACINE}/moteurs/EchoMimicV3", BMS_ETAT_PERFORMANCE="/data/etat_performance.txt",
               BMS_PYTHON_SEPARATION=f"{RACINE}/env_separation/bin/python", BMS_MAINTIEN="1",
               BMS_INACTIVITE_MAX="0", BMS_VEILLE=str(40 * 60), HF_HOME="/data/hf", TORCH_HOME="/data/torch",
               ACESTEP_OFFLOAD_TO_CPU="false", ACESTEP_LM_MODEL_PATH="acestep-5Hz-lm-1.7B",
               PYTHONUNBUFFERED="1", MPLBACKEND="Agg")
    # modèles chant/danse/décors : vérifiés (et téléchargés la 1re fois) en arrière-plan
    subprocess.Popen([f"{RACINE}/outils/uv/uv", "--version"])
    subprocess.Popen(["python", f"{RACINE}/studio/moteurs_video/installer_performance.py",
                      f"{RACINE}/moteurs/EchoMimicV3", "/data/etat_performance.txt", f"{RACINE}/outils/uv/uv"],
                     env=env)
    subprocess.Popen(["python", "serveur.py", "--sans-navigateur"], cwd=f"{RACINE}/studio", env=env)
