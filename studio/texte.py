"""Préparation des textes pour les IA : paroles propres, traduction des descriptions, durée utile."""
import re
import unicodedata

_TRADUCTEUR = None
MOTS_FR = {"le", "la", "les", "des", "une", "avec", "dans", "sur", "et", "très", "pour", "du", "au", "aux",
           "est", "qui", "en", "un", "de", "son", "ses", "sa", "nous", "vous", "elle", "il"}

BALISES = [  # l'IA musicale comprend ces balises anglaises
    (("pre-refrain", "pré-refrain", "pre refrain", "pre-chorus", "prerefrain"), "[Pre-Chorus]"),
    (("refrain", "chorus", "hook"), "[Chorus]"),
    (("couplet", "verse"), "[Verse]"),
    (("pont", "bridge"), "[Bridge]"),
    (("intro",), "[Intro]"),
    (("outro", "fin", "final"), "[Outro]"),
    (("solo", "instrumental", "break", "pause"), "[Instrumental]"),
    (("parlé", "parle", "spoken", "dj", "animation", "shout", "dédicace", "dedicace"), "[Spoken]"),
]


def _balise(contenu):
    t = contenu.lower()
    for mots, balise in BALISES:
        if any(re.search(r"\b" + re.escape(m) + r"\b", t) for m in mots):
            return balise
    return "[Verse]"


def nettoyer_paroles(texte: str) -> str:
    """Enlève la mise en forme (**gras**, émojis…) et transforme les titres de parties en balises."""
    texte = (texte or "").replace("\r\n", "\n")
    lignes = []
    for ligne in texte.split("\n"):
        brut = re.sub(r"[*_#`>~]+", "", ligne).strip()
        brut = "".join(c for c in brut if unicodedata.category(c)[0] in "LNPZ" or c in "'’-,.!?;:()[] ")
        brut = re.sub(r"\s+", " ", brut).strip()
        m = re.fullmatch(r"\[([^\]]*)\]\s*", brut) or re.fullmatch(r"\(([^)]*)\)\s*", brut) if brut else None
        if m is None and brut and re.fullmatch(r"(?i)(couplet|refrain|intro|outro|pont|bridge|verse|chorus)\b.{0,40}:?", brut):
            m = re.match(r"(.*)", brut)
        if m:
            lignes.append(_balise(m.group(1)))
        elif brut:
            lignes.append(brut)
        elif lignes and lignes[-1] != "":
            lignes.append("")
    texte = "\n".join(lignes).strip()
    texte = re.sub(r"\n{3,}", "\n\n", texte)
    if texte and not texte.startswith("["):
        texte = "[Verse]\n" + texte
    return texte


def mots_chantes(paroles: str) -> int:
    return len(re.findall(r"\w+", re.sub(r"\[[^\]]*\]", " ", paroles or "")))


def duree_necessaire(paroles: str) -> float:
    """Durée raisonnable pour chanter ces paroles sans les bousculer (≈ 2 mots/s + intro/pauses)."""
    return 25 + mots_chantes(paroles) / 2.0


def ajuster_paroles(paroles: str, duree: float):
    """Coupe les paroles trop longues à la fin d'une partie, pour tenir dans la durée."""
    if duree_necessaire(paroles) <= duree:
        return paroles, False
    parties = re.split(r"(?=^\[)", paroles, flags=re.M)
    gardees = []
    for p in parties:
        if gardees and duree_necessaire("".join(gardees + [p])) > duree:
            break
        gardees.append(p)
    resultat = "".join(gardees).strip()
    if not resultat.rstrip().endswith("[Outro]"):
        resultat += "\n\n[Outro]"
    return resultat, True


def est_francais(texte: str) -> bool:
    mots = re.findall(r"[a-zàâçéèêëîïôûùüÿœ]+", (texte or "").lower())
    return bool(mots) and (sum(m in MOTS_FR for m in mots) / len(mots) > 0.08 or
                           any(c in texte for c in "éèêàçù"))


def traduire_en(texte: str) -> str:
    """Traduit une description française en anglais (les IA d'images et de musique comprennent mieux)."""
    global _TRADUCTEUR
    texte = (texte or "").strip()
    if not texte or not est_francais(texte):
        return texte
    try:
        if _TRADUCTEUR is None:
            from transformers import pipeline
            _TRADUCTEUR = pipeline("translation", model="Helsinki-NLP/opus-mt-fr-en", device=-1)
        morceaux = [m.strip() for m in re.split(r"(?<=[.;!?\n])\s+", texte) if m.strip()]
        sorties = _TRADUCTEUR(morceaux, max_length=400)
        return " ".join(s["translation_text"] for s in sorties)
    except Exception as e:  # pas de traducteur : on garde le texte d'origine
        print("traduction impossible :", e, flush=True)
        return texte
