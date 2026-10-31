"""Bonheur Music Studio — application privée.

Sur PC : http://127.0.0.1:7870, accessible seulement depuis ce PC.
En ligne (BMS_EN_LIGNE=1) : même application, protégée par une clé secrète (BMS_CLE) que seule
la page de lancement de l'utilisateur connaît ; elle s'arrête seule après une longue inactivité.
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, make_response, redirect, request, send_file

sys.path.insert(0, str(Path(__file__).resolve().parent))

import clip as module_clip  # noqa: E402
import commandes  # noqa: E402
import demarrage  # noqa: E402
import musique  # noqa: E402
import video_ia  # noqa: E402
from config import (AMBIANCES, DOSSIER_APPLIO, DOSSIER_COMMANDES, FORMULES, INSTRUMENTS,  # noqa: E402
                    LANGUES, NIVEAUX_INSTRUMENT, NOM_STUDIO, STYLES)

PORT = int(os.environ.get("BMS_PORT", 7870))
EN_LIGNE = os.environ.get("BMS_EN_LIGNE") == "1"
CLE = os.environ.get("BMS_CLE", "")
INACTIVITE_MAX = int(os.environ.get("BMS_INACTIVITE_MAX", 50 * 60))  # en ligne : arrêt après 50 min sans rien
DERNIERE_ACTIVITE = [time.time()]
ICI = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 ** 3  # 2 Go d'envoi maximum
app.json.sort_keys = False  # garder l'ordre Standard, Pro, Ultra

# ---------------------------------------------------------------------------
# File d'attente : un seul travail à la fois (la carte graphique est partagée).
# ---------------------------------------------------------------------------
TRAVAUX = {}
FILE = queue.Queue()
VERROU = threading.Lock()


def nouveau_travail(type_, commande_id, fonction, *args):
    tid = uuid.uuid4().hex[:10]
    with VERROU:
        TRAVAUX[tid] = {"id": tid, "type": type_, "commande": commande_id, "etat": "en attente",
                        "journal": [], "resultat": None, "erreur": None,
                        "cree": datetime.now().isoformat(timespec="seconds")}
    FILE.put((tid, fonction, args))
    return tid


def _ouvrier():
    while True:
        tid, fonction, args = FILE.get()
        t = TRAVAUX[tid]
        t["etat"] = "en cours"

        def journal(msg, t=t):
            t["journal"].append(f"{datetime.now():%H:%M:%S}  {msg}")
            t["journal"] = t["journal"][-400:]

        try:
            t["resultat"] = fonction(*args, journal=journal)
            t["etat"] = "terminé"
        except Exception as e:  # on affiche l'erreur dans l'application
            t["etat"] = "erreur"
            t["erreur"] = str(e)
            journal("ERREUR : " + str(e))
            (DOSSIER_COMMANDES / "erreurs.log").open("a", encoding="utf-8").write(
                f"\n[{datetime.now()}] {t['type']} {t['commande']}\n{traceback.format_exc()}\n")
            try:
                commandes.maj_statut(DOSSIER_COMMANDES / t["commande"], "Erreur — voir le journal")
            except Exception:
                pass
        finally:
            FILE.task_done()


threading.Thread(target=_ouvrier, daemon=True).start()


def _dossier(commande_id) -> Path:
    d = (DOSSIER_COMMANDES / commande_id).resolve()
    if d.parent != DOSSIER_COMMANDES.resolve() or not (d / "fiche.json").exists():
        abort(404)
    return d


def _sauver_envois(champ, dossier_tmp: Path):
    chemins = []
    for f in request.files.getlist(champ):
        if f and f.filename:
            nom = Path(f.filename).name.replace(" ", "_")
            cible = dossier_tmp / f"{len(chemins) + 1:02d}_{nom}"
            f.save(cible)
            chemins.append(cible)
    return chemins


# ---------------------------------------------------------------------------
# Accès (version en ligne) : la page de lancement ouvre /?cle=… une fois, un cookie garde l'accès
# ---------------------------------------------------------------------------
PAGE_REFUSEE = """<!doctype html><meta charset="utf-8"><title>Bonheur Music Studio</title>
<body style="font-family:system-ui;background:#160f24;color:#f3eefc;display:grid;place-items:center;height:100vh;margin:0">
<div style="max-width:420px;text-align:center;padding:20px"><h1>Studio privé</h1>
<p>Ouvrez le studio depuis votre page « Bonheur Music Studio ».</p></div></body>"""


@app.before_request
def controle_acces():
    DERNIERE_ACTIVITE[0] = time.time()
    if not CLE:
        return None
    if request.args.get("cle") == CLE:
        reponse = make_response(redirect("/"))
        reponse.set_cookie("bms_cle", CLE, max_age=14 * 24 * 3600, httponly=True, samesite="Lax", secure=True)
        return reponse
    if request.cookies.get("bms_cle") != CLE:
        return PAGE_REFUSEE, 401


def _surveiller_inactivite():
    while True:
        time.sleep(60)
        occupe = any(t["etat"] in ("en attente", "en cours") for t in TRAVAUX.values())
        if occupe:
            DERNIERE_ACTIVITE[0] = time.time()
        elif time.time() - DERNIERE_ACTIVITE[0] > INACTIVITE_MAX:
            print("Studio inactif depuis longtemps : arrêt automatique (économise les heures de carte graphique).",
                  flush=True)
            demarrage.arreter_moteur_musical()
            os._exit(0)


if EN_LIGNE:
    threading.Thread(target=_surveiller_inactivite, daemon=True).start()


# ---------------------------------------------------------------------------
# Pages et API
# ---------------------------------------------------------------------------
@app.get("/")
def accueil():
    return send_file(ICI / "interface" / "index.html")


@app.get("/api/options")
def options():
    return jsonify({
        "studio": NOM_STUDIO,
        "styles": {k: v["bpm"] for k, v in STYLES.items()},
        "ambiances": list(AMBIANCES), "instruments": list(INSTRUMENTS),
        "niveaux": list(NIVEAUX_INSTRUMENT), "langues": list(LANGUES),
        "formules": FORMULES,
        "looks": list(module_clip.LOOKS),
        "en_ligne": EN_LIGNE,
    })


@app.get("/api/etat")
def etat():
    gpu = None
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            gpu = r.stdout.strip().splitlines()[0]
    except Exception:
        pass
    try:
        import demucs  # noqa: F401
        demucs_ok = True
    except ImportError:
        demucs_ok = False
    pret = musique.serveur_pret()
    return jsonify({
        "musique": pret,
        "musique_detail": "" if pret else demarrage.derniere_ligne_moteur(),
        "animation": video_ia.animation_disponible(),
        "levres": video_ia.levres_disponible(),
        "performance": video_ia.performance_disponible(),
        "performance_detail": _etat_performance(),
        "voix": (DOSSIER_APPLIO / "core.py").exists(),
        "separation": demucs_ok,
        "gpu": gpu,
        "file": sum(1 for t in TRAVAUX.values() if t["etat"] in ("en attente", "en cours")),
    })


def _etat_performance():
    f = Path(os.environ.get("BMS_ETAT_PERFORMANCE", "/nonexistent"))
    try:
        return f.read_text(encoding="utf-8").strip()[-160:]
    except OSError:
        return ""


@app.get("/api/commandes")
def liste():
    sortie = []
    for d, f in commandes.lister_commandes():
        sortie.append({k: f.get(k) for k in ("id", "date", "client", "contact", "formule", "prix", "paye",
                                              "titre", "style", "statut", "version_choisie")})
    return jsonify(sortie)


@app.get("/api/commandes/<cid>")
def detail(cid):
    d = _dossier(cid)
    fiche = commandes.lire_fiche(d)
    fiche["travaux"] = [t for t in TRAVAUX.values() if t["commande"] == cid]
    final = d / "livraison" / "FINAL"
    fiche["livrables"] = sorted(str(p) for p in final.rglob("*") if p.is_file()) if final.exists() else []
    return jsonify(fiche)


@app.post("/api/commandes")
def nouvelle():
    f = request.form
    if not f.get("client", "").strip() or not f.get("titre", "").strip():
        return jsonify({"erreur": "Le nom du client et le titre sont obligatoires."}), 400
    if f.get("style") not in STYLES or f.get("formule") not in FORMULES:
        return jsonify({"erreur": "Style ou formule inconnu."}), 400
    instruments = json.loads(f.get("instruments", "{}"))
    fiche = {
        "client": f["client"].strip(), "contact": f.get("contact", "").strip(),
        "formule": f["formule"], "prix": f.get("prix", "").strip(), "paye": False,
        "titre": f["titre"].strip(), "style": f["style"], "ambiance": f.get("ambiance"),
        "bpm": int(f.get("bpm") or STYLES[f["style"]]["bpm"]), "duree": int(f.get("duree") or 150),
        "langue": f.get("langue", "Français"), "voix_genre": f.get("voix_genre", "Homme"),
        "instruments": instruments, "description": f.get("description", ""),
        "paroles": f.get("paroles", ""), "transposition": int(f.get("transposition") or 0),
        "voix_ia": f.get("voix_ia") == "oui", "reutiliser_voix": f.get("reutiliser_voix") == "oui",
        "consentement": f.get("consentement") == "oui",
    }
    if not fiche["voix_ia"] and not fiche["consentement"]:
        return jsonify({"erreur": "Confirmez que le client est bien la personne dont la voix est utilisée."}), 400
    dossier = commandes.creer_commande(fiche)
    tmp = Path(tempfile.mkdtemp(prefix="bms_"))
    voix = _sauver_envois("voix", tmp)
    tid = nouveau_travail("chanson", dossier.name, _tache_chanson, dossier, voix, tmp)
    return jsonify({"commande": dossier.name, "travail": tid})


def _tache_chanson(dossier, voix, tmp, journal):
    try:
        return commandes.fabriquer_chanson(dossier, voix, journal=journal)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.post("/api/commandes/<cid>/clip")
def clip(cid):
    d = _dossier(cid)
    fiche = commandes.lire_fiche(d)
    if not fiche.get("versions"):
        return jsonify({"erreur": "La chanson n'est pas encore prête."}), 400
    tmp = Path(tempfile.mkdtemp(prefix="bms_"))
    photos = _sauver_envois("photos", tmp)
    if not photos:
        return jsonify({"erreur": "Ajoutez au moins une photo (idéalement 8 à 20)."}), 400
    visage = _sauver_envois("visage", tmp)
    reglages = {"look": request.form.get("look", "Naturel"),
                "description_clip": request.form.get("description_clip", "").strip(),
                "photo_visage": visage[0] if visage else None,
                "avec_chant": request.form.get("avec_chant", "oui") == "oui",
                "avec_danse": request.form.get("avec_danse", "oui") == "oui"}
    tid = nouveau_travail("clip", cid, _tache_clip, d, int(request.form.get("version", 1)), photos, reglages, tmp)
    return jsonify({"travail": tid})


def _tache_clip(d, version, photos, reglages, tmp, journal):
    try:
        return commandes.fabriquer_clip_et_livrer(d, version, photos, journal=journal, **reglages)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.post("/api/commandes/<cid>/paye")
def paye(cid):
    d = _dossier(cid)
    fiche = commandes.lire_fiche(d)
    fiche["paye"] = not fiche.get("paye")
    commandes.enregistrer_fiche(d, fiche)
    return jsonify({"paye": fiche["paye"]})


@app.post("/api/commandes/<cid>/ouvrir")
def ouvrir(cid):
    d = _dossier(cid) / "livraison"
    if hasattr(os, "startfile") and not EN_LIGNE:
        os.startfile(d)  # ouvre le dossier dans l'Explorateur Windows
    return jsonify({"ok": True})


@app.get("/api/travaux/<tid>")
def travail(tid):
    t = TRAVAUX.get(tid)
    return jsonify(t) if t else (jsonify({"erreur": "inconnu"}), 404)


@app.get("/fichier")
def fichier():
    chemin = Path(request.args.get("chemin", "")).resolve()
    racine = DOSSIER_COMMANDES.resolve()
    if racine not in chemin.parents or not chemin.is_file():
        abort(404)
    return send_file(chemin, as_attachment=request.args.get("telecharger") == "1", conditional=True)


@app.post("/api/arreter")
def arreter():
    """Bouton « Fermer le studio » : arrête le moteur musical puis le studio."""
    if any(t["etat"] in ("en attente", "en cours") for t in TRAVAUX.values()) and request.args.get("forcer") != "1":
        return jsonify({"erreur": "Un travail est en cours. Attendez la fin avant de fermer le studio."}), 409

    def fin():
        demarrage.arreter_moteur_musical()
        os._exit(0)
    threading.Timer(0.5, fin).start()
    return jsonify({"ok": True})


if __name__ == "__main__":
    demarrage.rediriger_sorties_si_sans_console()
    adresse = f"http://127.0.0.1:{PORT}"
    if demarrage.port_occupe(PORT):  # déjà ouvert : on affiche simplement la page
        webbrowser.open(adresse)
        sys.exit(0)
    DOSSIER_COMMANDES.mkdir(exist_ok=True)
    demarrage.demarrer_moteur_musical()
    if "--sans-navigateur" not in sys.argv and not EN_LIGNE:
        threading.Timer(1.5, lambda: webbrowser.open(adresse)).start()
    print(f"\n  {NOM_STUDIO} est ouvert sur {adresse}\n", flush=True)
    try:
        app.run(host="127.0.0.1", port=PORT, threaded=True)
    finally:
        demarrage.arreter_moteur_musical()
