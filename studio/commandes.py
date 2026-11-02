"""Gestion des commandes clients et enchaînement de toutes les étapes."""
import json
import os
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

import clip as module_clip
import mixage
import musique
import separation
import video_ia
import texte
import voix
from config import DOSSIER_COMMANDES, FORMULES, LANGUES, STYLES

def preparer_paroles(texte_paroles: str) -> str:
    return texte.nettoyer_paroles(texte_paroles)


def _slug(texte):
    import unicodedata
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", texte).strip("_")[:40] or "client"


# ---------------------------------------------------------------------------
# Fiches de commande
# ---------------------------------------------------------------------------
def creer_commande(fiche: dict) -> Path:
    date = datetime.now()
    nom = f"{date:%Y-%m-%d_%H%M}_{_slug(fiche['client'])}_{fiche['formule']}"
    dossier = DOSSIER_COMMANDES / nom
    for sous in ("entrees", "travail", "livraison"):
        (dossier / sous).mkdir(parents=True, exist_ok=True)
    fiche = {**fiche, "id": nom, "date": date.isoformat(timespec="minutes"), "statut": "Nouvelle"}
    enregistrer_fiche(dossier, fiche)
    return dossier


def lire_fiche(dossier: Path) -> dict:
    return json.loads((dossier / "fiche.json").read_text(encoding="utf-8"))


def enregistrer_fiche(dossier: Path, fiche: dict):
    (dossier / "fiche.json").write_text(json.dumps(fiche, ensure_ascii=False, indent=2), encoding="utf-8")


def lister_commandes():
    if not DOSSIER_COMMANDES.exists():
        return []
    fiches = []
    for d in sorted(DOSSIER_COMMANDES.iterdir(), reverse=True):
        if (d / "fiche.json").exists():
            try:
                fiches.append((d, lire_fiche(d)))
            except json.JSONDecodeError:
                pass
    return fiches


def maj_statut(dossier: Path, statut: str, **extra):
    fiche = lire_fiche(dossier)
    fiche["statut"] = statut
    fiche.update(extra)
    enregistrer_fiche(dossier, fiche)


