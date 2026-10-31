"""Mixage, mastering et exports (WAV, MP3, instrumental, extrait de démonstration)."""
from pathlib import Path

from config import MENTION_IA
from outils import duree_audio, lancer_ffmpeg

# Chaîne de traitement de la voix : nettoyage des graves, présence, compression, légère réverbération.
CHAINE_VOIX = (
    "aresample=44100,aformat=channel_layouts=stereo,highpass=f=90,"
    "equalizer=f=250:t=q:w=1:g=-2,equalizer=f=3200:t=q:w=1.2:g=2.5,equalizer=f=10000:t=h:w=0.7:g=1.5,"
    "acompressor=threshold=-20dB:ratio=3:attack=5:release=90:makeup=2,"
    "aecho=0.8:0.5:45|90:0.18|0.10"
)
# Mastering : compression douce puis volume standard des plateformes (-14 LUFS).
CHAINE_MASTER = (
    "acompressor=threshold=-14dB:ratio=2:attack=20:release=200:makeup=1,"
    "loudnorm=I=-14:TP=-1.0:LRA=11,alimiter=limit=0.95,aresample=44100,aformat=channel_layouts=stereo"
)


def mixer(voix: Path, accompagnements, sortie_wav: Path, niveau_voix_db=1.0):
    """Mélange la voix du client avec la musique, puis masterise."""
    accompagnements = [Path(a) for a in accompagnements]
    entrees = ["-i", voix]
    for a in accompagnements:
        entrees += ["-i", a]
    n = len(accompagnements)
    musique = "".join(f"[{i + 1}:a]aresample=44100,aformat=channel_layouts=stereo[m{i}];" for i in range(n))
    if n > 1:
        musique += "".join(f"[m{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0[mus];"
    else:
        musique += "[m0]anull[mus];"
    filtre = (
        f"[0:a]{CHAINE_VOIX},volume={niveau_voix_db}dB[v];{musique}"
        f"[v][mus]amix=inputs=2:normalize=0:duration=longest,{CHAINE_MASTER}[out]"
    )
    lancer_ffmpeg([*entrees, "-filter_complex", filtre, "-map", "[out]",
                   "-c:a", "pcm_s24le", sortie_wav], "Mixage")
    return sortie_wav


def additionner(pistes, sortie_wav: Path):
    """Additionne des pistes instrumentales (sans traitement de voix) puis masterise."""
    pistes = [Path(p) for p in pistes]
    entrees = [x for p in pistes for x in ("-i", p)]
    n = len(pistes)
    filtre = "".join(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo[m{i}];" for i in range(n))
    filtre += "".join(f"[m{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0,{CHAINE_MASTER}[out]"
    lancer_ffmpeg([*entrees, "-filter_complex", filtre, "-map", "[out]", "-c:a", "pcm_s24le", sortie_wav],
                  "Mixage instrumental")
    return sortie_wav


def masteriser(source: Path, sortie_wav: Path):
    """Masterise une piste seule (ex. l'instrumental)."""
    lancer_ffmpeg(["-i", source, "-af", CHAINE_MASTER, "-c:a", "pcm_s24le", sortie_wav], "Mastering")
    return sortie_wav


def exporter_mp3(source_wav: Path, sortie_mp3: Path, titre="", artiste=""):
    lancer_ffmpeg(["-i", source_wav, "-c:a", "libmp3lame", "-b:a", "320k",
                   "-metadata", f"title={titre}", "-metadata", f"artist={artiste}",
                   "-metadata", f"comment={MENTION_IA}", sortie_mp3], "Export MP3")
    return sortie_mp3


def extrait_demo(source_wav: Path, sortie_mp3: Path, longueur=30):
    """Extrait de 30 s avec un petit « bip » toutes les 7 s : à envoyer au client avant paiement."""
    duree = duree_audio(source_wav)
    debut = max(0.0, min(duree * 0.3, duree - longueur))
    filtre = (
        f"[0:a]atrim=start={debut:.2f}:duration={longueur},asetpts=PTS-STARTPTS,"
        f"afade=t=in:d=1,afade=t=out:st={longueur - 2}:d=2[a];"
        f"aevalsrc='0.12*sin(2*PI*880*t)*lt(mod(t\\,7)\\,0.25)':s=44100:d={longueur}[bip];"
        f"[a][bip]amix=inputs=2:normalize=0[out]"
    )
    lancer_ffmpeg(["-i", source_wav, "-filter_complex", filtre, "-map", "[out]",
                   "-c:a", "libmp3lame", "-b:a", "128k",
                   "-metadata", "comment=EXTRAIT - " + MENTION_IA, sortie_mp3], "Extrait démo")
    return sortie_mp3
