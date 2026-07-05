# Prompt spécifique CLIENT_H

## Identification du format
- Client: CLIENT_H
- Format: Réquisition d'achat (Style H)
- Une seule commande par document
- Structure de formulaire avec champs étiquetés et tableau de produits

## Structure du BC

### En-tête
Structure de formulaire avec paires étiquette:valeur:

```
RÉQUISITION D'ACHAT
Date d'impression: [JJ/MM/AAAA HH:MM]
N° Réquisition:          [numCommande]
Date:                    [JJ/MM/AAAA]
Date livraison:          [JJ/MM/AAAA]
Demandeur:               [codeEtablissement]
Fournisseur suggéré:     [codeFournisseur]
Code postal:             [codePostal]
Mode livraison:          [modeTransport]
Type commande:           [typeCommande]
Incoterm:                [incoterm]
Devise:                  [devise]
Priorité:                [priorité]
Validation requise:
[ ] Chef de service
[ ] Achats
[ ] Direction
Observations: [commentaires multilignes]
```

**Éléments à extraire:**
- **numCommande**: après `N° Réquisition:`
- **dateCommande**: après `Date:` (première occurrence)
- **dateLivraison**: après `Date livraison:`
- **codeEtablissement**: après `Demandeur:`
- **codeFournisseur**: après `Fournisseur suggéré:`
- **codePostal**: après `Code postal:`
- **modeTransport**: après `Mode livraison:`
- **typeCommande**: après `Type commande:`
- **commentaireEntete**: Texte après `Observations:` (peut être multiligne)

### Section produits
Débute après `Articles demandés:`

**En-tête du tableau:**
```
Ligne  Référence  Libellé  Quantité  Unité  Date livr.
```

**Format produit (une ligne):**
```
[numLigne]  [référence]  [libellé]  [quantité]  [unité]  [date]
```

**IMPORTANT:**
- **Ligne**: Numéro de ligne
- **Référence**: Code article
- **Libellé**: Description du produit
- **Quantité**: Nombre d'unités
- **Unité**: BOX, LOT, PKG, etc. (à ignorer pour la quantité)
- **Date livr.**: Date de livraison (format JJ/MM/AAAA)

## Règles d'extraction

### 1. En-tête
- **origine**: "CLIENT_H"
- **origineCommande**: "H"
- **version**: "ACE"
- **dateCommande**: Convertir format JJ/MM/AAAA en YYYYMMDD (entier)
- **dateLivraison**: Convertir format JJ/MM/AAAA en YYYYMMDD (entier)
- **idCommande**: Format `[codeFournisseur]-[numCommande]-1`
- Ignorer les cases à cocher "Validation requise"

### 2. Produits
Pour chaque ligne du tableau:
- **numLigne**: Colonne `Ligne`
- **codeArticle**: Colonne `Référence`
- **libelle**: Colonne `Libellé`
- **quantite**: Colonne `Quantité` (nombre seulement)
- **commentaire**: toujours vide `""`

### 3. Extraction du tableau
- Trouver la ligne d'en-tête commençant par `Ligne`
- Chaque ligne suivante = un produit
- S'arrêter à une ligne contenant seulement un numéro (ligne incomplète)
- Ignorer les lignes vides ou de séparation

### 4. Règles absolues
- ✅ Un BC CLIENT_H = UNE seule réquisition
- ✅ Extraire TOUS les produits du tableau
- ✅ Ignorer les unités (BOX, LOT, PKG, etc.) dans les quantités
- ✅ Ignorer les cases à cocher de validation
- ✅ Les produits peuvent avoir des dates de livraison différentes (information présente mais pas utilisée dans le JSON)

## Format de sortie attendu

```json
{
  "commandes": [
    {
      "entete": {
        "origine": "CLIENT_H",
        "codeEtablissement": "SITE-B27",
        "codeFournisseur": "HEALTHPRO-DISTRIBUTION",
        "codePostal": "31000",
        "numCommande": "5422424",
        "idCommande": "HEALTHPRO-DISTRIBUTION-5422424-1",
        "dateCommande": 20260122,
        "dateLivraison": 20260129,
        "commentaireEntete": "Commande groupée - Multi-sites\nFacturation centralisée",
        "modeTransport": "MARITIME",
        "typeCommande": "220",
        "origineCommande": "H",
        "version": "ACE"
      },
      "detailCommande": {
        "produits": [
          {
            "numLigne": 1,
            "codeArticle": "IJQB7ABJ",
            "libelle": "THERMOMÈTRE DIGITAL Sans contact",
            "quantite": 215.0,
            "commentaire": ""
          }
        ],
        "nbLignes": 1
      }
    }
  ]
}
```

## Différences avec autres clients

| Critère | CLIENT_H | CLIENT_G | CLIENT_E |
|---------|----------|----------|----------|
| Structure | Formulaire | Facture | Liste hiérarchique |
| Format | Réquisition | Commercial | Ordre |
| En-tête | Champs formulaire | VENDEUR/ACHETEUR | Sections > |
| Produits | Tableau simple | Tableau avec prix | Liste [N] |
| Validation | Cases à cocher | Aucune | Aucune |
| Info unique | Date d'impression | Prix/totaux | Notes optionnelles |
| Présentation | Document admin | Document vente | Document technique |
