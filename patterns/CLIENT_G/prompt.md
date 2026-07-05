# Prompt spécifique CLIENT_G

## Identification du format
- Client: CLIENT_G
- Format: Bon de commande commercial avec calculs (Style G)
- Une seule commande par document
- Structure de facture commerciale avec tableau de produits

## Structure du BC

### En-tête
Structure en deux blocs (VENDEUR / ACHETEUR):

```
BON DE COMMANDE COMMERCIAL
Avec calcul automatique des montants
VENDEUR
Fournisseur: [codeFournisseur]
CP: [codePostal]
Transport: [modeTransport]
Incoterm: [incoterm]
ACHETEUR
Etablissement: [codeEtablissement]
Type: [typeCommande]
Devise: [devise]
Priorité: [priorité]
Commande N° [numCommande] du [JJ/MM/AAAA]
Livraison prévue: [JJ/MM/AAAA]
[Commentaires multilignes]
```

**Éléments à extraire:**
- **codeFournisseur**: après `Fournisseur:`
- **codePostal**: après `CP:`
- **modeTransport**: après `Transport:`
- **codeEtablissement**: après `Etablissement:`
- **typeCommande**: après `Type:`
- **numCommande**: après `Commande N°` (avant `du`)
- **dateCommande**: après `du` (format JJ/MM/AAAA)
- **dateLivraison**: après `Livraison prévue:`
- **commentaireEntete**: Lignes suivantes avant le tableau

### Section produits
Tableau avec en-têtes de colonnes:

```
Pos  Code  Description  Qté  Unité  P.U. (devise)  Total (devise)
```

**Format produit (une ligne):**
```
[pos]  [code]  [description]  [qté]  [unité]  [prix]  [total]
```

**IMPORTANT:**
- **Pos**: Numéro de ligne (position dans le tableau)
- **Code**: Code article
- **Description**: Libellé du produit (peut être tronqué en fin de ligne)
- **Qté**: Quantité commandée
- **Unité**: LOT, M³, M, BOX, etc. (à ignorer pour la quantité)
- **P.U.**: Prix unitaire (à ignorer)
- **Total**: Montant total (à ignorer)

## Règles d'extraction

### 1. En-tête
- **origine**: "CLIENT_G"
- **origineCommande**: "G"
- **version**: "ACE"
- **dateCommande**: Convertir format JJ/MM/AAAA en YYYYMMDD (entier)
- **dateLivraison**: Convertir format JJ/MM/AAAA en YYYYMMDD (entier)
- **idCommande**: Format `[codeFournisseur]-[numCommande]-1`

### 2. Produits
Pour chaque ligne du tableau:
- **numLigne**: Colonne `Pos`
- **codeArticle**: Colonne `Code`
- **libelle**: Colonne `Description` (peut être tronquée)
- **quantite**: Colonne `Qté` (nombre seulement, ignorer l'unité)
- **commentaire**: toujours vide `""`

### 3. Extraction du tableau
- Trouver la ligne d'en-tête commençant par `Pos`
- Chaque ligne suivante = un produit
- S'arrêter à une ligne vide ou à des totaux/sous-totaux
- **ATTENTION**: Les descriptions peuvent être coupées ou continuer sur plusieurs lignes

### 4. Règles absolues
- ✅ Un BC CLIENT_G = UNE seule commande
- ✅ Extraire TOUS les produits du tableau
- ✅ Ignorer les colonnes de prix (P.U., Total)
- ✅ Ignorer les lignes de totaux (sous-total, TVA, total général)

## Format de sortie attendu

```json
{
  "commandes": [
    {
      "entete": {
        "origine": "CLIENT_G",
        "codeEtablissement": "SITE-C11",
        "codeFournisseur": "CHIPWORLD-FRANCE",
        "codePostal": "38000",
        "numCommande": "7189219",
        "idCommande": "CHIPWORLD-FRANCE-7189219-1",
        "dateCommande": 20260206,
        "dateLivraison": 20260213,
        "commentaireEntete": "Commande groupée - Multi-sites\nFacturation centralisée",
        "modeTransport": "MARITIME",
        "typeCommande": "SPOT",
        "origineCommande": "G",
        "version": "ACE"
      },
      "detailCommande": {
        "produits": [
          {
            "numLigne": 1,
            "codeArticle": "ZQWNJ3NS",
            "libelle": "LED RGB SMD 5050 Common Anode",
            "quantite": 473.0,
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

| Critère | CLIENT_G | CLIENT_F | CLIENT_H |
|---------|----------|----------|----------|
| Structure | Facture commerciale | Cascade ASCII | Réquisition |
| Format | Tableau avec prix | Cadres \| | Formulaire |
| En-tête | VENDEUR/ACHETEUR | Cadre unique | Formulaire à cases |
| Produits | Tableau multi-colonnes | Liste indentée | Tableau simple |
| Calculs | Prix et totaux | Aucun | Aucun |
| Info unique | Prix unitaires | Dates livraison/produit | Cases validation |
