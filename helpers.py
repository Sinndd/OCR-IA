# Petites fonctions utilitaires réutilisées par plusieurs routes.
#
# Regroupées ici pour éviter que la même logique (vérifier une extension de
# fichier, retrouver le client à partir de son "origine", lancer un script
# Python en sous-processus...) soit recopiée dans chaque route.
import json
import subprocess
import sys
from pathlib import Path

from extensions import METRICS_FILE, PATTERNS_DIR


# Charge les métriques depuis le fichier JSON
def load_metrics():
    if METRICS_FILE.exists():
        try:
            with open(METRICS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "extractions": [],
        "clients": {},
        "global_stats": {
            "total_extractions": 0,
            "total_products": 0,
            "total_validated": 0,
            "total_corrected": 0
        }
    }


# Sauvegarde les métriques dans le fichier JSON
def save_metrics(metrics):
    try:
        METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(METRICS_FILE, 'w', encoding='utf-8') as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️  Erreur sauvegarde métriques: {e}")


# Vrai si l'extension du fichier fait partie des extensions acceptées.
def is_allowed_file(filename: str, allowed_extensions) -> bool:
    return Path(filename).suffix.lower() in allowed_extensions


# Lance un script Python du projet (ocr_train.py, ocr_evaluate.py, ocr_smart.py...)
# dans un sous-processus, et renvoie le résultat (stdout/stderr/returncode).
def run_script(script_path: str, *args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, script_path, *args]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=Path.cwd())


# Parcourt patterns/CLIENT_* et donne (dossier_client, metadata) pour
# chaque client dont metadata.json existe et se charge correctement.
def iter_trained_clients():
    if not PATTERNS_DIR.exists():
        return
    for client_dir in PATTERNS_DIR.glob("CLIENT_*"):
        metadata_file = client_dir / "metadata.json"
        if not metadata_file.exists():
            continue
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                yield client_dir, json.load(f)
        except Exception:
            continue


# Retrouve l'ID du client (ex: "D") dont metadata.json liste `client_origin`
# dans ses "entreprises". Si aucun client existant ne correspond, génère un
# identifiant à partir du nom (espaces -> "_", majuscules, 20 caractères max).
def find_client_id_by_origine(client_origin: str) -> str:
    for client_dir, metadata in iter_trained_clients():
        if client_origin in metadata.get('entreprises', []):
            return client_dir.name.replace("CLIENT_", "")
    return client_origin.replace(' ', '_').upper()[:20]


# Sauvegarde `data` comme nouvel exemple d'entraînement pour `client_id`
# dans patterns/CLIENT_<id>/training_json_<n>.json, et renvoie le chemin créé.
def save_training_example(client_id: str, data: dict) -> Path:
    client_dir = PATTERNS_DIR / f"CLIENT_{client_id}"
    client_dir.mkdir(parents=True, exist_ok=True)

    next_n = len(list(client_dir.glob("training_json_*.json"))) + 1
    json_file = client_dir / f"training_json_{next_n}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return json_file


# Supprime le cache de patterns (regénéré automatiquement au besoin).
def invalidate_patterns_cache():
    cache_file = PATTERNS_DIR / "patterns_cache.json"
    if cache_file.exists():
        cache_file.unlink()
