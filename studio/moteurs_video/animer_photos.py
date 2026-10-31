"""Animation IA des photos avec Wan 2.2 TI2V-5B (licence Apache 2.0).

Lancé par le studio dans son propre environnement (env_video) :
    python animer_photos.py taches.json
taches.json = {"prompt": "...", "taches": [{"photo": "...", "sortie": "..."}], "secondes": 3, "pas": 30}
Chaque photo devient une courte vidéo où la personne bouge naturellement.
"""
import json
import sys
import time

import torch
from diffusers import AutoencoderKLWan, WanImageToVideoPipeline
from diffusers.utils import export_to_video
from PIL import Image, ImageOps

MODELE = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
NEGATIF = ("blurry, distorted face, deformed hands, extra fingers, bad anatomy, static, frozen, "
           "low quality, watermark, text, subtitles, flickering, ugly, disfigured")
FPS = 24


def dimensions(img):
    """Taille de sortie multiple de 32, en gardant l'orientation de la photo (~720p)."""
    ratio = img.width / img.height
    if ratio > 1.2:
        return 1280, 704
    if ratio < 0.83:
        return 704, 1280
    return 960, 960


def main(fichier):
    conf = json.load(open(fichier, encoding="utf-8"))
    print("Chargement du modèle d'animation (la première fois, téléchargement ~20 Go)…", flush=True)
    vae = AutoencoderKLWan.from_pretrained(MODELE, subfolder="vae", torch_dtype=torch.float32)
    pipe = WanImageToVideoPipeline.from_pretrained(MODELE, vae=vae, torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()  # garde la mémoire de la carte graphique sous contrôle
    try:
        pipe.vae.enable_tiling()
    except Exception:
        pass

    nb_images = int(conf.get("secondes", 3) * FPS) // 4 * 4 + 1  # format exigé : 4k + 1
    for i, t in enumerate(conf["taches"], start=1):
        debut = time.time()
        img = ImageOps.exif_transpose(Image.open(t["photo"])).convert("RGB")
        w, h = dimensions(img)
        img = ImageOps.fit(img, (w, h), Image.LANCZOS, centering=(0.5, 0.35))
        print(f"PROGRES {i}/{len(conf['taches'])} animation de {t['photo']}", flush=True)
        try:
            images = pipe(image=img, prompt=conf["prompt"], negative_prompt=NEGATIF, height=h, width=w,
                          num_frames=nb_images, num_inference_steps=int(conf.get("pas", 30)),
                          guidance_scale=5.0).frames[0]
            export_to_video(images, t["sortie"], fps=FPS)
            print(f"OK {t['sortie']} ({time.time() - debut:.0f} s)", flush=True)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            print(f"ECHEC mémoire insuffisante pour {t['photo']}", flush=True)
        except Exception as e:  # une photo ratée ne bloque pas les autres
            print(f"ECHEC {t['photo']} : {e}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
