"""Moteur « performance » : la personne de la photo chante (lèvres + gestes) ou danse, calée sur l'audio.

Modèle : EchoMimicV3-Flash (Ant Group, licence Apache 2.0), basé sur Wan 2.1 Fun 1.3B.
Lancé par video_ia.py dans son propre environnement Python, avec le dossier EchoMimicV3 comme
dossier courant :  python performance.py taches.json
Le modèle est chargé une seule fois, puis tous les plans sont fabriqués à la suite.
Imprime des lignes « PROGRES », « OK », « ECHEC » lues par le studio.
"""
import gc
import json
import math
import os
import sys
import time
import traceback

import numpy as np
import torch
from PIL import Image, ImageOps

sys.path.insert(0, os.getcwd())

NEGATIF = ("Gesture is bad. Gesture is unclear. Strange and twisted hands. Bad hands. Bad fingers. "
           "Unclear and blurry hands. Fused fingers. Distorted face, deformed mouth, blurry, low quality, "
           "static, frozen, watermark, text.")


def taille_echantillon(img, cote):
    """Même calcul que l'outil officiel : surface ≈ cote², multiples de 16, proportions conservées."""
    w, h = img.size
    if cote * cote < w * h:
        r = math.sqrt(w * h / cote / cote)
        w, h = w / r // 16 * 16, h / r // 16 * 16
    else:
        w, h = w // 16 * 16, h // 16 * 16
    return int(h), int(w)


def normaliser_volume(audio, sr=16000, lufs=-23):
    import pyloudnorm as pyln
    mesure = pyln.Meter(sr)
    volume = mesure.integrated_loudness(audio)
    if abs(volume) > 100:  # silence : on laisse tel quel
        return audio
    return pyln.normalize.loudness(audio, volume, lufs)


class Factice(torch.nn.Module):
    """Remplace l'encodeur de texte (11 Go) une fois les descriptions encodées : il ne sert plus."""

    def __init__(self, dtype):
        super().__init__()
        self._dtype = dtype
        self.poids = torch.nn.Parameter(torch.zeros(1, dtype=dtype), requires_grad=False)

    @property
    def dtype(self):
        return self._dtype

    @property
    def device(self):
        return self.poids.device


