#!/usr/bin/env python3
"""
Benchmark modeles LLM - Compare la precision, le temps de traitement et le
taux de JSON invalide de plusieurs modeles sur les clients disposant d'un
vrai PDF source (CLIENT_D, E, F, G, H).

Pour chaque client, les training_json_N.json (qui partagent tous le meme
numCommande) sont fusionnes en un seul JSON attendu, puisque le PDF source
contient plusieurs lignes de produits reparties sur plusieurs fichiers
d'exemples few-shot.

Usage:
    python Administration/benchmark_models.py
    python Administration/benchmark_models.py --models qwen2.5:7b,qwen3-vl:8b
    python Administration/benchmark_models.py --clients D,E
"""

import argparse
import glob
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "Production"))
sys.path.insert(0, str(Path(__file__).parent))

from ocr_smart import SmartExtractor
from ocr_evaluate import JSONComparator

PATTERNS_DIR = Path("patterns")
AGENCES_FILE = Path("Données/refs/agencesPAP.txt")
CLIENTS_FILE = Path("Données/refs/clients.txt")

DEFAULT_CLIENTS = ["D", "E", "F", "G", "H"]
DEFAULT_MODELS = ["qwen2.5:7b", "qwen3-vl:8b"]


def build_expected_json(client_id: str) -> dict:
    """Fusionne tous les training_json_N.json d'un client (meme numCommande,
    lignes de produits reparties sur plusieurs fichiers) en un seul JSON attendu."""
    client_dir = PATTERNS_DIR / f"CLIENT_{client_id}"
    files = sorted(client_dir.glob("training_json_*.json"))
    if not files:
        raise FileNotFoundError(f"Aucun training_json_*.json pour CLIENT_{client_id}")

    entete = None
    produits = []
    for fp in files:
        data = json.loads(fp.read_text(encoding="utf-8"))
        for commande in data.get("commandes", []):
            if entete is None:
                entete = commande["entete"]
            produits.extend(commande["detailCommande"]["produits"])

    return {
        "commandes": [
            {
                "entete": entete,
                "detailCommande": {
                    "produits": produits,
                    "nbLignes": len(produits),
                },
            }
        ]
    }


def find_pdf(client_id: str) -> Path:
    client_dir = PATTERNS_DIR / f"CLIENT_{client_id}"
    matches = sorted(client_dir.glob("BC_*.pdf"))
    if not matches:
        raise FileNotFoundError(f"Aucun PDF source pour CLIENT_{client_id}")
    return matches[0]


def run_one(extractor: SmartExtractor, client_id: str, pdf_path: Path, expected: dict) -> dict:
    start = time.perf_counter()
    try:
        actual, _, _ = extractor.process_bc(pdf_path, client_id_hint=client_id)
        duration = time.perf_counter() - start

        comparator = JSONComparator()
        comparator.compare_dicts(expected, actual)
        precision = comparator.get_precision()

        return {
            "client": client_id,
            "status": "ok",
            "duration_s": round(duration, 1),
            "precision": round(precision, 1),
            "correct_fields": comparator.stats["correct_fields"],
            "total_fields": comparator.stats["total_fields"],
        }
    except json.JSONDecodeError as e:
        duration = time.perf_counter() - start
        return {
            "client": client_id,
            "status": "invalid_json",
            "duration_s": round(duration, 1),
            "error": str(e),
        }
    except Exception as e:
        duration = time.perf_counter() - start
        return {
            "client": client_id,
            "status": "error",
            "duration_s": round(duration, 1),
            "error": str(e),
        }