# ---------------------------------------------------------------------------
# Étape 1 : la chanson
# ---------------------------------------------------------------------------
def fabriquer_chanson(dossier: Path, enregistrements, journal=print):
    fiche = lire_fiche(dossier)
    formule = FORMULES[fiche["formule"]]
    travail, livraison = dossier / "travail", dossier / "livraison"
    maj_statut(dossier, "Chanson en cours")

    # 1. Composition (d'abord : si le moteur musical a un souci, on le sait tout de suite)
    description = musique.construire_description(
        fiche["style"], fiche["ambiance"], fiche["instruments"], fiche["voix_genre"], fiche.get("description", ""),
        voix_solo=not fiche.get("voix_ia"))
    fiche["description_ia"] = description
    enregistrer_fiche(dossier, fiche)
    duree = min(float(fiche["duree"]), formule["duree_max"])
    paroles_propres = preparer_paroles(fiche.get("paroles", ""))
    if texte.mots_chantes(paroles_propres) >= 15:
        besoin = texte.duree_necessaire(paroles_propres)
        if besoin > duree:  # paroles trop longues pour la durée : on allonge, puis on coupe si besoin
            nouvelle = min(float(formule["duree_max"]), round(besoin / 10) * 10)
            if nouvelle > duree:
                journal(f"Paroles longues : durée portée de {int(duree)} s à {int(nouvelle)} s pour bien les chanter.")
                duree = nouvelle
            paroles_propres, coupees = texte.ajuster_paroles(paroles_propres, duree)
            if coupees:
                journal(f"Attention : les paroles dépassent ce que permet la formule ({int(duree)} s). "
                        "Les dernières parties ont été retirées. Choisissez une formule plus longue pour tout garder.")
    fichiers, paroles = musique.generer_chansons(
        description=description, paroles=paroles_propres,
        langue=LANGUES.get(fiche["langue"], "fr"), bpm=fiche.get("bpm") or STYLES[fiche["style"]]["bpm"],
        duree=duree, versions=formule["versions"], dossier_sortie=travail, journal=journal,
        sujet=" ".join(x for x in (f"A {fiche['style']} song titled \"{fiche['titre']}\".",
                                   fiche.get("description", "").strip(), description) if x))

    # 2. Voix du client (apprentissage si nouvelle cliente)
    modele = None
    if not fiche.get("voix_ia"):
        modele = voix.modele_existant(fiche["client"]) if fiche.get("reutiliser_voix") else None
        if modele:
            journal("Voix du client déjà connue : réutilisation du modèle enregistré.")
        else:
            if not enregistrements:
                raise ValueError("Ajoutez les enregistrements de la voix du client "
                                 "(ou cochez « garder la voix de l'IA »).")
            copies = []
            for f in enregistrements:
                cible = dossier / "entrees" / Path(f).name
                shutil.copy(f, cible)
                copies.append(cible)
            modele = voix.entrainer_voix(fiche["client"], copies, formule["epoques_voix"], journal=journal)

    # 3. Voix du client + mixage pour chaque version
    versions = []
    for i, ia in enumerate(fichiers, start=1):
        journal(f"— Version {i}/{len(fichiers)} —")
        pistes = separation.separer(ia, travail / f"pistes_v{i}", quatre_pistes=formule["pistes_separees"],
                                    journal=journal, modele="htdemucs_ft" if modele else "htdemucs")
        voix_finale = pistes["voix"]
        if modele:
            journal("Remplacement de la voix de l'IA par la voix du client…")
            voix_finale = voix.convertir_voix(pistes["voix"], travail / f"voix_client_v{i}.wav",
                                              *modele, transposition=fiche.get("transposition", 0), journal=journal,
                                              genre=fiche.get("voix_genre", "Homme"))
        accompagnements = [p for n, p in pistes.items() if n != "voix"]
        master = mixage.mixer(voix_finale, accompagnements, livraison / f"version_{i}.wav")
        mp3 = mixage.exporter_mp3(master, livraison / f"version_{i}.mp3", fiche["titre"], fiche["client"])
        demo = mixage.extrait_demo(master, livraison / f"version_{i}_EXTRAIT.mp3")
        versions.append({"numero": i, "wav": str(master), "mp3": str(mp3), "extrait": str(demo),
                         "voix": str(voix_finale), "pistes": {k: str(v) for k, v in pistes.items()},
                         "paroles": paroles[i - 1] if i - 1 < len(paroles) else ""})
        journal(f"Version {i} prête.")

    maj_statut(dossier, "Chanson prête — choisir la version", versions=versions)
    journal("Chanson terminée. Écoutez les versions, puis passez à l'onglet « Clip ».")
    return versions


# ---------------------------------------------------------------------------
# Étape 2 : le clip et la livraison
# ---------------------------------------------------------------------------
PROMPT_CHANT = ("A music video performance. The singer sings the song with passion and emotion, lips moving "
                "in sync with the vocals, expressive natural hand gestures, head and shoulders moving to the "
                "rhythm, confident stage presence, cinematic lighting, sharp details, realistic.")
PROMPT_DANSE = ("A music video. The person dances to the beat with joy, moving shoulders, arms and hips "
                "rhythmically, smiling, energetic but natural body movement, cinematic lighting, realistic.")


def fabriquer_clip_et_livrer(dossier: Path, numero_version: int, photos, journal=print,
                             look="Naturel", description_clip="", photo_visage=None,
                             avec_chant=True, avec_danse=True):
    fiche = lire_fiche(dossier)
    formule = FORMULES[fiche["formule"]]
    version = next(v for v in fiche["versions"] if v["numero"] == int(numero_version))
    livraison = dossier / "livraison"
    final = livraison / "FINAL"
    final.mkdir(exist_ok=True)
    maj_statut(dossier, "Clip en cours", version_choisie=int(numero_version), look=look,
               description_clip=description_clip)

    photos_copiees = []
    for k, p in enumerate(photos, start=1):
        cible = dossier / "entrees" / f"photo_{k}{Path(p).suffix.lower()}"
        shutil.copy(p, cible)
        photos_copiees.append(cible)
    visage = None
    if photo_visage:
        visage = dossier / "entrees" / f"visage{Path(photo_visage).suffix.lower()}"
        shutil.copy(photo_visage, visage)

    titre = fiche["titre"]
    base = _slug(f"{fiche['client']}_{titre}")
    shutil.copy(version["wav"], final / f"{base}.wav")
    shutil.copy(version["mp3"], final / f"{base}.mp3")

    paroles_synchro = []
    if formule["karaoke"]:
        journal("Synchronisation des paroles sur la voix (karaoké)…")
        paroles_synchro = module_clip.synchroniser_paroles(Path(version["voix"]),
                                                           LANGUES.get(fiche["langue"], "fr"), journal)

    atelier = dossier / "travail" / "clip"
    shutil.rmtree(atelier, ignore_errors=True)
    atelier.mkdir(parents=True)
    analyse, plans = module_clip.analyser_et_decouper(Path(version["wav"]), formule["clip_effets"], journal)

    # Mémoire : sur Kaggle (≈ 30 Go), on met le moteur musical en pause pendant la vidéo IA
    moteur_en_pause = False
    if (formule.get("plans_chantes") or description_clip) and video_ia.performance_disponible() \
            and _memoire_totale_go() < 48:
        import demarrage
        demarrage.arreter_moteur_musical()
        moteur_en_pause = True
        journal("Moteur musical mis en pause pendant la création vidéo (mémoire).")
    try:
        return _clip_suite(dossier, fiche, formule, version, livraison, final, photos_copiees, visage, titre, base,
                           paroles_synchro, atelier, analyse, plans, look, description_clip, avec_chant,
                           avec_danse, journal)
    finally:
        if moteur_en_pause:
            import demarrage
            demarrage.demarrer_moteur_musical()
            journal("Moteur musical relancé (prêt dans 2 à 3 minutes).")


