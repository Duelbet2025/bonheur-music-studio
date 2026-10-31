"""Installe le moteur « performance » (EchoMimicV3-Flash) en arrière-plan, sans bloquer le studio.

Usage : python installer_performance.py <dossier_moteur> <fichier_etat> <uv>
- écrit l'avancement dans <fichier_etat> (affiché dans le studio) ;
- écrit <dossier_moteur>/PRET.json avec les chemins des modèles quand tout est prêt.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

DEPOT = "https://github.com/antgroup/echomimic_v3.git"
VERSION = "7e89489ca51c0d008fc1963ec6c03fc5bd0b9397"  # version testée (janvier 2026)
CU128 = "https://download.pytorch.org/whl/cu128"
PAQUETS = ["diffusers==0.35.2", "transformers==4.57.1", "accelerate>=1.0", "omegaconf", "einops",
           "safetensors", "librosa", "moviepy==2.2.1", "pyloudnorm", "imageio[ffmpeg]", "imageio[pyav]",
           "opencv-python-headless", "ftfy", "sentencepiece", "timm", "huggingface_hub>=0.30", "scipy",
           "scikit-image", "func_timeout", "tomesd", "torchdiffeq", "torchsde", "protobuf", "beautifulsoup4"]
# module manquant -> paquet à installer (réparation automatique)
NOMS = {"cv2": "opencv-python-headless", "PIL": "pillow", "skimage": "scikit-image", "yaml": "pyyaml",
        "sklearn": "scikit-learn", "bs4": "beautifulsoup4", "google": "protobuf"}


def main(dossier, fichier_etat, uv):
    dossier, fichier_etat = Path(dossier), Path(fichier_etat)
    dossier.parent.mkdir(parents=True, exist_ok=True)
    journal = dossier.parent / "installation_performance.log"

    def etat(msg):
        fichier_etat.write_text(msg, encoding="utf-8")
        with open(journal, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

    def lancer(cmd, cwd=None):
        with open(journal, "a", encoding="utf-8") as f:
            f.write("$ " + " ".join(map(str, cmd)) + "\n")
            f.flush()
            r = subprocess.run([str(c) for c in cmd], cwd=cwd, stdout=f, stderr=subprocess.STDOUT)
        if r.returncode != 0:
            raise RuntimeError("échec de : " + " ".join(map(str, cmd))[:150])

    try:
        if not (dossier / "src").exists():
            etat("téléchargement du code (1/4)")
            if dossier.exists():
                shutil.rmtree(dossier)
            lancer(["git", "clone", "-q", DEPOT, dossier])
            lancer(["git", "checkout", "-q", VERSION], cwd=dossier)
        py = dossier / "env" / "bin" / "python"
        if not py.exists():
            lancer([uv, "venv", dossier / "env", "--python", "3.11", "--seed", "-q"])
        etat("installation des bibliothèques (2/4)")
        lancer([uv, "pip", "install", "-q", "--python", py, "torch==2.7.1", "torchvision==0.22.1",
                "torchaudio==2.7.1", *PAQUETS, "--extra-index-url", CU128, "--index-strategy", "unsafe-best-match"])
        subprocess.run([uv, "pip", "install", "-q", "--python", str(py), "decord"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # facultatif
        subprocess.run([uv, "cache", "clean"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # vérification des imports, avec réparation automatique des paquets manquants
        test = ("import src.utils, src.wav2vec2, src.cache_utils, src.fm_solvers_unipc, src.wan_vae, "
                "src.wan_image_encoder, src.wan_text_encoder, src.wan_transformer3d_audio_2512, "
                "src.pipeline_wan_fun_inpaint_audio_2512, pyloudnorm, librosa")
        for _ in range(6):
            r = subprocess.run([str(py), "-c", test], cwd=dossier, capture_output=True, text=True)
            if r.returncode == 0:
                break
            m = re.search(r"No module named '([^'.]+)", r.stderr)
            if not m:
                raise RuntimeError("import impossible : " + r.stderr.strip().splitlines()[-1][:150])
            lancer([uv, "pip", "install", "-q", "--python", py, NOMS.get(m.group(1), m.group(1))])
        else:
            raise RuntimeError("bibliothèques incomplètes")

        etat("téléchargement des modèles, environ 20 Go (3/4)")
        modeles = dossier / "modeles"
        script = f"""
import json, pathlib
from huggingface_hub import snapshot_download
m = pathlib.Path({str(modeles)!r})
base = snapshot_download("alibaba-pai/Wan2.1-Fun-V1.1-1.3B-InP", local_dir=m / "Wan2.1-Fun-V1.1-1.3B-InP")
flash = snapshot_download("BadToBest/EchoMimicV3", allow_patterns=["echomimicv3-flash-pro/*"], local_dir=m / "EchoMimicV3")
trans = sorted(pathlib.Path(flash).rglob("*flash*/**/diffusion_pytorch_model*.safetensors")) or \\
        sorted(pathlib.Path(flash).rglob("diffusion_pytorch_model*.safetensors"))
w2v = [p.parent for p in pathlib.Path(flash).rglob("config.json") if "wav2vec" in str(p).lower()]
if not w2v:
    w2v = [pathlib.Path(snapshot_download("TencentGameMate/chinese-wav2vec2-base", local_dir=m / "chinese-wav2vec2-base"))]
    try:
        snapshot_download("TencentGameMate/chinese-wav2vec2-base", revision="refs/pr/1",
                          allow_patterns=["model.safetensors"], local_dir=m / "chinese-wav2vec2-base")
    except Exception:
        pass
assert trans, "poids EchoMimicV3-Flash introuvables"
print(json.dumps({{"base": str(base), "transformer": str(trans[0]), "wav2vec": str(w2v[0])}}))
"""
        r = subprocess.run([str(py), "-c", script], capture_output=True, text=True,
                           env={**os.environ, "HF_HUB_ENABLE_HF_TRANSFER": "0"})
        with open(journal, "a", encoding="utf-8") as f:
            f.write(r.stdout[-3000:] + r.stderr[-3000:])
        if r.returncode != 0:
            raise RuntimeError("téléchargement des modèles : " + (r.stderr.strip().splitlines() or ["?"])[-1][:150])
        chemins = json.loads(r.stdout.strip().splitlines()[-1])
        etat("vérification (4/4)")
        (dossier / "PRET.json").write_text(json.dumps(chemins), encoding="utf-8")
        etat("prêt")
    except Exception as e:
        etat("indisponible : " + str(e)[:140])
        raise


if __name__ == "__main__":
    main(*sys.argv[1:4])
