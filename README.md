# OCR Pipeline PRO A PRO

## Objectif

Ce projet a pour but d'extraire automatiquement des données structurées (au format JSON métier) à partir de bons de commande PDF, en appliquant des règles métier strictes et en utilisant l'OCR, LLaVA (via Ollama) et des scripts Python robustes. L'objectif est d'obtenir des fichiers JSON exploitables pour l'intégration EDI, avec une validation forte et une visualisation claire des résultats.

## Fonctionnement général

- **ocr.py** :
  - Pipeline principal.
  - Prend en entrée un ou plusieurs PDF de bons de commande.
  - Applique l'OCR si besoin, extrait le texte, interroge LLaVA pour générer un JSON structuré.
  - Valide et corrige les données extraites selon les règles métier (dates, clients, agences, produits, etc.).
  - Génère un ou plusieurs fichiers JSON (un par commande détectée dans le PDF).
  - Affiche un résumé et les éventuelles erreurs de validation.

- **visualize.py** :
  - Permet d'afficher de façon lisible le contenu d'un ou plusieurs fichiers JSON générés.
  - Affiche les entêtes, les produits, et fait des vérifications/fuzzy-matching sur les agences/clients.

## Utilisation

### Extraction

```sh
python ocr.py \
  --input ./BC/Bon_de_commande_simple_35303_INFLIGHT.pdf \
  --out-dir resultats/ \
  --agences-file refs/agencesPAP.txt \
  --clients-file refs/clients.txt
```

Les fichiers JSON générés sont placés dans `resultats/` et nommés selon le schéma :
- `commande_<numCommande>.json` (ex : `commande_01142-32721-1.json`)

### Visualisation

```sh
python visualize.py --input resultats/commande_01142-32721-1.json
```

## État actuel & problèmes rencontrés

- Le pipeline fonctionne et génère des JSON métier à partir des PDF.
- La validation métier est stricte (dates, clients, agences, produits, etc.).
- Le visualizer permet d'inspecter les JSON générés.

**Problèmes actuels :**

1. **Génération incomplète des commandes :**
   - Pour certains PDF multi-commandes, seul le deuxième JSON est généré, alors que le PDF contient plusieurs commandes (ex : 2 attendues, 1 générée).
   - Le détail des produits dans la deuxième commande est incomplet (4 produits extraits au lieu de 9 attendus).

2. **Nommage des fichiers JSON :**
   - Le nommage n'est pas strictement conforme au format attendu (`commande_01142-32721-2.json`), parfois un underscore remplace le tiret.

3. **Extraction des produits (visualizer) :**
   - Pour la première commande, le visualizer affiche un produit générique ("Produit 1") avec un code article et une quantité par défaut, au lieu des vraies valeurs extraites du PDF.
   - Les champs code article, quantité et libellé ne sont pas correctement extraits ou transmis dans le JSON.

4. **Validation stricte :**
   - Si la validation échoue (dates manquantes, structure incorrecte), aucun JSON n'est généré, ce qui complique le debug.

## Prochaines étapes recommandées

- Corriger la logique de regroupement et d'extraction des produits pour chaque commande (s'assurer que tous les produits sont extraits et associés à la bonne date de livraison).
- Uniformiser le nommage des fichiers JSON générés (`commande_<numCommande>.json` avec des tirets).
- Améliorer la robustesse de l'extraction des champs produits (codeArticle, libelle, quantite) pour éviter les valeurs par défaut.
- (Optionnel) Permettre la génération du JSON même en cas d'erreur de validation, pour faciliter le debug.

## Exemples attendus

Voir les fichiers `exemple1.json` et `exemple2.json` pour le format et le contenu attendus (structure, nombre de produits, valeurs extraites).

---

Pour toute anomalie, vérifier la sortie console de `ocr.py` (erreurs de validation, debug LLaVA) et comparer les JSON générés avec les exemples fournis.