def _memoire_totale_go():
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError, AttributeError):
        return 64.0


def decouper_scenes(description: str, maximum=6):
    """« plage avec des filles ; deuxième photo devant des voitures… » -> une scène par morceau."""
    morceaux = [m.strip(" .,-") for m in re.split(r"[;\n]+|(?<=[.!?])\s+", description or "") if m.strip(" .,-")]
    propres = []
    for m in morceaux:
        m = re.sub(r"(?i)^(the\s+)?(first|second|third|fourth|fifth|other|last|\d+(st|nd|rd|th)?)\s+(photo|picture|image)\s*(with|in|on|at|:)?\s*", "", m)
        m = re.sub(r"(?i)^(photo|picture|image)\s*\d*\s*(with|in|on|at|:)?\s*", "", m)
        if len(m) > 3:
            propres.append(m)
    return propres[:maximum]


def _clip_suite(dossier, fiche, formule, version, livraison, final, photos_copiees, visage, titre, base,
                paroles_synchro, atelier, analyse, plans, look, description_clip, avec_chant, avec_danse, journal):
    # Décors décrits par le client : la personne est placée dans chaque scène (plage, voitures, forêt…)
    scenes_images = []
    if description_clip and video_ia.decors_disponibles():
        scenes = decouper_scenes(texte.traduire_en(description_clip))
        if scenes:
            taches_decors = [{"scene": sc, "photo": photos_copiees[k % len(photos_copiees)], "graine": 11 + k}
                             for k, sc in enumerate(scenes)]
            scenes_images = video_ia.generer_decors(taches_decors, atelier / "decors", journal)
            journal(f"{len(scenes_images)} décor(s) créé(s) avec la personne dedans.")
    elif description_clip:
        journal("Créateur de décors pas encore prêt ici : la description guide seulement l'ambiance.")
    if scenes_images:
        photos_copiees = scenes_images + photos_copiees  # les scènes passent en premier dans le montage

    # Le chanteur chante (lèvres + gestes) et danse : EchoMimicV3 (version en ligne)
    animations, levres = {}, {}
    nb_chant = formule.get("plans_chantes", 0) if avec_chant else 0
    nb_danse = formule.get("plans_danse", 0) if avec_danse else 0
    performance = (nb_chant or nb_danse) and video_ia.performance_disponible()
    if (nb_chant or nb_danse) and not performance:
        journal("Moteur « le chanteur chante et danse » pas encore prêt ici : clip fait avec les photos.")
    if performance:
        plans, choix = module_clip.preparer_plans_performance(plans, Path(version["voix"]), nb_chant, nb_danse)
        visages = [visage] if (visage and not scenes_images) else []  # avec décors : la personne y est déjà
        sources = visages + [p for p in photos_copiees if p != visage] or photos_copiees
        taches = []
        for n, (k, nature) in enumerate(choix.items()):
            a, b = plans[k]
            audio = atelier / f"perf_audio_{k:03d}.wav"
            piste = version["voix"] if nature == "chant" else version["wav"]
            from outils import lancer_ffmpeg
            lancer_ffmpeg(["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", piste, "-ac", 1, "-ar", 16000, audio],
                          "Découpe de l'audio d'un plan")
            # le visage principal pour les plans chantés, les autres photos en alternance pour varier
            image = sources[0] if (nature == "chant" and visages and n % 3 != 2) else sources[n % len(sources)]
            prompt = (PROMPT_CHANT if nature == "chant" else PROMPT_DANSE)
            if description_clip:
                prompt += " " + description_clip
            taches.append({"cle": k, "image": image, "audio": audio, "prompt": prompt, "graine": 43 + n})
        delai = 3600 * (2 if fiche["formule"] == "Ultra" else 1)  # au-delà : photos pour le reste
        faits = video_ia.generer_performances(taches, atelier / "performance", journal, delai_max=delai,
                                              deux_cartes=_memoire_totale_go() < 48)
        levres = dict(faits)
        journal(f"{sum(1 for k in faits if choix[k] == 'chant')} plan(s) chanté(s) et "
                f"{sum(1 for k in faits if choix[k] == 'danse')} plan(s) dansé(s) prêts.")

    # Photos animées par l'IA (Pro / Ultra, si le module est installé sur ce PC)
    if formule["photos_animees"] and not performance:
        if video_ia.animation_disponible():
            choix = photos_copiees[:formule["photos_animees"]]
            animations = video_ia.animer_photos(choix, description_clip, atelier / "animations", journal)
        else:
            journal("Animation IA non disponible ici : animation classique des photos.")

    # Le visage du client chante (Ultra, MuseTalk sur PC, si le module est installé)
    if formule["levres"] and not performance:
        if video_ia.levres_disponible():
            plans, numeros = module_clip.preparer_plans_levres(plans, Path(version["voix"]))
            if numeros:
                faits = video_ia.synchro_levres(visage or photos_copiees[0], Path(version["voix"]),
                                                [plans[i] for i in numeros], journal)
                faits = video_ia.nettoyer_levres(faits, atelier / "levres")
                levres = {numeros[k]: f for k, f in faits.items()}
                journal(f"{len(levres)} passage(s) chanté(s) par le visage du client.")
        else:
            journal("Synchro des lèvres non disponible ici : clip fait sans.")

    clips = module_clip.fabriquer_clip(
        audio=Path(version["wav"]), photos=photos_copiees, dossier=atelier, formats=formule["clip_formats"],
        effets=formule["clip_effets"], titre=titre, artiste=fiche["client"],
        paroles_synchro=paroles_synchro, journal=journal, look=look, animations=animations,
        levres=levres, analyse=analyse, plans=plans)
    renommes = {}
    for fmt, f in clips.items():
        cible = final / f"{base}_clip_{fmt.replace(':', 'x')}.mp4"
        shutil.move(str(f), cible)
        renommes[fmt] = cible
    principal = renommes.get("16:9") or next(iter(renommes.values()))
    apercu = module_clip.apercu_clip(principal, livraison / f"{base}_clip_APERCU.mp4")

    if formule["pochette"]:
        module_clip.fabriquer_pochette(photos_copiees[0], titre, fiche["client"], final / f"{base}_pochette.jpg")
    # Version instrumentale (karaoké) offerte à partir de Pro
    if formule["pochette"]:
        pistes = version["pistes"]
        accomp = [Path(p) for n, p in pistes.items() if n != "voix"]
        instru = final / f"{base}_instrumental.wav"
        mixage.additionner(accomp, instru)
    if formule["pistes_separees"]:
        dossier_pistes = final / "pistes_separees"
        dossier_pistes.mkdir(exist_ok=True)
        shutil.copy(version["voix"], dossier_pistes / "voix.wav")
        for n, p in version["pistes"].items():
            if n != "voix":
                shutil.copy(p, dossier_pistes / f"{n}.wav")

    paroles_txt = version.get("paroles") or fiche.get("paroles", "")
    if paroles_txt:
        (final / f"{base}_paroles.txt").write_text(paroles_txt, encoding="utf-8")

    archive = livraison / f"{base}_{fiche['formule']}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for f in final.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(final))
    maj_statut(dossier, "Livrée", archive=str(archive))
    journal("Commande terminée : tout est dans le dossier « livraison ».")
    return {"clips": {k: str(v) for k, v in renommes.items()}, "apercu": str(apercu), "archive": str(archive)}
