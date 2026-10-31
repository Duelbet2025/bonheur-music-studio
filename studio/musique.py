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


def _fin_journal_moteur(n=12):
    """Lignes utiles de la fin du journal du moteur musical (pour comprendre une erreur)."""
    try:
        from demarrage import JOURNAL_MOTEUR
        lignes = JOURNAL_MOTEUR.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    utiles = [l for l in lignes if any(m in l for m in ("Error", "error", "Exception", "OOM", "out of memory",
                                                        "NaN", "Traceback", "failed", "Killed"))]
    return "\n".join((utiles or lignes)[-n:])[-1500:]


def _une_generation(demande, journal, delai_max, etiquette):
    rep = requests.post(f"{URL_ACESTEP}/release_task", json=demande, timeout=60)
    rep.raise_for_status()
    corps = rep.json()
    if corps.get("code") != 200 or not corps.get("data"):
        raise ErreurMusique(f"Refus du moteur musical : {corps.get('error')}")
    id_tache = corps["data"]["task_id"]
    debut, dernier = time.time(), 0
    while True:
        time.sleep(4)
        rep = requests.post(f"{URL_ACESTEP}/query_result", json={"task_id_list": [id_tache]}, timeout=60)
        rep.raise_for_status()
        entrees = rep.json().get("data") or []
        if not entrees:
            continue
        entree = entrees[0]
        statut = entree.get("status")
        if statut == 1:
            return _extraire_resultats(entree)
        if statut == 2:
            raise ErreurMusique("échec du moteur musical. " + (_fin_journal_moteur() or str(entree.get("result"))[:300]))
        if time.time() - debut > delai_max:
            raise ErreurMusique(f"la composition dépasse {delai_max // 60} min.")
        if time.time() - dernier > 30:  # journal plus léger : une ligne toutes les 30 s
            journal(f"{etiquette} : composition en cours… {int(time.time() - debut)} s")
            dernier = time.time()


def generer_chansons(*, description, paroles, langue, bpm, duree, versions,
                     dossier_sortie: Path, journal=print, delai_max=2400, sujet=""):
    """Compose les versions une par une (moins de mémoire, et une version ratée n'annule pas les autres).

    Retourne (liste des fichiers .wav, liste des paroles).
    """
    if not serveur_pret():
        raise ErreurMusique("Le moteur musical n'est pas encore démarré : attendez que son voyant soit vert.")

    base = {
        "prompt": description,
        "lyrics": paroles.strip() if paroles else "",
        "vocal_language": langue,
        "bpm": int(bpm) if bpm else None,
        "audio_duration": float(duree),
        "batch_size": 1,
        "thinking": True,
        "audio_format": "wav",
        "use_random_seed": True,
    }
    if not base["lyrics"]:
        journal("Écriture des paroles par l'IA…")
        base["lyrics"] = ecrire_paroles(sujet or description, langue)
    base = {k: v for k, v in base.items() if v is not None}

    dossier_sortie.mkdir(parents=True, exist_ok=True)
    fichiers, paroles_finales, erreurs = [], [], []
    for v in range(1, int(versions) + 1):
        etiquette = f"Version {v}/{versions}"
        journal(f"{etiquette} : envoi au moteur musical ({int(duree)} s)…")
        resultats = None
        for essai, reglage in enumerate(({}, {"thinking": False})):
            try:
                resultats = _une_generation({**base, **reglage}, journal, delai_max, etiquette)
                break
            except (ErreurMusique, requests.RequestException) as e:
                erreurs.append(f"{etiquette} : {e}")
                journal(f"{etiquette} : {e}")
                if essai == 0:
                    journal(f"{etiquette} : nouvel essai en mode rapide…")
        for res in resultats or []:
            lien = res.get("file")
            if not lien:
                continue
            if not lien.startswith("http"):
                lien = f"{URL_ACESTEP}{lien}"  # le serveur encode déjà le chemin
            audio = requests.get(lien, timeout=300)
            audio.raise_for_status()
            n = len(fichiers) + 1
            cible = dossier_sortie / f"version_{n}_ia.wav"
            cible.write_bytes(audio.content)
            fichiers.append(cible)
            paroles_finales.append(res.get("lyrics") or base.get("lyrics", ""))
            (dossier_sortie / f"version_{n}_infos.json").write_text(
                json.dumps({"metas": res.get("metas") or {}, "paroles": res.get("lyrics"),
                            "graine": res.get("seed_value")}, ensure_ascii=False, indent=2), encoding="utf-8")
            journal(f"{etiquette} composée.")
            break
    if not fichiers:
        raise ErreurMusique("Aucune version n'a pu être composée. " + (erreurs[-1] if erreurs else ""))
    journal(f"{len(fichiers)} version(s) composée(s).")
    return fichiers, paroles_finales