def main(fichier_taches):
    reglages = json.load(open(fichier_taches, encoding="utf-8"))
    taches = reglages["taches"]
    if not taches:
        print("OK aucun plan", flush=True)
        return

    from omegaconf import OmegaConf
    from safetensors.torch import load_file
    from transformers import AutoTokenizer, Wav2Vec2FeatureExtractor
    import librosa
    from einops import rearrange

    from src.cache_utils import get_teacache_coefficients
    from src.fm_solvers_unipc import FlowUniPCMultistepScheduler
    from src.pipeline_wan_fun_inpaint_audio_2512 import WanFunInpaintAudioPipeline
    from src.utils import filter_kwargs, get_image_to_video_latent2, save_videos_grid
    from src.wan_image_encoder import CLIPModel
    from src.wan_text_encoder import WanT5EncoderModel
    from src.wan_transformer3d_audio_2512 import WanTransformerAudioMask3DModel
    from src.wan_vae import AutoencoderKLWan
    from src.wav2vec2 import Wav2Vec2Model

    m = reglages["modeles"]
    base = m["base"]
    cuda = torch.device("cuda")
    ancienne_carte = torch.cuda.get_device_capability()[0] < 8  # T4 : pas de bfloat16 rapide
    dtype = torch.float16 if ancienne_carte else torch.bfloat16
    pas = int(reglages.get("pas", 8))
    cote = int(reglages.get("cote", 512 if ancienne_carte else 640))
    images_max = int(reglages.get("images_max", 81))
    config = OmegaConf.load("config/config.yaml")

    def chemin(cle, defaut):
        return os.path.join(base, config[cle].get(defaut + "_subpath", defaut))

    print("PROGRES Chargement du modèle de performance…", flush=True)
    t0 = time.time()

    # 1. Descriptions encodées une fois, sur le processeur (l'encodeur ne tient pas avec le reste sur 16 Go)
    tokenizer = AutoTokenizer.from_pretrained(chemin("text_encoder_kwargs", "tokenizer"))
    encodeur = WanT5EncoderModel.from_pretrained(
        chemin("text_encoder_kwargs", "text_encoder"),
        additional_kwargs=OmegaConf.to_container(config["text_encoder_kwargs"]),
        low_cpu_mem_usage=True, torch_dtype=torch.bfloat16).eval()

    transformer = WanTransformerAudioMask3DModel.from_pretrained(
        chemin("transformer_additional_kwargs", "transformer"),
        transformer_additional_kwargs=OmegaConf.to_container(config["transformer_additional_kwargs"]),
        low_cpu_mem_usage=True, torch_dtype=dtype)
    etat = load_file(m["transformer"])
    etat = etat.get("state_dict", etat)
    manquants, inattendus = transformer.load_state_dict(etat, strict=False)
    print(f"   poids Flash chargés (manquants {len(manquants)}, inattendus {len(inattendus)})", flush=True)
    del etat

    vae = AutoencoderKLWan.from_pretrained(
        chemin("vae_kwargs", "vae"), additional_kwargs=OmegaConf.to_container(config["vae_kwargs"])).to(dtype)
    clip_image = CLIPModel.from_pretrained(chemin("image_encoder_kwargs", "image_encoder")).to(dtype).eval()
    planif = FlowUniPCMultistepScheduler(
        **filter_kwargs(FlowUniPCMultistepScheduler, {**OmegaConf.to_container(config["scheduler_kwargs"]),
                                                      "shift": 1}))
    pipeline = WanFunInpaintAudioPipeline(transformer=transformer, vae=vae, tokenizer=tokenizer,
                                          text_encoder=encodeur, scheduler=planif, clip_image_encoder=clip_image)

    textes = {}
    with torch.no_grad():
        for t in taches:
            if t["prompt"] not in textes:
                pos, neg = pipeline.encode_prompt(t["prompt"], NEGATIF, do_classifier_free_guidance=True,
                                                  device=torch.device("cpu"), dtype=torch.bfloat16)
                textes[t["prompt"]] = ([e.to(cuda, dtype) for e in pos], [e.to(cuda, dtype) for e in neg])
    pipeline.__dict__["text_encoder"] = Factice(dtype)  # libère l'encodeur (sans passer par diffusers)
    # on donne à la fois le texte (pour la taille du lot) et ses encodages déjà calculés :
    # la vérification d'origine refuse ce cas, on la remplace par une version qui l'accepte
    pipeline.check_inputs = lambda *a, **k: None
    del encodeur
    gc.collect()
    pipeline.to(cuda)
    pipeline.transformer.enable_teacache(get_teacache_coefficients(base), pas, 0.1, num_skip_start_steps=2,
                                         offload=False)

    audio_enc = Wav2Vec2Model.from_pretrained(m["wav2vec"], local_files_only=True).to("cpu")
    audio_enc.feature_extractor._freeze_parameters()
    extracteur = Wav2Vec2FeatureExtractor.from_pretrained(m["wav2vec"], local_files_only=True)
    ratio_t = vae.config.temporal_compression_ratio
    print(f"PROGRES Modèle prêt en {time.time() - t0:.0f} s ({'float16' if ancienne_carte else 'bfloat16'}, "
          f"{cote}px, {pas} étapes).", flush=True)

    reussis = 0
    for i, t in enumerate(taches, start=1):
        debut = time.time()
        try:
            img = ImageOps.exif_transpose(Image.open(t["image"])).convert("RGB")
            duree = librosa.get_duration(path=t["audio"])
            n = min(int(duree * 25), images_max)
            n = max(5, (n - 1) // ratio_t * ratio_t + 1)
            son, sr = librosa.load(t["audio"], sr=16000)
            son = normaliser_volume(son, sr)[:int(n / 25 * sr)]
            valeurs = np.squeeze(extracteur(son, sampling_rate=sr).input_values)
            with torch.no_grad():
                sortie_audio = audio_enc(torch.from_numpy(valeurs).float().unsqueeze(0), seq_len=int(n),
                                         output_hidden_states=True)
            emb = torch.stack(sortie_audio.hidden_states[1:], dim=1).squeeze(0)
            emb = rearrange(emb, "b s d -> s b d").to(cuda, dtype)
            fenetre = torch.arange(n).unsqueeze(1) + (torch.arange(5) - 2).unsqueeze(0)
            emb = emb[torch.clamp(fenetre, 0, emb.shape[0] - 1)].unsqueeze(0)

            h, w = taille_echantillon(img, cote)
            video, masque, img_clip = get_image_to_video_latent2(img, None, video_length=n, sample_size=[h, w])
            pos, neg = textes[t["prompt"]]
            with torch.no_grad():
                resultat = pipeline(
                    t["prompt"], negative_prompt=NEGATIF, prompt_embeds=pos, negative_prompt_embeds=neg,
                    num_frames=n, audio_embeds=emb, audio_scale=1.0, ip_mask=None, use_un_ip_mask=False,
                    height=h, width=w, generator=torch.Generator(device=cuda).manual_seed(int(t.get("graine", 43))),
                    neg_scale=1.0, neg_steps=0, use_dynamic_cfg=False, use_dynamic_acfg=False,
                    guidance_scale=float(t.get("cfg", 5.0)), audio_guidance_scale=float(t.get("cfg_audio", 3.0)),
                    num_inference_steps=pas, video=video, mask_video=masque, clip_image=img_clip,
                    cfg_skip_ratio=0.0, shift=5.0).videos
            resultat = torch.as_tensor(resultat)
            if torch.isnan(resultat).any() or float(resultat.float().std()) < 0.01:
                raise RuntimeError("image vide (calcul instable sur cette carte)")
            save_videos_grid(resultat[:, :, :n], t["sortie"], fps=25)
            reussis += 1
            print(f"PROGRES plan {i}/{len(taches)} fait en {time.time() - debut:.0f} s", flush=True)
        except Exception as e:  # un plan raté n'arrête pas les autres : il sera remplacé par la photo
            print(f"ECHEC plan {i}/{len(taches)} : {str(e)[:200]}", flush=True)
            traceback.print_exc()
            if "out of memory" in str(e).lower():
                torch.cuda.empty_cache()
        if t.get("fin_avant") and time.time() > float(t["fin_avant"]):
            print("ECHEC temps maximum atteint : les plans restants seront faits avec les photos", flush=True)
            break
    print(f"OK {reussis}/{len(taches)} plans de performance fabriqués", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
