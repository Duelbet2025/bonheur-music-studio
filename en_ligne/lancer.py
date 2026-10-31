"""Lance le studio hors Kaggle (Lightning AI, ou toute machine Linux avec carte NVIDIA).

Usage (une seule ligne, à coller dans le terminal) :
  curl -sL https://raw.githubusercontent.com/Duelbet2025/bonheur-music-studio/main/en_ligne/lancer.py | python3 - CLE CANAL
"""
import io
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

BMS_CLE, BMS_CANAL = sys.argv[1], sys.argv[2]
dest = Path.home() / "bms_code"
shutil.rmtree(dest, ignore_errors=True)
dest.mkdir(parents=True)
with urllib.request.urlopen("https://codeload.github.com/Duelbet2025/bonheur-music-studio/tar.gz/refs/heads/main",
                            timeout=120) as r:
    tarfile.open(fileobj=io.BytesIO(r.read()), mode="r:gz").extractall(dest)
BMS_CODE = str(next(dest.iterdir()))
exec(open(BMS_CODE + "/en_ligne/demarrer_kaggle.py", encoding="utf-8").read())
