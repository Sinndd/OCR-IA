# 🚀 Training & RAG System

Ce dossier contient les outils pour fine-tuner le LLM et mettre en place le système RAG.

## 📦 Installation

```bash
cd OCR/training
pip install -r requirements.txt
```

## 🎯 Scripts disponibles

### 1. Fine-tuning LLM (`finetune_llm.py`)

Réentraîne un modèle LLM sur tes exemples de bons de commande.

```bash
# Étape 1: Préparer les données
python finetune_llm.py --prepare

# Étape 2: Lancer le fine-tuning (GPU recommandé)
python finetune_llm.py --train --epochs 3

# Étape 3: Tester le modèle
python finetune_llm.py --test
```

**Prérequis:**
- GPU avec au moins 8GB VRAM (pour QLoRA 4-bit)
- Ou CPU avec beaucoup de RAM (très lent)

### 2. Système RAG (`rag_system.py`)

Base de connaissances pour adaptation dynamique sans fine-tuning.

```bash
# Indexer tous les exemples
python rag_system.py --index

# Voir les statistiques
python rag_system.py --stats

# Rechercher des exemples similaires
python rag_system.py --query "texte du BC..."

# Extraction avec RAG
python rag_system.py --extract fichier.txt
```

### 3. Pipeline Complet (`pipeline_ocr.py`)

Workflow unifié: OCR → RAG → LLM → JSON → Feedback → Apprentissage.

```bash
# Traiter un fichier
python pipeline_ocr.py --file document.pdf

# Traitement batch
python pipeline_ocr.py --batch dossier_bcs/

# Mode interactif (validation + correction)
python pipeline_ocr.py --interactive

# Sans RAG
python pipeline_ocr.py --file doc.pdf --no-rag
```

## 📂 Structure

```
training/
├── finetune_llm.py      # Fine-tuning LLM
├── rag_system.py        # Système RAG
├── pipeline_ocr.py      # Pipeline complet
├── requirements.txt     # Dépendances
├── README.md            # Ce fichier
├── data/                # Données d'entraînement générées
│   └── training_data.jsonl
├── finetuned_model/     # Modèle fine-tuné
│   ├── lora_adapter/
│   ├── tokenizer/
│   └── metadata.json
└── rag/                 # Base RAG
    └── vectordb/        # Embeddings ChromaDB
```

## 🔄 Workflow recommandé

### Phase 1: Collecter des exemples
1. Traite des BCs avec l'interface web
2. Corrige les erreurs → les corrections sont sauvegardées automatiquement

### Phase 2: Activer RAG
```bash
python rag_system.py --index
```
→ Le LLM s'appuiera sur les exemples similaires pour mieux extraire

### Phase 3: Fine-tuning (optionnel, pour aller plus loin)
```bash
python finetune_llm.py --prepare
python finetune_llm.py --train
```
→ Le modèle est spécialisé sur tes données

## 📊 Comparaison des approches

| Approche | Avantages | Inconvénients |
|----------|-----------|---------------|
| **Prompt seul** | Simple, rapide | Peu adaptatif |
| **RAG** | Adaptatif, pas de GPU | Dépend de la qualité des exemples |
| **Fine-tuning** | Très performant | GPU requis, plus complexe |
| **RAG + Fine-tuning** | Le meilleur des deux | Plus de setup |

## 💡 Conseils

1. **Commence par RAG** - C'est le plus simple et déjà très efficace
2. **Ajoute des exemples variés** - Plus il y a de diversité, mieux le RAG fonctionne
3. **Fine-tune quand tu as 50+ exemples** - Avant, RAG suffit généralement
4. **Utilise le mode interactif** - Pour valider et enrichir ta base rapidement
