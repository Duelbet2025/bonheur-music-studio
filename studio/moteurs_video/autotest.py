"""Auto-test du clip vivant (lancé une fois quand les moteurs sont prêts) : décor + chant sur un personnage test.

Usage (environnement EchoMimicV3, dossier courant = EchoMimicV3) : python autotest.py PRET.json dossier_sortie
Imprime « AUTOTEST OK … » ou « AUTOTEST ECHEC … » avec la raison.
"""
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

ICI = Path(__file__).resolve().parent


def main(pret, sortie):
    sortie = Path(sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    modeles = json.loads(Path(pret).read_text(encoding="utf-8"))
    rapport = []
    t0 = time.time()
    personne = sortie / "personne.jpg"
    try:
        if "sdxl" in modeles:
            sys.path.insert(0, str(ICI))
            import torch
            import scenes
            pipe = scenes.charger_sdxl(modeles, torch.float16)
            img = pipe(prompt="full body photo of a smiling african male singer standing, plain studio background, "
                              "realistic photography", num_inference_steps=4, guidance_scale=0, width=768,
                       height=1024).images[0]
            img.save(personne)
            del pipe
            torch.cuda.empty_cache()
            taches = {"modeles": modeles, "taches": [{"scene": "a beach at sunset with palm trees", "photo": str(personne),
                                                      "sortie": str(sortie / "scene.jpg"),
                                                      "sortie_decor": str(sortie / "decor.jpg"), "graine": 3}]}
            (sortie / "decors.json").write_text(json.dumps(taches), encoding="utf-8")
            r = subprocess.run([sys.executable, str(ICI / "scenes.py"), str(sortie / "decors.json")],
                               capture_output=True, text=True)
            ok = (sortie / "scene.jpg").exists()
            rapport.append(f"décors {'OK' if ok else 'ECHEC'} ({time.time() - t0:.0f} s)"
                           + ("" if ok else " : " + (r.stdout + r.stderr).strip()[-600:]))
            image = sortie / "scene.jpg" if ok else personne
        else:
            rapport.append("décors non installés")
            raise RuntimeError("pas d'image de test (décors absents)")
        audio = sortie / "audio.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "sine=f=220:d=3,volume=0.5,apulsator=hz=4", "-ar", "16000", "-ac", "1", str(audio)], check=True)
        t1 = time.time()
        perf = {"modeles": modeles, "taches": [{"image": str(image), "audio": str(audio),
                                                "prompt": "A singer sings with expressive hand gestures.",
                                                "sortie": str(sortie / "perf.mp4"), "graine": 1}]}
        (sortie / "perf.json").write_text(json.dumps(perf), encoding="utf-8")
        r = subprocess.run([sys.executable, str(ICI / "performance.py"), str(sortie / "perf.json")],
                           capture_output=True, text=True)
        ok = (sortie / "perf.mp4").exists() and (sortie / "perf.mp4").stat().st_size > 10000
        rapport.append(f"chant/danse {'OK' if ok else 'ECHEC'} ({time.time() - t1:.0f} s pour 3 s de vidéo)"
                       + ("" if ok else " : " + (r.stdout + r.stderr).strip()[-900:]))
        print(("AUTOTEST OK " if ok else "AUTOTEST ECHEC ") + " | ".join(rapport), flush=True)
    except Exception as e:
        print("AUTOTEST ECHEC " + " | ".join(rapport) + " | " + str(e)[:300] + " | " +
              traceback.format_exc()[-600:], flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
