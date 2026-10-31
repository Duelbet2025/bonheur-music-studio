# Bonheur Music Studio

Studio privé de chansons et de clips par intelligence artificielle, construit uniquement avec des outils libres et gratuits.

- **Composition** : ACE-Step 1.5 (MIT) — styles (coupé-décalé, zouk, reggae…), tempo, ambiance, instruments, paroles.
- **Voix du client** : Applio / RVC (MIT) — l'IA apprend la voix du client et l'applique à la chanson.
- **Séparation et mixage** : Demucs (MIT), FFmpeg, normalisation -14 LUFS.
- **Clip** : montage calé sur le rythme, karaoké (faster-whisper), et plans où le chanteur **chante (lèvres + gestes) et danse**
  grâce à EchoMimicV3-Flash (Apache 2.0).
- **Formules** Standard / Pro / Ultra.

Deux façons de l'utiliser :
- **En ligne** (sans carte graphique) : `en_ligne/demarrer_kaggle.py`, lancé depuis un notebook Kaggle privé (GPU T4 gratuit).
- **Sur PC Windows avec carte NVIDIA** : `DEMARRER.bat`.

Aucune donnée client ni clé n'est stockée dans ce dépôt.
