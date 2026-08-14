# OCR Pipeline PRO A PRO

## Objectif

Ce projet extrait automatiquement des données structurées (JSON métier) à partir de bons de commande (PDF, HTML, TXT), en combinant extraction de texte, détection du client, un LLM local (via Ollama) piloté par des exemples spécifiques à chaque client, et des règles métier de validation/correction. L'objectif est de produire des JSON exploitables pour l'intégration EDI.

Le système s'utilise soit via une application web (upload, suivi des jobs, entraînement, statistiques), soit via des scripts CLI, soit via une API REST (intégration n8n / email entrant).

## Architecture actuelle

### Application web (`app.py`)

Application Flask + Flask-SocketIO (port 5001, `python app.py`). Pages principales :
- `/` : upload de bons de commande
- `/results` : résultats de la dernière extraction
- `/training` : entraînement (finetune / pipeline / RAG)
- `/stats` : statistiques d'extraction (`Données/metrics.json`)
- `/monitoring` : suivi temps réel des jobs (WebSocket)
- `/failed-jobs` : gestion des jobs en échec

API REST (utilisée notamment par le workflow n8n, voir `Documentation/GUIDE_N8N_EMAIL.md`) :
- `POST /api/extract` : soumet un fichier, traitement asynchrone via file de jobs
- `GET /api/status/<job_id>` (alias `/api/result/<job_id>`) : statut / résultat d'un job
- `GET /api/jobs`, `POST /api/retry/<job_id>`

La route `/validate` permet de valider ou corriger une extraction depuis l'UI ; une correction est réinjectée comme nouvel exemple d'apprentissage dans `patterns/CLIENT_<id>/`, ce qui améliore les extractions suivantes pour ce client.


### File de traitement (`job_manager.py`, `job_processor.py`)

- `job_manager.py` : persistance SQLite (`jobs.db`) des jobs et de leurs logs (statuts `PENDING`/`PROCESSING`/`COMPLETED`/`FAILED`, étapes détaillées).
- `job_processor.py` : worker en mémoire (thread + `queue.Queue`, pas de dépendance externe type Celery/Redis) qui exécute le pipeline d'extraction pour chaque job soumis et notifie l'UI via WebSocket.

L'upload synchrone depuis `/` (subprocess CLI) et l'API asynchrone `/api/extract` (import direct) sont deux chemins distincts qui appellent tous les deux le même moteur d'extraction.

### Moteur d'extraction (`Production/ocr_smart.py`)

`SmartExtractor` est le moteur réellement utilisé en production. Pipeline (`process_bc()`) :
1. Extraction du texte (PDF via PyMuPDF, HTML, TXT)
2. Détection du client par score de mots-clés/origine sur `patterns/CLIENT_*/metadata.json`
3. Appel au LLM (Ollama, modèle par défaut `qwen2.5:7b`) avec un prompt système contenant les règles métier fixes et jusqu'à 8 exemples du client les plus similaires au document courant
4. Nettoyage, normalisation et validation/réparation du JSON produit (structure, codes articles, dates)

CLI :
```sh
python Production/ocr_smart.py --input Données/BC/mon_bc.pdf --out-dir Données/resultats/
python Production/ocr_smart.py --input Données/BC/mon_bc.pdf --client-id NEWREST --model qwen2.5:7b --debug
```

`visualize.py` affiche de façon lisible un JSON généré (`python visualize.py --input Données/resultats/xxx.json`).

### Patterns par client (`patterns/`)

Un dossier par client (`CLIENT_A` à `CLIENT_H`) contenant :
- `metadata.json` : mots-clés de détection, formats de dates, conventions de nommage — généré par `Administration/ocr_train.py`, consommé par `SmartExtractor.detect_client()`
- `training_bc_N.txt` / `training_json_N.json` : exemples few-shot (BC + JSON attendu) utilisés par le LLM
- `prompt.md` : prompt spécifique au client, écrit à la main (utilisé par `training/rag_system.py`, pas par `ocr_smart.py`)
- `patterns_cache.json` : cache de patterns généralisés par client, invalidé à chaque correction validée depuis l'UI

### Administration (`Administration/`)

- `ocr_train.py` : crée/étend les patterns d'un client à partir d'exemples (BC + JSON attendu)
  ```sh
  python Administration/ocr_train.py --client-id NEWREST --bc-samples BC/ex1.pdf --expected-json ex1.json
  python Administration/ocr_train.py --client-id NEWREST --add-sample BC/ex2.pdf --add-json ex2.json
  ```
- `ocr_evaluate.py` : compare les JSON générés à des JSON attendus (`examples/<client_id>/exemple_*/`) et calcule une précision par champ
  ```sh
  python Administration/ocr_evaluate.py --client-id API --debug
  ```
- `ocr_manager.py` : gestion des patterns (`--list`, `--client-id X --info`, `--stats`, `--export`/`--import`)

### RAG et entraînement (`training/`)

- `rag_system.py` (FAISS) : système RAG **actuellement branché** sur l'app web (`/training`, `/api/rag/*`)
- `rag_qdrant.py` / `migrate_qdrant.py` / `view_qdrant.py` / `visualize_qdrant_3d.py` : piste alternative basée sur Qdrant, explorée en parallèle mais pas intégrée à l'app
- `finetune_llm.py` : prépare un dataset et fine-tune (QLoRA) `Qwen2.5-7B-Instruct` à partir des exemples clients — outillé mais aucun modèle fine-tuné n'a été produit à ce jour (`training/finetuned_model/` vide)
- `time_predictor.py` : `BayesianTimePredictor`, estime le temps d'extraction d'un document (modèle persisté dans `time_model.pkl`)
- `pipeline_ocr.py` : orchestrateur autonome alternatif (OCR → RAG → LLM → JSON → apprentissage), indépendant du couple `job_processor.py`/`ocr_smart.py`

### Données (`Données/`)

- `BC/` : bons de commande d'exemple (PDF/HTML/TXT)
- `refs/agencesPAP.txt`, `refs/clients.txt` : listes de référence pour le fuzzy matching (agences, clients)
- `resultats/` : JSON générés
- `metrics.json` : historique des extractions (alimente `/stats` et le mécanisme de validation)

### Intégration email (n8n)

`n8n_workflow.json` + `Documentation/GUIDE_N8N_EMAIL.md` décrivent un workflow n8n qui surveille une boîte mail (IMAP), filtre les emails contenant un bon de commande et déclenche `POST /api/extract`.

## Tests

```sh
pytest tests/ -v
```

- `tests/test_job_manager.py` : création/transition de statut/retry des jobs (SQLite temporaire)
- `tests/test_json_comparator.py` : comparaison JSON attendu/obtenu (`JSONComparator`)

CI GitHub Actions (`.github/workflows/ci.yml`) : exécute la suite `pytest` sur push/PR vers `master`/`main`/`feature/**`.

`test_branche.sh` est un smoke-test manuel (hors CI) qui lance une extraction sur un BC d'exemple et vérifie la génération du cache de patterns — utile avant de merger une branche expérimentale.

## Installation

```sh
pip install -r requirements.txt
pip install -r requirements-dev.txt   # pour les tests
```

Nécessite [Ollama](https://ollama.com) avec au moins le modèle `qwen2.5:7b` installé (`ollama pull qwen2.5:7b`).

## État connu / points d'attention

- `training/rag_system.py` (FAISS) et `training/rag_qdrant.py` (Qdrant) coexistent ; seul le premier est branché sur l'app web.
- Le fine-tuning (`training/finetune_llm.py`) est outillé mais non exploité en production.
