"""Décors du clip : crée la scène décrite par le client et y place la personne de la photo.

1. l'image du décor est générée par SDXL + SDXL-Lightning (4 étapes ; licences OpenRAIL++, usage
   commercial permis) à partir de la description (plage, voitures de luxe, forêt…) ;
2. la personne est détourée de sa photo (rembg, MIT) ;
3. elle est posée dans le décor, avec la lumière et les couleurs du décor, ombre au sol.
Le résultat sert ensuite d'image de départ au moteur « performance » (elle chante / danse dedans).

Usage : python scenes.py taches.json   (imprime PROGRES / OK / ECHEC)
"""
import json
import sys
import time
import traceback

import numpy as np
from PIL import Image, ImageFilter, ImageOps

NEGATIF = ("nsfw, nudity, naked, topless, explicit, sexual, lowres, blurry, text, watermark, logo, "
           "deformed, ugly, cropped, frame, border, cartoon, painting, close-up portrait of one face")


def charger_sdxl(m, dtype):
    import torch
    from diffusers import AutoencoderKL, EulerDiscreteScheduler, StableDiffusionXLPipeline
    vae = AutoencoderKL.from_pretrained(m["vae"], torch_dtype=dtype)
    pipe = StableDiffusionXLPipeline.from_pretrained(m["sdxl"], vae=vae, torch_dtype=dtype,
                                                     variant="fp16", use_safetensors=True)
    pipe.load_lora_weights(m["lightning"])
    pipe.fuse_lora()
    pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config, timestep_spacing="trailing")
    pipe.to("cuda")
    pipe.enable_vae_slicing()
    return pipe


def detourer(photo):
    from rembg import new_session, remove
    global _SESSION
    try:
        _SESSION
    except NameError:
        _SESSION = new_session("isnet-general-use")
    img = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
    img.thumbnail((1600, 1600))
    rgba = remove(img, session=_SESSION, post_process_mask=True)
    boite = rgba.getchannel("A").point(lambda a: 255 if a > 20 else 0).getbbox()
    return rgba.crop(boite) if boite else rgba


def accorder_couleurs(personne, decor, force=0.45):
    """Rapproche la lumière et la teinte de la personne de celles du décor (sans la dénaturer)."""
    p = np.asarray(personne.convert("RGB")).astype(np.float32)
    a = np.asarray(personne.getchannel("A")).astype(np.float32) / 255.0
    d = np.asarray(decor.convert("RGB")).astype(np.float32)
    masque = a > 0.5
    if masque.sum() < 100:
        return personne
    mp, sp = p[masque].mean(0), p[masque].std(0) + 1e-3
    md, sd = d.reshape(-1, 3).mean(0), d.reshape(-1, 3).std(0) + 1e-3
    cible = (p - mp) / sp * (sp * (1 - force) + sd * force) + (mp * (1 - force) + md * force)
    sortie = Image.fromarray(np.clip(cible, 0, 255).astype(np.uint8))
    sortie.putalpha(personne.getchannel("A"))
    return sortie


def composer(decor, personne, hauteur=0.86, decalage=0.0):
    """Pose la personne debout, en bas du cadre, avec une ombre douce au sol."""
    W, H = decor.size
    h = int(H * hauteur)
    w = int(personne.width * h / personne.height)
    if w > W * 0.8:
        w = int(W * 0.8)
        h = int(personne.height * w / personne.width)
    personne = accorder_couleurs(personne.resize((w, h), Image.LANCZOS), decor)
    x = int((W - w) / 2 + decalage * W)
    y = H - h
    alpha = personne.getchannel("A").filter(ImageFilter.GaussianBlur(1.2))  # bords adoucis
    personne.putalpha(alpha)
    ombre = Image.new("L", (W, H), 0)
    ell = Image.new("L", (int(w * 0.9), max(8, int(h * 0.06))), 0)
    from PIL import ImageDraw
    ImageDraw.Draw(ell).ellipse([0, 0, ell.width - 1, ell.height - 1], fill=110)
    ombre.paste(ell, (x + int(w * 0.05), H - ell.height // 2 - 4))
    ombre = ombre.filter(ImageFilter.GaussianBlur(12))
    resultat = decor.convert("RGB").copy()
    noir = Image.new("RGB", (W, H), (0, 0, 0))
    resultat = Image.composite(noir, resultat, ombre)
    resultat.paste(personne, (x, y), personne)
    return resultat


def main(fichier):
    import torch
    reglages = json.load(open(fichier, encoding="utf-8"))
    taches = reglages["taches"]
    dtype = torch.float16
    print("PROGRES Chargement du créateur de décors…", flush=True)
    t0 = time.time()
    pipe = charger_sdxl(reglages["modeles"], dtype)
    print(f"PROGRES Créateur de décors prêt en {time.time() - t0:.0f} s", flush=True)
    faits = 0
    for i, t in enumerate(taches, start=1):
        try:
            largeur, hauteur = t.get("taille", [768, 1024])
            prompt = (f"{t['scene']}, wide shot music video set, background scenery with space in the center "
                      f"foreground for the singer, cinematic lighting, vibrant colors, professional photography, "
                      f"highly detailed, 4k, tasteful, non-explicit")
            g = torch.Generator("cuda").manual_seed(int(t.get("graine", 7)))
            decor = pipe(prompt=prompt, negative_prompt=NEGATIF, num_inference_steps=4, guidance_scale=0,
                         width=largeur, height=hauteur, generator=g).images[0]
            decor.save(t["sortie_decor"])
            image = composer(decor, detourer(t["photo"]))
            image.save(t["sortie"], quality=95)
            faits += 1
            print(f"PROGRES décor {i}/{len(taches)} prêt", flush=True)
        except Exception as e:
            print(f"ECHEC décor {i}/{len(taches)} : {str(e)[:200]}", flush=True)
            traceback.print_exc()
    print(f"OK {faits}/{len(taches)} décors créés", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
