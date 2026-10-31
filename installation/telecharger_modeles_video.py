"""Télécharge les modèles des modules vidéo IA (appelé par l'installateur).

    python telecharger_modeles_video.py musetalk <dossier MuseTalk>
    python telecharger_modeles_video.py wan
"""
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download


def musetalk(dossier: Path):
    m = dossier / "models"
    print("Modèles MuseTalk (synchro des lèvres)…", flush=True)
    snapshot_download("TMElyralab/MuseTalk", local_dir=m,
                      allow_patterns=["musetalk/*", "musetalkV15/*"])
    for fichier in ("config.json", "diffusion_pytorch_model.bin"):
        hf_hub_download("stabilityai/sd-vae-ft-mse", fichier, local_dir=m / "sd-vae")
    for fichier in ("config.json", "pytorch_model.bin", "preprocessor_config.json"):
        hf_hub_download("openai/whisper-tiny", fichier, local_dir=m / "whisper")
    hf_hub_download("yzd-v/DWPose", "dw-ll_ucoco_384.pth", local_dir=m / "dwpose")
    for fichier in ("79999_iter.pth", "resnet18-5c106cde.pth"):
        hf_hub_download("ManyOtherFunctions/face-parse-bisent", fichier, local_dir=m / "face-parse-bisent")
    attendu = [m / "musetalkV15" / "unet.pth", m / "musetalkV15" / "musetalk.json",
               m / "sd-vae" / "diffusion_pytorch_model.bin", m / "whisper" / "pytorch_model.bin",
               m / "dwpose" / "dw-ll_ucoco_384.pth", m / "face-parse-bisent" / "79999_iter.pth"]
    manquants = [str(f) for f in attendu if not f.exists()]
    if manquants:
        sys.exit("Fichiers manquants : " + ", ".join(manquants))
    print("Modèles MuseTalk prêts.", flush=True)


def wan():
    print("Modèle d'animation Wan 2.2 (~25 Go, patientez)…", flush=True)
    snapshot_download("Wan-AI/Wan2.2-TI2V-5B-Diffusers")
    print("Modèle d'animation prêt.", flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "musetalk":
        musetalk(Path(sys.argv[2]))
    else:
        wan()
