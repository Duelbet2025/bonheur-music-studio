"""Génération de la chanson avec ACE-Step 1.5 (serveur local sur le port 8001)."""
import json
import time
from pathlib import Path
import requests

from config import AMBIANCES, INSTRUMENTS, NIVEAUX_INSTRUMENT, STYLES, URL_ACESTEP


class ErreurMusique(Exception):
    pass


def serveur_pret() -> bool:
    try:
        return requests.get(f"{URL_ACESTEP}/health", timeout=3).status_code == 200
    except requests.RequestException:
        return False


def construire_description(style, ambiance, instruments, voix_genre, description_libre=""):
    """Assemble la description envoyée à l'IA à partir des choix du formulaire."""
    morceaux = [STYLES[style]["tags"]]
    if ambiance in AMBIANCES:
        morceaux.append(AMBIANCES[ambiance])
    for nom, niveau in (instruments or {}).items():
        modele = NIVEAUX_INSTRUMENT.get(niveau)
        if modele and nom in INSTRUMENTS:
            morceaux.append(modele.format(INSTRUMENTS[nom]))
    absents = [INSTRUMENTS[n] for n, niv in (instruments or {}).items()
               if NIVEAUX_INSTRUMENT.get(niv) is None and n in INSTRUMENTS]
    if absents:
        morceaux.append("no " + ", no ".join(absents))
    morceaux.append("male lead vocals" if voix_genre == "Homme" else "female lead vocals")
    if description_libre.strip():
        morceaux.append(description_libre.strip())
    morceaux.append("high quality studio mix")
    return ", ".join(morceaux)


def _extraire_resultats(entree):
    resultat = entree.get("result")
    if isinstance(resultat, str):
        try:
            resultat = json.loads(resultat)
        except json.JSONDecodeError:
            resultat = []
    if isinstance(resultat, dict):
        resultat = [resultat]
    return resultat or []


def ecrire_paroles(sujet: str, langue: str) -> str:
    """Demande à l'IA d'écrire des paroles (couplets, refrain) sur un sujet."""
    rep = requests.post(f"{URL_ACESTEP}/v1/create_sample",
                        json={"query": sujet, "instrumental": False, "vocal_language": langue}, timeout=600)
    rep.raise_for_status()
    corps = rep.json()
    paroles = (corps.get("data") or {}).get("lyrics", "")
    if corps.get("code") != 200 or not paroles.strip():
        raise ErreurMusique("L'IA n'a pas pu écrire les paroles. Écrivez-les dans la commande.")
    return paroles


def generer_chansons(*, description, paroles, langue, bpm, duree, versions,
                     dossier_sortie: Path, journal=print, delai_max=1800, sujet=""):
    """Envoie la commande à ACE-Step et télécharge les versions générées.

    Retourne la liste des fichiers .wav créés.
    """
    if not serveur_pret():
        raise ErreurMusique(
            "Le moteur musical ACE-Step n'est pas démarré. "
            "Lancez l'application avec « lancer_studio.bat »."
        )

    demande = {
        "prompt": description,
        "lyrics": paroles.strip() if paroles else "",
        "vocal_language": langue,
        "bpm": int(bpm) if bpm else None,
        "audio_duration": float(duree),
        "batch_size": int(versions),
        "thinking": True,
        "audio_format": "wav",
        "use_random_seed": True,
    }
    if not demande["lyrics"]:
        # Pas de paroles : l'IA les écrit d'abord, puis on garde le tempo et la durée choisis.
        journal("Écriture des paroles par l'IA…")
        demande["lyrics"] = ecrire_paroles(sujet or description, langue)
    demande = {k: v for k, v in demande.items() if v is not None}

    journal(f"Envoi au moteur musical ({versions} version(s), {int(duree)} s)…")
    rep = requests.post(f"{URL_ACESTEP}/release_task", json=demande, timeout=60)
    rep.raise_for_status()
    corps = rep.json()
    if corps.get("code") != 200 or not corps.get("data"):
        raise ErreurMusique(f"Refus du moteur musical : {corps.get('error')}")
    id_tache = corps["data"]["task_id"]

    debut = time.time()
    while True:
        time.sleep(4)
        rep = requests.post(f"{URL_ACESTEP}/query_result",
                            json={"task_id_list": [id_tache]}, timeout=60)
        rep.raise_for_status()
        entrees = rep.json().get("data") or []
        if not entrees:
            continue
        entree = entrees[0]
        statut = entree.get("status")
        if statut == 1:
            break
        if statut == 2:
            raise ErreurMusique(f"La génération a échoué : {entree.get('result')}")
        if time.time() - debut > delai_max:
            raise ErreurMusique("La génération prend trop de temps (plus de 30 min).")
        journal(f"Composition en cours… {int(time.time() - debut)} s")

    dossier_sortie.mkdir(parents=True, exist_ok=True)
    fichiers, paroles_finales = [], []
    for i, res in enumerate(_extraire_resultats(entree), start=1):
        lien = res.get("file")
        if not lien:
            continue
        if not lien.startswith("http"):
            lien = f"{URL_ACESTEP}{lien}"  # le serveur encode déjà le chemin
        audio = requests.get(lien, timeout=300)
        audio.raise_for_status()
        cible = dossier_sortie / f"version_{i}_ia.wav"
        cible.write_bytes(audio.content)
        fichiers.append(cible)
        paroles_finales.append(res.get("lyrics") or demande.get("lyrics", ""))
        meta = res.get("metas") or {}
        (dossier_sortie / f"version_{i}_infos.json").write_text(
            json.dumps({"metas": meta, "paroles": res.get("lyrics"), "graine": res.get("seed_value")},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    if not fichiers:
        raise ErreurMusique("Le moteur n'a renvoyé aucun fichier audio.")
    journal(f"{len(fichiers)} version(s) composée(s).")
    return fichiers, paroles_finales