def summarize(model: str, results: list) -> dict:
    ok = [r for r in results if r["status"] == "ok"]
    invalid_json = [r for r in results if r["status"] == "invalid_json"]
    other_errors = [r for r in results if r["status"] == "error"]

    return {
        "model": model,
        "nb_documents": len(results),
        "nb_success": len(ok),
        "avg_precision": round(sum(r["precision"] for r in ok) / len(ok), 1) if ok else None,
        "avg_duration_s": round(sum(r["duration_s"] for r in results) / len(results), 1) if results else None,
        "invalid_json_rate": round(100 * len(invalid_json) / len(results), 1) if results else None,
        "other_error_rate": round(100 * len(other_errors) / len(results), 1) if results else None,
        "details": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark de modeles LLM sur des clients avec PDF reel")
    parser.add_argument("--clients", type=str, default=",".join(DEFAULT_CLIENTS),
                         help="Liste de clients separes par des virgules (defaut: D,E,F,G,H)")
    parser.add_argument("--models", type=str, default=",".join(DEFAULT_MODELS),
                         help="Liste de modeles separes par des virgules")
    parser.add_argument("--output", type=Path, default=Path("Données/benchmark_results.json"))
    args = parser.parse_args()

    clients = args.clients.split(",")
    models = args.models.split(",")

    print(f"Clients: {clients}")
    print(f"Modeles: {models}\n")

    dataset = {}
    for client_id in clients:
        dataset[client_id] = {
            "pdf": find_pdf(client_id),
            "expected": build_expected_json(client_id),
        }
        nb_produits = len(dataset[client_id]["expected"]["commandes"][0]["detailCommande"]["produits"])
        print(f"CLIENT_{client_id}: {dataset[client_id]['pdf'].name} ({nb_produits} produits attendus)")

    print()

    summaries = []
    for model in models:
        print(f"{'='*60}")
        print(f"MODELE: {model}")
        print(f"{'='*60}")

        extractor = SmartExtractor(
            patterns_dir=PATTERNS_DIR,
            agences_file=AGENCES_FILE,
            clients_file=CLIENTS_FILE,
            model=model,
            debug=False,
        )

        results = []
        for client_id in clients:
            print(f"\n--- CLIENT_{client_id} ---")
            r = run_one(extractor, client_id, dataset[client_id]["pdf"], dataset[client_id]["expected"])
            results.append(r)
            if r["status"] == "ok":
                print(f"  OK - precision {r['precision']}% ({r['correct_fields']}/{r['total_fields']} champs) en {r['duration_s']}s")
            else:
                print(f"  {r['status'].upper()} en {r['duration_s']}s: {r['error']}")

        summary = summarize(model, results)
        summaries.append(summary)
        print(f"\n>>> {model}: precision moy. {summary['avg_precision']}% | "
              f"temps moy. {summary['avg_duration_s']}s | "
              f"JSON invalide {summary['invalid_json_rate']}% | "
              f"autres erreurs {summary['other_error_rate']}%\n")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(summaries, f, indent=2, ensure_ascii=False, default=str)
    print(f"Resultats sauvegardes dans {args.output}")

    print(f"\n{'='*60}")
    print("TABLEAU RECAPITULATIF")
    print(f"{'='*60}")
    print(f"{'Modele':<20}{'Precision moy.':<18}{'Temps moy.':<14}{'JSON invalide':<16}{'Autres erreurs'}")
    for s in summaries:
        print(f"{s['model']:<20}{str(s['avg_precision'])+'%':<18}{str(s['avg_duration_s'])+'s':<14}"
              f"{str(s['invalid_json_rate'])+'%':<16}{str(s['other_error_rate'])+'%'}")

    print(f"\n{'='*60}")
    print("DETAIL PAR CLIENT")
    print(f"{'='*60}")

    col_width = max(22, max(len(s["model"]) for s in summaries) + 6)
    header = f"{'Client':<10}" + "".join(f"{s['model']:<{col_width}}" for s in summaries)
    print(header)

    by_client = {}
    for s in summaries:
        for r in s["details"]:
            by_client.setdefault(r["client"], {})[s["model"]] = r

    for client_id in clients:
        row = f"{client_id:<10}"
        for s in summaries:
            r = by_client.get(client_id, {}).get(s["model"])
            if r is None:
                cell = "-"
            elif r["status"] == "ok":
                cell = f"{r['precision']}% ({r['duration_s']}s)"
            else:
                cell = f"{r['status'].upper()} ({r['duration_s']}s)"
            row += f"{cell:<{col_width}}"
        print(row)


if __name__ == "__main__":
    main()
