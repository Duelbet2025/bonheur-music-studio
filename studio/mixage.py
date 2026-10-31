"""Mixage, mastering et exports (WAV, MP3, instrumental, extrait de démonstration)."""
from pathlib import Path

from config import MENTION_IA
from outils import duree_audio, lancer_ffmpeg

# Chaîne de traitement de la voix (comme en studio) : nettoyage des graves, enlever le « carton »,
# présence et brillance, de-esser, compression en deux temps, petite réverbération.
CHAINE_VOIX = (
    "aresample=44100,aformat=channel_layouts=stereo,highpass=f=100,"
    "equalizer=f=300:t=q:w=1.2:g=-3,equalizer=f=3000:t=q:w=1.0:g=3,equalizer=f=12000:t=h:w=0.7:g=2,"
    "deesser=i=0.4,"
    "acompressor=threshold=-24dB:ratio=4:attack=3:release=80:makeup=4,"
    "acompressor=threshold=-12dB:ratio=2:attack=10:release=150:makeup=1,"
    "aecho=0.8:0.6:60|120:0.12|0.07"
)
# Mastering : compression douce puis volume standard des plateformes (-14 LUFS).
CHAINE_MASTER = (
    "acompressor=threshold=-14dB:ratio=2:attack=20:release=200:makeup=1,"
    "loudnorm=I=-14:TP=-1.0:LRA=11,alimiter=limit=0.95,aresample=44100,aformat=channel_layouts=stereo"
)
VOIX_AU_DESSUS_DB = 2.0  # voix 2 dB plus forte que la musique (style afro/pop : la voix devant)


def volume_lufs(fichier: Path) -> float:
    """Volume perçu (LUFS intégré) d'un fichier, mesuré par FFmpeg."""
    import json
    import re
    import subprocess
    from outils import ffmpeg
    r = subprocess.run([ffmpeg(), "-hide_banner", "-nostats", "-i", str(fichier), "-af",
                        "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr)
    try:
        valeur = float(json.loads(m.group(0))["input_i"])
        return valeur if valeur > -70 else -70.0
    except Exception:
        return -23.0


def mixer(voix: Path, accompagnements, sortie_wav: Path, voix_au_dessus_db=VOIX_AU_DESSUS_DB):
    """Mélange voix + musique comme un ingénieur du son.

    1. la voix est traitée (EQ, de-esser, compression), la musique est additionnée ;
    2. on MESURE leur volume perçu et on règle la voix pour qu'elle passe 2 dB au-dessus de la musique ;
    3. la musique se baisse un peu quand la voix chante (« ducking ») pour que chaque mot s'entende ;
    4. mastering à -14 LUFS.
    """
    accompagnements = [Path(a) for a in accompagnements]
    dossier = Path(sortie_wav).parent
    voix_traitee = dossier / f"_{Path(sortie_wav).stem}_voix.wav"
    musique_seule = dossier / f"_{Path(sortie_wav).stem}_musique.wav"
    lancer_ffmpeg(["-i", voix, "-af", CHAINE_VOIX, "-c:a", "pcm_s24le", voix_traitee], "Traitement de la voix")
    entrees = [x for a in accompagnements for x in ("-i", a)]
    n = len(accompagnements)
    filtre = "".join(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo[m{i}];" for i in range(n))
    filtre += ("".join(f"[m{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0[out]") if n > 1 \
        else "[m0]anull[out]"
    lancer_ffmpeg([*entrees, "-filter_complex", filtre, "-map", "[out]", "-c:a", "pcm_s24le", musique_seule],
                  "Somme de la musique")
    gain = (volume_lufs(musique_seule) + voix_au_dessus_db) - volume_lufs(voix_traitee)
    gain = max(-12.0, min(18.0, gain))
    filtre = (
        f"[0:a]volume={gain:.2f}dB,asplit=2[v][cle];"
        f"[1:a][cle]sidechaincompress=threshold=0.06:ratio=2.5:attack=15:release=300:makeup=1[mus];"
        f"[v][mus]amix=inputs=2:normalize=0:duration=longest,{CHAINE_MASTER}[out]"
    )
    lancer_ffmpeg(["-i", voix_traitee, "-i", musique_seule, "-filter_complex", filtre, "-map", "[out]",
                   "-c:a", "pcm_s24le", sortie_wav], "Mixage")
    for f in (voix_traitee, musique_seule):
        f.unlink(missing_ok=True)
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
