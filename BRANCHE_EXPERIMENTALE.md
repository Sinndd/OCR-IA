# 🧪 Branche Expérimentale : Multi-Exemples Intelligents

## 📋 Résumé des Améliorations

Cette branche (`feature/multi-examples-smart-extraction`) implémente des améliorations majeures pour l'extraction OCR :

### 1. **Tri Intelligent des Exemples** 🎯
- **Avant** : Un seul exemple utilisé (le premier trouvé)
- **Après** : Les 5 exemples les plus similaires au BC à traiter

**Comment ça marche ?**
- Analyse des caractéristiques du BC (format date, structure, mots-clés)
- Calcul d'un score de similarité pour chaque exemple disponible
- Sélection des exemples les plus pertinents

### 2. **Détection de Similarité Multi-Critères** 🔍
Critères analysés :
- Format de date (dd/mm/yyyy, yyyy-mm-dd, etc.)
- Présence de tableaux structurés
- Mots-clés fréquents dans le texte
- Densité numérique
- Structure (entête, footer)

**Score de similarité** : 0 à 1 (1 = très similaire)

### 3. **Cache de Patterns Généralisés** ⚡
- **Avant** : Patterns recalculés à chaque fois
- **Après** : Patterns mis en cache (`patterns_cache.json`)

**Contenu du cache** :
- Champs communs à tous les exemples
- Champs optionnels
- Types de données attendus
- Contraintes de validation

### 4. **Prompts Plus Flexibles** 🎨
- **Avant** : Prompts très spécifiques à un seul format
- **Après** : Prompts génériques qui s'adaptent à plusieurs formats

**Avantages** :
- Supporte les futurs formats sans modification
- Le LLM comprend mieux les variations
- Meilleure généralisation

## 🚀 Comment Tester

### Vérifier la branche actuelle
```bash
git branch
# Vous devriez voir : * feature/multi-examples-smart-extraction
```

### Tester avec un BC
```bash
cd "/Users/nathan/Library/Mobile Documents/com~apple~CloudDocs/PRO A PRO/OCR"
source venv/bin/activate

# Test avec debug pour voir les scores de similarité
python Production/ocr_smart.py \
  --input "Données/BC/Bon_de_commande_anonymisé.pdf" \
  --out-dir resultats/ \
  --agences-file Données/refs/agencesPAP.txt \
  --clients-file Données/refs/clients.txt \
  --debug
```

### Ce que vous verrez en mode debug

```
🔍 Analyse de similarité (2 exemples disponibles)...
  📊 API-01142-32721: similarité = 0.856
  📊 API-02323-1631: similarité = 0.742
  ✓ 2 exemples sélectionnés (les plus similaires)

  🔨 Construction du pattern généralisé...
  ✓ Pattern construit: 15 champs communs

[DEBUG] Prompt LLM optimisé
  - 2 exemples sélectionnés (sur 2 disponibles)
  - Pattern généralisé: OUI
  - Taille prompt: 12450 chars
  - Modèle: qwen2.5:7b
```

## 📊 Comparaison Avant/Après

| Aspect | Version Actuelle (master) | Version Optimisée (branche) |
|--------|---------------------------|----------------------------|
| Exemples utilisés | 1 seul | 5 plus similaires |
| Prompts | Spécifiques à un format | Génériques et flexibles |
| Cache | Aucun | Patterns généralisés |
| Similarité | Non calculée | Score multi-critères |
| Adaptabilité | Faible | Élevée |

## 🔄 Revenir à la Version Précédente

Si les résultats ne sont pas satisfaisants :

```bash
# Retour à la version stable
git checkout master

# Les fichiers reviennent à l'état d'origine
```

## 🔬 Tests Recommandés

### 1. Test avec un client connu (API)
```bash
python Production/ocr_smart.py \
  --input examples/API/exemple_1_multi/Bon_de_commande_anonymisé.pdf \
  --client-id API \
  --out-dir resultats/test_api/ \
  --debug
```

### 2. Test avec un client connu (NEWREST)
```bash
python Production/ocr_smart.py \
  --input "examples/NEWREST/exemple_1_single/Bon de commande simple_1439275 CS0028.pdf" \
  --client-id NEWREST \
  --out-dir resultats/test_newrest/ \
  --debug
```

### 3. Test avec détection automatique
```bash
python Production/ocr_smart.py \
  --input "Données/BC/Bon_de_commande_anonymisé.pdf" \
  --out-dir resultats/test_auto/ \
  --debug
```

## 📈 Métriques à Observer

1. **Score de similarité** : Les exemples sélectionnés ont-ils des scores > 0.5 ?
2. **Qualité d'extraction** : Tous les produits sont-ils extraits ?
3. **Temps d'exécution** : Pas de ralentissement significatif ?
4. **Taille du cache** : `patterns/patterns_cache.json` se crée-t-il ?

## 🐛 En Cas de Problème

### Le cache pose problème
```bash
# Supprimer le cache
rm patterns/patterns_cache.json

# Relancer le test
```

### Les scores de similarité sont trop bas
- C'est normal si les BCs sont très différents
- Le système utilisera quand même les meilleurs disponibles
- Minimum 1 exemple est toujours utilisé

### Erreur d'importation
```bash
# Vérifier les dépendances
pip install hashlib  # Normalement inclus dans Python
```

## 💡 Prochaines Étapes

Si cette version fonctionne bien :
1. ✅ Valider les résultats sur plusieurs BCs
2. ✅ Comparer avec les anciens résultats
3. ✅ Merger dans master si satisfaisant

Si vous souhaitez des ajustements :
- Modifier le nombre d'exemples max (actuellement 5)
- Ajuster les poids des critères de similarité
- Enrichir les patterns généralisés

## 🔗 Branches Git

```bash
# Voir toutes les branches
git branch -a

# master : Version stable actuelle
# feature/multi-examples-smart-extraction : Cette version expérimentale
```

---

**Date de création** : 6 novembre 2025  
**Auteur** : Nathan (avec assistance IA)  
**Objectif** : Améliorer la qualité d'extraction en utilisant plusieurs exemples similaires
