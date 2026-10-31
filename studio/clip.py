"""Clip vidéo automatique synchronisé sur la chanson.

- Détecte le tempo et les temps forts de la chanson (librosa).
- Change de photo exactement sur les temps forts (plus souvent dans les passages énergiques).
- Anime chaque photo (zoom, travelling) avec fond flou pour les photos verticales.
- Formules Pro/Ultra : « pulsations » et flashs sur chaque temps, plusieurs formats.
- Ultra : paroles affichées en karaoké, synchronisées sur la voix.
"""
import json
import random
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from config import NOM_STUDIO
from outils import lancer_ffmpeg

FPS = 30
FORMATS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
MARGE_ZOOM = 1.3  # l'image de travail est 30 % plus grande que la vidéo


# ---------------------------------------------------------------------------
# Polices
# ---------------------------------------------------------------------------
def police(taille, grasse=True):
    candidats = [
        "C:/Windows/Fonts/segoeuib.ttf" if grasse else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if grasse else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if grasse
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidats:
        if Path(c).exists():
            return ImageFont.truetype(c, taille)
    return ImageFont.load_default(size=taille)


def _texte_contour(draw, xy, texte, fnt, couleur=(255, 255, 255), contour=(0, 0, 0), ep=4, anchor="mm"):
    draw.text(xy, texte, font=fnt, fill=couleur, stroke_width=ep, stroke_fill=contour, anchor=anchor)


def _couper_lignes(texte, fnt, largeur_max, draw):
    mots, lignes, courante = texte.split(), [], ""
    for mot in mots:
        essai = (courante + " " + mot).strip()
        if draw.textlength(essai, font=fnt) <= largeur_max:
            courante = essai
        else:
            if courante:
                lignes.append(courante)
            courante = mot
    if courante:
        lignes.append(courante)
    return lignes


# ---------------------------------------------------------------------------
# Analyse musicale
# ---------------------------------------------------------------------------
def analyser_rythme(audio: Path):
    import librosa
    y, sr = librosa.load(str(audio), sr=22050, mono=True)
    duree = len(y) / sr
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    tempo = float(np.atleast_1d(tempo)[0])
    rms = librosa.feature.rms(y=y)[0]
    temps_rms = librosa.times_like(rms, sr=sr)
    beats = [float(b) for b in beats if 0.05 < b < duree - 0.05]
    if len(beats) < 8:  # musique sans rythme net : grille régulière
        pas = 60.0 / (tempo or 100)
        beats = list(np.arange(pas, duree, pas))
    return {"duree": duree, "tempo": tempo, "beats": beats,
            "rms": rms.tolist(), "temps_rms": temps_rms.tolist()}


def decouper_en_plans(analyse, effets):
    """Choisit les instants de changement de photo, toujours sur un temps fort."""
    beats, duree = analyse["beats"], analyse["duree"]
    rms, t_rms = np.array(analyse["rms"]), np.array(analyse["temps_rms"])
    seuil = np.percentile(rms, 70)

    def energie(t):
        return rms[min(len(rms) - 1, int(np.searchsorted(t_rms, t)))]

    coupes, i = [0.0], 0
    while i < len(beats):
        if effets == "simple":
            pas = 8
        else:
            pas = 2 if energie(beats[i]) >= seuil else 4
        i += pas
        if i < len(beats) and beats[i] - coupes[-1] >= 0.8:
            coupes.append(beats[i])
    if duree - coupes[-1] < 1.0 and len(coupes) > 1:
        coupes.pop()
    coupes.append(duree)
    return [(coupes[k], coupes[k + 1]) for k in range(len(coupes) - 1)]


# ---------------------------------------------------------------------------
# Préparation des images
# ---------------------------------------------------------------------------
def preparer_image(photo: Path, taille, sortie: Path):
    """Image de travail : photo entière sur fond flou, légèrement plus grande que la vidéo."""
    w, h = int(taille[0] * MARGE_ZOOM), int(taille[1] * MARGE_ZOOM)
    img = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
    fond = ImageOps.fit(img, (w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
    fond = Image.eval(fond, lambda v: int(v * 0.55))
    ratio_img, ratio_cadre = img.width / img.height, w / h
    if abs(ratio_img - ratio_cadre) < 0.15:
        devant = ImageOps.fit(img, (w, h), Image.LANCZOS, centering=(0.5, 0.35))
        fond.paste(devant, (0, 0))
    else:
        devant = ImageOps.contain(img, (w, h), Image.LANCZOS)
        fond.paste(devant, ((w - devant.width) // 2, (h - devant.height) // 2))
    fond.save(sortie, quality=95)
    return sortie


def carton_titre(titre, artiste, taille, sortie: Path):
    w, h = taille
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f_titre, f_artiste = police(int(w * 0.07)), police(int(w * 0.035), grasse=False)
    lignes = _couper_lignes(titre.upper(), f_titre, w * 0.85, d)
    y = h * (0.42 if w >= h else 0.6) - (len(lignes) - 1) * w * 0.04
    for ligne in lignes:
        _texte_contour(d, (w / 2, y), ligne, f_titre, ep=max(3, w // 300))
        y += w * 0.08
    if artiste:
        _texte_contour(d, (w / 2, y + w * 0.01), artiste, f_artiste, couleur=(255, 215, 120), ep=3)
    img.save(sortie)
    return sortie


def image_ligne_paroles(texte, taille, sortie: Path):
    w, h = taille
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fnt = police(int(min(w, h) * 0.055))
    lignes = _couper_lignes(texte, fnt, w * 0.88, d)[:2]
    hauteur_ligne = int(min(w, h) * 0.075)
    y0 = h * (0.86 if w > h else 0.78) - (len(lignes) - 1) * hauteur_ligne
    bande = Image.new("RGBA", (w, int(hauteur_ligne * (len(lignes) + 0.6))), (0, 0, 0, 110))
    img.alpha_composite(bande, (0, int(y0 - hauteur_ligne * 0.8)))
    for k, ligne in enumerate(lignes):
        _texte_contour(d, (w / 2, y0 + k * hauteur_ligne), ligne, fnt, ep=4)
    img.save(sortie)
    return sortie


def signature(taille, sortie: Path, texte=NOM_STUDIO):
    w, h = taille
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fnt = police(int(min(w, h) * 0.022), grasse=False)
    d.text((w - 30, h - 30), texte, font=fnt, fill=(255, 255, 255, 150), anchor="rd")
    img.save(sortie)
    return sortie


def filigrane_apercu(taille, sortie: Path):
    w, h = taille
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fnt = police(int(min(w, h) * 0.12))
    calque = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(calque).text((w / 2, h / 2), "APERÇU", font=fnt, fill=(255, 255, 255, 90), anchor="mm")
    img.alpha_composite(calque.rotate(20, resample=Image.BICUBIC))
    d.text((w / 2, h * 0.93), NOM_STUDIO, font=police(int(min(w, h) * 0.035)), fill=(255, 255, 255, 170),
           anchor="mm")
    img.save(sortie)
    return sortie


# ---------------------------------------------------------------------------
# Paroles synchronisées (Ultra)
# ---------------------------------------------------------------------------
def synchroniser_paroles(voix: Path, langue="fr", journal=print):
    """Repère quand chaque phrase est chantée, à partir de la piste voix (faster-whisper)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        journal("faster-whisper absent : clip sans karaoké.")
        return []
    mots = None
    try:  # audio décodé ici (évite l'incompatibilité de faster-whisper avec les nouvelles versions de PyAV)
        import librosa
        son, _ = librosa.load(str(voix), sr=16000, mono=True)
    except Exception as e:
        journal(f"Karaoké : lecture de la voix impossible ({e}).")
        return []
    for device, calcul in (("cuda", "float16"), ("cpu", "int8")):
        try:
            modele = WhisperModel("small", device=device, compute_type=calcul)
            segments, _ = modele.transcribe(son, language=None if langue == "unknown" else langue,
                                            word_timestamps=True, vad_filter=True)
            mots = [m for s in segments for m in (s.words or [])]
            break
        except Exception as e:
            journal(f"Karaoké ({device}) : {e}")
    if mots is None:
        return []
    lignes, courante = [], []
    for m in mots:
        if courante and (m.start - courante[-1].end > 0.7 or len(courante) >= 7):
            lignes.append(courante)
            courante = []
        courante.append(m)
    if courante:
        lignes.append(courante)
    return [{"debut": l[0].start - 0.15, "fin": l[-1].end + 0.3,
             "texte": " ".join(m.word.strip() for m in l)} for l in lignes]


# ---------------------------------------------------------------------------
# Rendu
# ---------------------------------------------------------------------------
MOUVEMENTS = ["zoom_avant", "travelling_droite", "zoom_arriere", "travelling_gauche", "zoom_haut"]


def _expr_mouvement(mouvement, nb_images, pulses):
    p = f"(on/{max(1, nb_images - 1)})"
    pulse = "+".join(f"0.035*max(0\\,1-abs(on-{b})/5)" for b in pulses) or "0"
    centre_x, centre_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if mouvement == "zoom_avant":
        z, x, y = f"1+0.14*{p}", centre_x, centre_y
    elif mouvement == "zoom_arriere":
        z, x, y = f"1.14-0.14*{p}", centre_x, centre_y
    elif mouvement == "travelling_droite":
        z, x, y = "1.12", f"(iw-iw/zoom)*{p}", centre_y
    elif mouvement == "travelling_gauche":
        z, x, y = "1.12", f"(iw-iw/zoom)*(1-{p})", centre_y
    else:  # zoom vers le haut (là où sont souvent les visages)
        z, x, y = f"1+0.14*{p}", centre_x, "(ih-ih/zoom)*0.3"
    return f"'{z}+{pulse}'", f"'{x}'", f"'{y}'"


LOOKS = {
    "Naturel": "",
    "Chaud et ensoleillé": "colorbalance=rs=.08:gs=.02:bs=-.08,eq=saturation=1.15",
    "Doré (mariage, fête)": "colorbalance=rs=.06:gs=.03:bs=-.06,eq=saturation=1.08:brightness=0.02",
    "Soirée néon": "eq=saturation=1.45:contrast=1.08,colorbalance=rs=.05:bs=.10",
    "Froid et nocturne": "colorbalance=rs=-.06:gs=-.01:bs=.10,eq=saturation=.92",
    "Vintage": "curves=preset=vintage,eq=saturation=.9",
    "Noir et blanc": "hue=s=0,eq=contrast=1.15",
}


def preparer_plans_levres(plans, voix: Path, max_total=45.0, duree_cible=2.5, duree_max=4.5):
    """Choisit les passages où le visage du client chante.

    Les plans consécutifs chantés sont fusionnés en un plan de 2,5 à 4,5 s (toujours coupé sur
    un temps fort), puis on laisse au moins 3 plans d'autres photos entre deux passages.
    Retourne (nouvelle liste de plans, numéros des plans chantés).
    """
    import librosa
    y, sr = librosa.load(str(voix), sr=16000, mono=True)
    rms = np.nan_to_num(librosa.feature.rms(y=y, hop_length=320)[0])
    seuil = max(float(np.percentile(rms, 40)), float(rms.max()) * 0.08)
    actif = rms > seuil
    pas = 320 / sr

    def chante(a, b):
        morceau = actif[int(a / pas):max(int(a / pas) + 1, int(b / pas))]
        return len(morceau) > 0 and morceau.mean() > 0.6

    nouveaux, choisis, total, depuis = [], [], 0.0, 99
    i = 0
    while i < len(plans):
        a, b = plans[i]
        if depuis >= 3 and total < max_total and chante(a, b):
            j = i
            while b - a < duree_cible and j + 1 < len(plans) and plans[j + 1][1] - a <= duree_max \
                    and chante(*plans[j + 1]):
                j += 1
                b = plans[j][1]
            if b - a >= 1.5:
                choisis.append(len(nouveaux))
                nouveaux.append((a, b))
                total += b - a
                depuis = 0
                i = j + 1
                continue
        nouveaux.append((a, b))
        depuis += 1
        i += 1
    return nouveaux, choisis


def preparer_plans_performance(plans, voix: Path, nb_chant, nb_danse, duree_cible=2.4, duree_max=3.2):
    """Choisit les plans où le chanteur chante (passages chantés) et danse (passages instrumentaux).

    Les plans voisins sont fusionnés en plans de 2,4 à 3,2 s (le moteur fait au plus 3,2 s par plan),
    toujours coupés sur un temps fort, et répartis sur toute la chanson.
    Retourne (nouvelle liste de plans, {numéro de plan: "chant" ou "danse"}).
    """
    import librosa
    y, sr = librosa.load(str(voix), sr=16000, mono=True)
    rms = np.nan_to_num(librosa.feature.rms(y=y, hop_length=320)[0])
    seuil = max(float(np.percentile(rms, 40)), float(rms.max()) * 0.08)
    actif = rms > seuil
    pas = 320 / sr

    def part_chantee(a, b):
        morceau = actif[int(a / pas):max(int(a / pas) + 1, int(b / pas))]
        return float(morceau.mean()) if len(morceau) else 0.0

    # 1. fusion des plans voisins de même nature (chanté / instrumental)
    nouveaux, natures, i = [], [], 0
    while i < len(plans):
        a, b = plans[i]
        chante = part_chantee(a, b) > 0.6
        instru = part_chantee(a, b) < 0.15
        j = i
        if chante or instru:
            while b - a < duree_cible and j + 1 < len(plans) and plans[j + 1][1] - a <= duree_max:
                suivant = part_chantee(*plans[j + 1])
                if (chante and suivant > 0.6) or (instru and suivant < 0.15):
                    j += 1
                    b = plans[j][1]
                else:
                    break
        nature = None
        if b - a >= 1.5 and a >= 4.0:  # pas sur le titre du début
            nature = "chant" if chante else "danse" if instru else None
        nouveaux.append((a, b))
        natures.append(nature)
        i = j + 1

    # 2. répartition régulière sur la chanson
    def repartir(candidats, nombre):
        if nombre <= 0 or not candidats:
            return []
        if len(candidats) <= nombre:
            return candidats
        pas_ = len(candidats) / nombre
        return [candidats[int(k * pas_ + pas_ / 2)] for k in range(nombre)]

    choix = {}
    for k in repartir([k for k, n in enumerate(natures) if n == "chant"], nb_chant):
        choix[k] = "chant"
    for k in repartir([k for k, n in enumerate(natures) if n == "danse"], nb_danse):
        choix[k] = "danse"
    if nb_danse and not any(v == "danse" for v in choix.values()):
        # chanson sans passage instrumental : on danse sur des passages chantés non choisis
        reste = [k for k, n in enumerate(natures) if n == "chant" and k not in choix]
        for k in repartir(reste, max(1, nb_danse // 2)):
            choix[k] = "danse"
    return nouveaux, dict(sorted(choix.items()))


def _source_video(taille, boucle):
    """Filtre FFmpeg : vidéo placée dans le cadre avec fond flou (comme les photos)."""
    w, h = int(taille[0] * MARGE_ZOOM), int(taille[1] * MARGE_ZOOM)
    fin = ",tpad=stop_mode=clone:stop_duration=2" if not boucle else ""
    return (f"[0:v]fps={FPS}{fin},split[s1][s2];"
            f"[s1]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=30:2,"
            f"eq=brightness=-0.22[fond];"
            f"[s2]scale={w}:{h}:force_original_aspect_ratio=decrease[devant];"
            f"[fond][devant]overlay=(W-w)/2:(H-h)/2,")


def rendre_plan(source, debut, fin, taille, beats, mouvement, effets, calques, sortie: Path,
                type_source="image", look=""):
    """Rend un plan vidéo entre deux temps forts.

    type_source : « image » (photo préparée), « animation » (vidéo IA en boucle)
    ou « levres » (vidéo du visage qui chante, déjà calée sur ce passage).
    """
    duree = fin - debut
    nb = max(1, round(duree * FPS))
    w, h = taille
    beats_locaux = [round((b - debut) * FPS) for b in beats if debut <= b < fin] if effets != "simple" else []
    if type_source == "levres":  # mouvement très doux pour garder le visage net
        z, x, y = f"'1+0.05*(on/{max(1, nb - 1)})'", "'iw/2-(iw/zoom/2)'", "'ih/2-(ih/zoom/2)'"
    else:
        z, x, y = _expr_mouvement(mouvement, nb, beats_locaux)
    vf = f"zoompan=z={z}:x={x}:y={y}:d=1:s={w}x{h}:fps={FPS}"
    if beats_locaux:
        flash = "+".join(f"0.10*max(0\\,1-abs(t-{(b / FPS):.3f})/0.12)" for b in beats_locaux)
        vf += f",eq=brightness='{flash}':eval=frame"
    if look:
        vf += "," + look
    vf += ",format=yuv420p"

    if type_source == "image":
        entrees = ["-loop", "1", "-framerate", FPS, "-t", f"{duree:.3f}", "-i", source]
        graphe = f"[0:v]{vf}[v0]"
    else:
        boucle = type_source == "animation"
        entrees = (["-stream_loop", "-1"] if boucle else []) + ["-i", source]
        graphe = _source_video(taille, boucle) + f"{vf}[v0]"
    courant = "v0"
    for k, (png, a, b) in enumerate(calques, start=1):
        entrees += ["-loop", "1", "-framerate", FPS, "-t", f"{duree:.3f}", "-i", png]
        a_loc, b_loc = max(0.0, a - debut), min(duree, b - debut)
        graphe += (f";[{courant}][{k}:v]overlay=0:0:format=auto:"
                   f"enable='between(t\\,{a_loc:.3f}\\,{b_loc:.3f})'[v{k}]")
        courant = f"v{k}"
    lancer_ffmpeg([*entrees, "-filter_complex", graphe, "-map", f"[{courant}]",
                   "-frames:v", nb, "-r", FPS, "-an", "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", 20, "-pix_fmt", "yuv420p", sortie], "Rendu d'un plan")
    return sortie


def analyser_et_decouper(audio: Path, effets, journal=print):
    journal("Analyse du rythme de la chanson…")
    analyse = analyser_rythme(audio)
    plans = decouper_en_plans(analyse, effets)
    journal(f"Tempo détecté : {analyse['tempo']:.0f} BPM — {len(plans)} plans synchronisés.")
    return analyse, plans


def fabriquer_clip(*, audio: Path, photos, dossier: Path, formats, effets, titre, artiste,
                   paroles_synchro=None, journal=print, graine=None, look="", animations=None,
                   levres=None, analyse=None, plans=None):
    """Fabrique le clip complet dans chaque format demandé. Retourne {format: fichier mp4}.

    animations : {photo: vidéo IA en boucle} — remplace l'animation classique de ces photos.
    levres : {numéro de plan: vidéo du visage qui chante} — utilisé tel quel pour ces plans.
    """
    photos = [Path(p) for p in photos]
    if not photos:
        raise ValueError("Aucune photo fournie pour le clip.")
    animations = {Path(k): Path(v) for k, v in (animations or {}).items()}
    levres = levres or {}
    hasard = random.Random(graine)
    if analyse is None or plans is None:
        analyse, plans = analyser_et_decouper(audio, effets, journal)
    filtre_look = LOOKS.get(look, look or "")

    # Ordre des photos : on passe par toutes les photos avant d'en répéter une.
    ordre = []
    while len(ordre) < len(plans):
        tour = photos[:]
        hasard.shuffle(tour)
        if ordre and tour[0] == ordre[-1] and len(tour) > 1:
            tour[0], tour[1] = tour[1], tour[0]
        ordre += tour

    resultats = {}
    for fmt in formats:
        taille = FORMATS[fmt]
        travail = dossier / f"_travail_{fmt.replace(':', 'x')}"
        travail.mkdir(parents=True, exist_ok=True)
        images = {p: preparer_image(p, taille, travail / f"photo_{i}.jpg") for i, p in enumerate(photos)}
        titre_png = carton_titre(titre, artiste, taille, travail / "titre.png")
        sign_png = signature(taille, travail / "signature.png")
        lignes = []
        for i, l in enumerate(paroles_synchro or []):
            lignes.append((image_ligne_paroles(l["texte"], taille, travail / f"ligne_{i}.png"), l["debut"], l["fin"]))

        liste = []
        for i, (debut, fin) in enumerate(plans):
            calques = [(titre_png, 0.2, 4.5)] if debut < 4.5 else []
            calques += [(png, a, b) for png, a, b in lignes if a < fin and b > debut]
            if fin > analyse["duree"] - 6:
                calques.append((sign_png, analyse["duree"] - 6, analyse["duree"]))
            sortie = travail / f"plan_{i:04d}.mp4"
            mouvement = MOUVEMENTS[i % len(MOUVEMENTS)] if effets != "simple" else hasard.choice(MOUVEMENTS)
            photo = ordre[i]
            if i in levres:
                source, type_source = levres[i], "levres"
            elif photo in animations:
                source, type_source = animations[photo], "animation"
            else:
                source, type_source = images[photo], "image"
            try:
                rendre_plan(source, debut, fin, taille, analyse["beats"], mouvement, effets, calques, sortie,
                            type_source=type_source, look=filtre_look)
            except RuntimeError:
                if type_source == "image":
                    raise
                # vidéo IA illisible : on retombe sur la photo animée classiquement
                rendre_plan(images[photo], debut, fin, taille, analyse["beats"], mouvement, effets, calques,
                            sortie, look=filtre_look)
            liste.append(sortie)
            if i % 10 == 0:
                journal(f"Clip {fmt} : plan {i + 1}/{len(plans)}")

        fichier_liste = travail / "liste.txt"
        fichier_liste.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in liste), encoding="utf-8")
        final = dossier / f"clip_{fmt.replace(':', 'x')}.mp4"
        lancer_ffmpeg(["-f", "concat", "-safe", 0, "-i", fichier_liste, "-i", audio,
                       "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                       "-shortest", "-movflags", "+faststart",
                       "-metadata", f"title={titre}", "-metadata", f"artist={artiste}", final], "Assemblage du clip")
        shutil.rmtree(travail, ignore_errors=True)
        resultats[fmt] = final
        journal(f"Clip {fmt} terminé.")
    (dossier / "analyse_rythme.json").write_text(
        json.dumps({"tempo": analyse["tempo"], "plans": plans}, indent=1), encoding="utf-8")
    return resultats


def apercu_clip(clip: Path, sortie: Path, longueur=30):
    """Extrait de 30 s du clip avec le filigrane « APERÇU »."""
    import subprocess
    from outils import ffmpeg
    sonde = subprocess.run([ffmpeg(), "-i", str(clip)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace").stderr
    import re
    m = re.search(r"Stream.*Video.* (\d{3,4})x(\d{3,4})", sonde)
    taille = (int(m.group(1)), int(m.group(2))) if m else (1920, 1080)
    png = filigrane_apercu(taille, sortie.with_suffix(".png"))
    lancer_ffmpeg(["-ss", 20, "-t", longueur, "-i", clip, "-i", png, "-filter_complex",
                   "[0:v][1:v]overlay=0:0,format=yuv420p[v]", "-map", "[v]", "-map", "0:a",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", 26, "-c:a", "aac", "-b:a", "128k",
                   "-movflags", "+faststart", sortie], "Aperçu du clip")
    png.unlink(missing_ok=True)
    return sortie


def fabriquer_pochette(photo: Path, titre, artiste, sortie: Path):
    """Pochette carrée 3000 x 3000 (format exigé par les plateformes de streaming)."""
    taille = 3000
    img = ImageOps.fit(ImageOps.exif_transpose(Image.open(photo)).convert("RGB"), (taille, taille),
                       Image.LANCZOS, centering=(0.5, 0.35))
    degrade = Image.new("L", (1, taille))
    for yy in range(taille):
        degrade.putpixel((0, yy), int(max(0, (yy - taille * 0.5) / (taille * 0.5)) * 210))
    noir = Image.new("RGB", (taille, taille), (0, 0, 0))
    img = Image.composite(noir, img, degrade.resize((taille, taille)))
    d = ImageDraw.Draw(img)
    f_titre = police(230)
    lignes = _couper_lignes(titre.upper(), f_titre, taille * 0.88, d)[:3]
    y = taille * 0.80 - (len(lignes) - 1) * 250
    for l in lignes:
        _texte_contour(d, (taille / 2, y), l, f_titre, ep=6)
        y += 250
    if artiste:
        _texte_contour(d, (taille / 2, y + 30), artiste, police(130, grasse=False), couleur=(255, 215, 120), ep=4)
    img.save(sortie, quality=95)
    return sortie
