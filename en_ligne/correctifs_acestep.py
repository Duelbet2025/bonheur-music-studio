"""Correctif ACE-Step pour les cartes d'avant 2020 (T4 de Kaggle).

ACE-Step 1.5 passe ces cartes en float16, ce qui donne un son vide (« NaN latents »). Son message
conseille ACESTEP_DTYPE=float32, mais cette variable n'est pas lue pour les cartes NVIDIA : on
l'ajoute ici. Usage : python correctifs_acestep.py <dossier ACE-Step-1.5>   (sans effet si déjà fait)
"""
import sys
from pathlib import Path

LIRE = "__import__('os').environ.get('ACESTEP_DTYPE', '').lower() == 'float32'"
CORRECTIFS = {
    "acestep/core/generation/handler/init_service_orchestrator.py": [
        ("                    self.dtype = torch.float16\n",
         f"                    self.dtype = torch.float32 if {LIRE} else torch.float16  # BMS\n"),
    ],
    "acestep/core/generation/handler/memory_utils.py": [
        ("                return torch.bfloat16\n            return torch.float16\n",
         f"                return torch.bfloat16\n            return torch.float32 if {LIRE} else torch.float16  # BMS\n"),
    ],
}


def appliquer(dossier):
    dossier = Path(dossier)
    for fichier, remplacements in CORRECTIFS.items():
        f = dossier / fichier
        if not f.exists():
            print("correctif : fichier absent", fichier)
            continue
        texte = f.read_text(encoding="utf-8")
        for ancien, nouveau in remplacements:
            if nouveau in texte:
                continue
            if ancien in texte:
                texte = texte.replace(ancien, nouveau, 1)
                print("correctif appliqué :", fichier)
            else:
                print("correctif : motif introuvable dans", fichier)
        f.write_text(texte, encoding="utf-8")


if __name__ == "__main__":
    appliquer(sys.argv[1])
