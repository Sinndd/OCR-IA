# Prompt spécifique CLIENT_C

## Identification du format
- Client: CLIENT_C
- Format: Bon de commande tabulaire simple (Style A)
- Une commande avec **plusieurs dates de livraison** dans un même BC
- Produits listés par lignes avec colonnes: Lig., Code, Libellé, Qté, Date Liv.

## Structure du BC

### En-tête
- **Numéro de commande**: après `N° Cde:`
- **Date de commande**: après `Date:`
- **Code fournisseur**: après `Fournisseur:`
- **Type commande**: après `Type:` (ex: `220 / L`)
- **Etablissement**: après `Etablissement:`
- **Code postal**: après `CP:`
- **Note**: après `Note:` (peut contenir plusieurs lignes)

### Section produits
Débute après la ligne d’en-tête des colonnes:
`Lig.  Code  Libellé (Nourriture)  Qté  Date Liv.`

**Chaque produit est sur une ligne:**
```
Lig.  Code   Libellé                    Qté  Date Liv.
1     613980 Sauce Tomate Basilic       27   13/01/2026
```

## Règles d’extraction
- ✅ **Regrouper par Date Liv.** : une commande par date de livraison
- ✅ **Numéro de commande identique** pour toutes les dates
- ✅ **Mode transport**: `L` (issu de `Type: 220 / L`)
- ✅ **Type commande**: `220`
- ✅ **Origine commande**: `D`
- ✅ **Version**: `ACE`
- ✅ Extraire la note complète dans `commentaireEntete`

## Format de sortie attendu

```json
{
  "commandes": [
    {
      "entete": {
        "origine": "CLIENT_C",
        "codeEtablissement": "ETAB-61",
        "codeFournisseur": "856414",
        "codePostal": "94150",
        "numCommande": "1480012",
        "idCommande": "1480012",
        "dateCommande": 20260106,
        "dateLivraison": 20260113,
        "commentaireEntete": "Livraison fractionnée\nFragile !",
        "modeTransport": "L",
        "typeCommande": "220",
        "origineCommande": "D",
        "version": "ACE"
      },
      "detailCommande": {
        "produits": [
          {"numLigne": 1, "codeArticle": "613980", "libelle": "Sauce Tomate Basilic", "quantite": 27.0, "commentaire": ""}
        ],
        "nbLignes": 1
      }
    }
  ]
}
```
