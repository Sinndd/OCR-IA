# Prompt spécifique CLIENT_E

## Identification du format
- Client: CLIENT_E
- Format: Liste hiérarchique avec symboles > et -> (Style E)
- Une seule commande par document
- Structure avec sections marquées par symboles

## Structure du BC

### En-tête
Structure hiérarchique avec symboles `>` pour les sections principales:

```
> ORDRE DE COMMANDE
> RÉFÉRENCE COMMANDE
- Numéro: [numéro]
- Date: [JJ/MM/AAAA]
- Livraison: [JJ/MM/AAAA]
- Type: [type]
- Priorité: [priorité]
> DONNÉES FOURNISSEUR
- Code: [codeFournisseur]
-> Etablissement: [etablissement]
-> Code postal: [CP]
> MODALITÉS D'EXPÉDITION
- Transport: [mode]
- Incoterm: [incoterm]
- Devise: [devise]
- Instructions: [texte multiligne]
```

**Éléments à extraire:**
- **numCommande**: après `- Numéro:`
- **dateCommande**: après `- Date:`
- **dateLivraison**: après `- Livraison:`
- **typeCommande**: après `- Type:`
- **codeFournisseur**: après `- Code:` (section DONNÉES FOURNISSEUR)
- **codeEtablissement**: après `-> Etablissement:`
- **codePostal**: après `-> Code postal:`
- **modeTransport**: après `- Transport:`
- **commentaireEntete**: Texte après `- Instructions:` (peut être multiligne)

### Section produits
Débute après `> ARTICLES COMMANDES`

**Format produit:**
```
  [numLigne] Libellé du produit
-> Code: [codeArticle]  |  Quantite: [qté] [unité]  |  Livraison: [date]
```

Ou avec note optionnelle:
```
  [numLigne] Libellé du produit
-> Code: [codeArticle]  |  Quantite: [qté] [unité]  |  Livraison: [date]
  Note: [commentaire]
```

**IMPORTANT:**
- Chaque produit commence par `[numéro]` entre crochets
- Le code article est après `-> Code:`
- La quantité est après `Quantite:` (ignorer l'unité qui suit: M³, L, PKG, etc.)
- Si présent, le commentaire est sur la ligne `Note:` suivante

## Règles d'extraction

### 1. En-tête
- **origine**: "CLIENT_E"
- **origineCommande**: "E"
- **version**: "ACE"
- **dateCommande**: Convertir format JJ/MM/AAAA en YYYYMMDD (entier)
- **dateLivraison**: Convertir format JJ/MM/AAAA en YYYYMMDD (entier)
- **idCommande**: Format `[codeFournisseur]-[numCommande]-1`

### 2. Produits
Pour chaque produit:
- Extraire le **numLigne** entre crochets
- Extraire le **libellé** (texte après `[N]`)
- Extraire le **codeArticle** après `-> Code:`
- Extraire la **quantite** après `Quantite:` (nombre seulement, ignorer l'unité)
- Si ligne `Note:` présente, extraire le **commentaire**

### 3. Règles absolues
- ✅ Un BC CLIENT_E = UNE seule commande
- ✅ Extraire TOUS les produits marqués `[N]`
- ✅ Ignorer les unités (M³, L, PKG, BOX, LOT, etc.) dans les quantités
- ✅ Le commentaire est optionnel

## Format de sortie attendu

```json
{
  "commandes": [
    {
      "entete": {
        "origine": "CLIENT_E",
        "codeEtablissement": "SITE-C28",
        "codeFournisseur": "HEALTHPRO-DISTRIBUTION",
        "codePostal": "67000",
        "numCommande": "9814754",
        "idCommande": "HEALTHPRO-DISTRIBUTION-9814754-1",
        "dateCommande": 20260118,
        "dateLivraison": 20260125,
        "commentaireEntete": "URGENT - Priorité production\nLivraison directe atelier",
        "modeTransport": "EXPRESS",
        "typeCommande": "220",
        "origineCommande": "E",
        "version": "ACE"
      },
      "detailCommande": {
        "produits": [
          {
            "numLigne": 1,
            "codeArticle": "KV9C42RB",
            "libelle": "SERINGUE STÉRILE 5ml Luer-Lock",
            "quantite": 372.0,
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

| Critère | CLIENT_E | CLIENT_A | CLIENT_F |
|---------|----------|----------|----------|
| Structure | Hiérarchique avec > | Tabulaire | Cascade ASCII |
| Séparateurs | > et -> | Lignes/colonnes | Cadres +- |
| Produits | [N] Libellé puis -> | Code # | Code puis -> |
| Commentaires | Note: optionnel | Rares | Rares |
