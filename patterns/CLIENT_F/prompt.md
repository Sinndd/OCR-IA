# Prompt spécifique CLIENT_F

## Identification du format
- Client: CLIENT_F
- Format: Cascade ASCII avec cadres (Style F)
- Une seule commande par document
- Utilise des caractères ASCII pour la mise en forme: +, -, |

## Structure du BC

### En-tête
Structure en cadre ASCII:

```
+- COMMANDE ----------------------------------------+
| REF-CMD    : [numéro]
| DATE       : [JJ/MM/AAAA]
| DELIVERY   : [JJ/MM/AAAA]
| TYPE       : [type] | PRIO: [priorité]
| -------------------------------------------------
| SUPPLIER   : [codeFournisseur]
|   -> SITE  : [etablissement]
|   -> ZIP   : [CP]
| -------------------------------------------------
| TRANSPORT  : [mode]
| INCOTERM   : [incoterm]
| CURRENCY   : [devise]
| -------------------------------------------------
| NOTES      : [texte multiligne]
+---------------------------------------------------+
```

**Éléments à extraire:**
- **numCommande**: après `REF-CMD    :`
- **dateCommande**: après `DATE       :`
- **dateLivraison**: après `DELIVERY   :`
- **typeCommande**: après `TYPE       :` (avant le `|`)
- **codeFournisseur**: après `SUPPLIER   :`
- **codeEtablissement**: après `-> SITE  :`
- **codePostal**: après `-> ZIP   :`
- **modeTransport**: après `TRANSPORT  :`
- **commentaireEntete**: Texte après `NOTES      :` (peut être multiligne)

### Section produits
Débute après le cadre `+- ITEMS ------------------------------------------+`

**Format produit:**
```
| [NN] [codeArticle]
|     -> [Libellé]
|        QTY: [qté] [unité]  |  DLV: [date]
|
```

**IMPORTANT:**
- Chaque produit commence par `| [NN]` avec numéro entre crochets
- Code article sur la même ligne que `[NN]`
- Libellé sur ligne suivante avec `|     ->`
- Quantité après `QTY:` (ignorer l'unité)
- Date de livraison après `DLV:` (format JJ/MM/AAAA)

## Règles d'extraction

### 1. En-tête
- **origine**: "CLIENT_F"
- **origineCommande**: "F"
- **version**: "ACE"
- **dateCommande**: Convertir format JJ/MM/AAAA en YYYYMMDD (entier)
- **dateLivraison**: Convertir format JJ/MM/AAAA en YYYYMMDD (entier)
- **idCommande**: Format `[codeFournisseur]-[numCommande]-1`

### 2. Produits
Pour chaque produit:
- Extraire le **numLigne** entre crochets `[NN]`
- Extraire le **codeArticle** après le numéro (même ligne)
- Extraire le **libellé** sur la ligne `|     ->` suivante
- Extraire la **quantite** après `QTY:` (nombre seulement)
- **commentaire**: toujours vide `""`

### 3. Règles absolues
- ✅ Un BC CLIENT_F = UNE seule commande
- ✅ Extraire TOUS les produits marqués `| [NN]`
- ✅ Ignorer les unités (M, PKG, SET, KG, M³, etc.) dans les quantités
- ✅ Ignorer les caractères de cadre (+, -, |) lors de l'extraction

## Format de sortie attendu

```json
{
  "commandes": [
    {
      "entete": {
        "origine": "CLIENT_F",
        "codeEtablissement": "SITE-D45",
        "codeFournisseur": "DISTRIB-TECH-FR",
        "codePostal": "38000",
        "numCommande": "3521156",
        "idCommande": "DISTRIB-TECH-FR-3521156-1",
        "dateCommande": 20260122,
        "dateLivraison": 20260129,
        "commentaireEntete": "Livraison fractionnée selon planning\nContrôle qualité renforcé",
        "modeTransport": "EXPRESS",
        "typeCommande": "SPOT",
        "origineCommande": "F",
        "version": "ACE"
      },
      "detailCommande": {
        "produits": [
          {
            "numLigne": 1,
            "codeArticle": "V50PCGIL",
            "libelle": "CIRCUIT INTEGRE REF#XK4879-B",
            "quantite": 451.0,
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

| Critère | CLIENT_F | CLIENT_E | CLIENT_G |
|---------|----------|----------|----------|
| Structure | Cadres ASCII | Hiérarchique > | Tableau facture |
| Séparateurs | +- et \| | > et -> | Lignes de tableau |
| En-tête | Cadre avec \| | Sections > | Blocs VENDEUR/ACHETEUR |
| Produits | \| [NN] Code puis -> | [N] puis -> | Positions en tableau |
| Mise en forme | Cascade ASCII | Liste indentée | Format commercial |
