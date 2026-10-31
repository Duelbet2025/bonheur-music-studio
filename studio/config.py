"""Réglages du studio : styles musicaux, formules Standard / Pro / Ultra, chemins."""
import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_COMMANDES = Path(os.environ.get("BMS_COMMANDES") or RACINE / "commandes")
DOSSIER_VOIX = RACINE / "voix_clients"
DOSSIER_MOTEURS = RACINE / "moteurs"
DOSSIER_APPLIO = DOSSIER_MOTEURS / "Applio"

NOM_STUDIO = "Bonheur Music Studio"
URL_ACESTEP = "http://127.0.0.1:8001"

# ---------------------------------------------------------------------------
# Styles musicaux. "tags" est la description envoyée à l'IA (en anglais, car le
# modèle comprend mieux l'anglais). Les styles rares sont décrits par leurs
# instruments pour aider l'IA.
# ---------------------------------------------------------------------------
STYLES = {
    "Coupé-décalé": {
        "tags": "Coupé-Décalé, Ivorian dance music, Afropop, fast syncopated drum machine, "
                "rolling percussion, bright synth leads, energetic dancefloor, call and response vocals",
        "bpm": 125,
    },
    "Zouglou": {
        "tags": "Zouglou, Ivorian popular music, Afropop, acoustic and electric guitars, "
                "percussion, group choir vocals, storytelling, festive",
        "bpm": 110,
    },
    "Zouk": {
        "tags": "Zouk, French Caribbean, romantic zouk love, smooth synth pads, "
                "tanbou drum groove, warm bass, sensual R&B vocals",
        "bpm": 95,
    },
    "Kompa": {
        "tags": "Kompa, Haitian konpa, steady groove, guitar riffs, horn section, "
                "keyboard, romantic dance",
        "bpm": 105,
    },
    "Reggae": {
        "tags": "Roots reggae, one drop drums, offbeat guitar skank, deep bass line, "
                "organ bubble, warm vocals",
        "bpm": 75,
    },
    "Dancehall": {
        "tags": "Dancehall, Jamaican riddim, digital drums, heavy bass, energetic toasting vocals",
        "bpm": 98,
    },
    "Afrobeats": {
        "tags": "Afrobeats, Afropop, log drum, shakers, syncopated percussion, "
                "melodic guitar, smooth catchy vocals",
        "bpm": 105,
    },
    "Amapiano": {
        "tags": "Amapiano, South African house, log drum bass, shakers, jazzy piano chords, deep groove",
        "bpm": 112,
    },
    "Rumba congolaise / Soukous": {
        "tags": "Congolese rumba, Soukous, sweet highlife-style lead guitars, sebene, "
                "bass, snare rolls, harmonized vocals",
        "bpm": 120,
    },
    "Highlife": {
        "tags": "Highlife, West African, bright interlocking guitars, horns, percussion, joyful",
        "bpm": 115,
    },
    "Gospel africain": {
        "tags": "African gospel, praise and worship, choir, piano, organ, uplifting, spiritual",
        "bpm": 100,
    },
    "Rap / Hip-hop": {
        "tags": "Hip-hop, rap, trap drums, 808 bass, hi-hats, dark piano melody",
        "bpm": 90,
    },
    "R&B": {
        "tags": "Contemporary R&B, smooth, soulful, electric piano, soft drums, emotional vocals",
        "bpm": 80,
    },
    "Variété / Pop": {
        "tags": "Pop, catchy chorus, modern production, guitars, synths, upbeat",
        "bpm": 110,
    },
    "Slow / Ballade": {
        "tags": "Ballad, slow love song, piano, strings, emotional, intimate vocals",
        "bpm": 68,
    },
}

AMBIANCES = {
    "Joyeuse / festive": "joyful, festive, happy, celebration",
    "Romantique": "romantic, tender, love song",
    "Triste / émouvante": "sad, melancholic, emotional",
    "Énergique / danse": "energetic, danceable, powerful",
    "Calme / douce": "calm, soft, relaxing",
    "Spirituelle": "spiritual, uplifting, hopeful",
    "Sombre / dure": "dark, intense, aggressive",
}

INSTRUMENTS = {
    "Batterie": "drums",
    "Basse": "bass",
    "Guitare": "guitar",
    "Piano": "piano",
    "Synthé": "synthesizer",
    "Cuivres (trompettes, sax)": "brass section, saxophone",
    "Cordes (violons)": "strings",
    "Percussions africaines": "African percussion, djembe, talking drum",
    "Orgue": "organ",
    "Chœurs": "backing choir",
}

NIVEAUX_INSTRUMENT = {
    "Auto": "",                 # le style décide (par défaut)
    "Absent": None,
    "Léger": "subtle {}",
    "Normal": "{}",
    "Dominant": "prominent dominant {}",
}

LANGUES = {
    "Français": "fr",
    "Anglais": "en",
    "Espagnol": "es",
    "Portugais": "pt",
    "Autre langue (laisser l'IA détecter)": "unknown",
}

# ---------------------------------------------------------------------------
# Formules vendues aux clients.
# ---------------------------------------------------------------------------
FORMULES = {
    "Standard": {
        "duree_max": 150,          # secondes
        "versions": 1,             # nombre de chansons générées pour choisir
        "epoques_voix": 150,       # entraînement de la voix du client
        "clip_formats": ["16:9"],
        "clip_effets": "simple",   # zoom doux + coupes sur le rythme
        "karaoke": False,
        "pochette": False,
        "pistes_separees": False,
        "photos_animees": 0,       # photos animées par l'IA (si la carte graphique le permet)
        "levres": False,           # le visage du client chante (synchro des lèvres)
        "plans_chantes": 0,        # plans où le chanteur chante (lèvres + gestes, IA EchoMimicV3)
        "plans_danse": 0,          # plans où le chanteur danse sur la musique
        "description": "1 chanson (~2 min 30), voix du client, clip calé sur le rythme (1 photo suffit).",
    },
    "Pro": {
        "duree_max": 240,
        "versions": 3,
        "epoques_voix": 300,
        "clip_formats": ["16:9", "9:16"],
        "clip_effets": "dynamique",  # + flashs et zooms sur les temps forts
        "karaoke": False,
        "pochette": True,
        "pistes_separees": False,
        "photos_animees": 4,
        "levres": False,
        "plans_chantes": 6,
        "plans_danse": 2,
        "description": "Chanson complète, 3 versions au choix, voix soignée, clip YouTube + TikTok où le chanteur chante (lèvres et gestes synchronisés) et danse, pochette.",
    },
    "Ultra": {
        "duree_max": 300,
        "versions": 4,
        "epoques_voix": 500,
        "clip_formats": ["16:9", "9:16", "1:1"],
        "clip_effets": "dynamique",
        "karaoke": True,
        "pochette": True,
        "pistes_separees": True,
        "photos_animees": 8,
        "levres": True,
        "plans_chantes": 12,
        "plans_danse": 5,
        "description": "Chanson complète, 4 versions, vrai clip : le chanteur chante (lèvres, gestes) et danse sur de nombreux plans, karaoké, tous formats, pochette, pistes séparées.",
    },
}

MENTION_IA = "Créé avec l'intelligence artificielle - " + NOM_STUDIO
