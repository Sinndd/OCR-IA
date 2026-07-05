# 🚀 Commandes Training OCR

## 📍 Navigation
```bash
cd "/Users/nathan/Library/Mobile Documents/com~apple~CloudDocs/PRO A PRO/OCR/training"
source "/Users/nathan/Library/Mobile Documents/com~apple~CloudDocs/PRO A PRO/.venv/bin/activate"
```

---

## 🔍 Système RAG (Retrieval-Augmented Generation)

### Indexer les exemples
```bash
python rag_system.py --index
```
**Rôle :** Indexe tous vos exemples de training dans une base vectorielle FAISS. À faire une fois, puis à chaque ajout de nouveaux exemples.

### Extraire avec RAG
```bash
python rag_system.py --extract ../Données/BC/fichier.pdf
python rag_system.py --extract ../Données/BC/fichier.html
```
**Rôle :** Extrait les données d'un document en utilisant les exemples similaires comme contexte pour le LLM.

### Voir les statistiques
```bash
python rag_system.py --stats
```
**Rôle :** Affiche le nombre de documents indexés dans la base vectorielle.

---

## 🔄 Pipeline OCR Complet

### Mode fichier unique (interactif)
```bash
python pipeline_ocr.py --file ../Données/BC/fichier.pdf
```
**Rôle :** Traite un document avec OCR → RAG → LLM → JSON. Demande confirmation avant sauvegarde.

### Mode batch (automatique)
```bash
python pipeline_ocr.py --batch ../Données/BC/ --auto-save
```
**Rôle :** Traite tous les documents d'un dossier automatiquement et sauvegarde les résultats.

### Mode sans RAG
```bash
python pipeline_ocr.py --file ../Données/BC/fichier.pdf --no-rag
```
**Rôle :** Utilise uniquement le LLM sans recherche d'exemples similaires.

### Mode debug
```bash
python pipeline_ocr.py --file ../Données/BC/fichier.pdf --debug
```
**Rôle :** Affiche tous les détails du traitement (prompts, réponses LLM, etc.).

---

## 🎯 Fine-tuning (Optionnel)

### Préparer les données d'entraînement
```bash
python finetune_llm.py --prepare
```
**Rôle :** Collecte toutes les paires (texte BC, JSON) depuis vos patterns et crée un fichier JSONL pour l'entraînement.

### Lancer le fine-tuning
```bash
python finetune_llm.py --train --epochs 3
```
**Rôle :** Fine-tune le modèle Qwen2.5-7B sur vos données (nécessite GPU et ~15GB de téléchargement).

### Tester le modèle fine-tuné
```bash
python finetune_llm.py --test
```
**Rôle :** Teste le modèle fine-tuné sur des exemples et compare avec le modèle de base.

---

## 🔧 Vérifications

### Vérifier qu'Ollama fonctionne
```bash
curl http://localhost:11434/api/generate -d '{
  "model": "qwen2.5:7b",
  "prompt": "Test",
  "stream": false
}'
```

### Voir les modèles Ollama installés
```bash
ollama list
```

### Lancer Ollama
```bash
ollama serve
```

---

## 📊 Workflow Recommandé

1. **Indexer les exemples** (à faire une fois)
   ```bash
   python rag_system.py --index
   ```

2. **Tester sur un document**
   ```bash
   python rag_system.py --extract ../Données/BC/fichier.pdf
   ```

3. **Utiliser le pipeline complet** (pour production)
   ```bash
   python pipeline_ocr.py --batch ../Données/BC/ --auto-save
   ```

4. **Fine-tuning** (optionnel, pour optimiser)
   ```bash
   python finetune_llm.py --prepare
   python finetune_llm.py --train
   ```
