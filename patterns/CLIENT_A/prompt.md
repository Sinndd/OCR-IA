# Prompt spécifique CLIENT_A

## Identification du format
- Client: CLIENT_A (NEWREST RESTAURATION)
- Format: Bon de commande tabulaire avec en-tête détaillé
- Une seule date de livraison par BC
- Produits organisés en tableau structuré

## Structure du BC

### En-tête (lignes 1-35 environ)
- **Numéro de commande**: `N° bon de commande [numéro]` (ligne 1)
- **Code site fournisseur**: `Code site Frns : [code]` (chercher cette ligne)
- **Date de livraison**: Section "Date de Livraison" avec date au format `JJ/MM/AAAA`
- **Gestionnaire**: Ligne contenant `@newrest.eu`

### Section produits
Débute après `Article ([nombre])`

**Format tabulaire avec colonnes:**
```
Article (N)    Quantité    Packaging    Quantité livrée    Prix unitaire    ...
```

### Pattern produit (CRITIQUE)

**Chaque produit occupe 2-3 lignes:**

1. **Catégorie** (ligne optionnelle): 
   - Commence par `F-` (ex: `F-CHARCUTERIE - PORC`)
   - À ignorer, c'est juste un séparateur

2. **Ligne principale du produit:**
   - **Libellé**: Description complète (ex: `PORC JAMBON CUIT CHOIX DD TR 40/50G`)
   - **Code article**: Format `UE#[code]([référence])` ou `#[code]([référence])`
     - Exemple: `UE#488(150508)` → code = `488`
     - Exemple: `#3731(27402)` → code = `3731`

3. **Ligne de données numériques:**
   - Commence par la quantité (chiffre)
   - Contient: packaging, prix, etc.
   - Format: `[Qté] [Packaging] [PrixUnit] [PrixPkg] [PoidsPckg] [Total] [TVA]`

**IMPORTANT:** Le code article peut être sur la même ligne ou la ligne suivante du libellé.

## Instructions d'extraction

### 1. Extraire l'en-tête
- Numéro de commande: chercher `N° bon de commande `
- Code site: chercher `Code site Frns : `
- Date de livraison: chercher `Date de Livraison` puis la date sur la ligne suivante
- Code postal: extraire depuis l'adresse (5 chiffres)

### 2. Identifier la section produits
- Commence après la ligne `Article ([nombre])`
- Se termine à la fin du document ou avant "Total"

### 3. Extraire chaque produit
Pour chaque produit:
- **Ignorer** les lignes commençant par `F-` (catégories)
- **Libellé**: Ligne de texte descriptif (tout en majuscules généralement)
- **Code article**: Extraire depuis pattern `#[code]([ref])`
  - Prendre uniquement `[code]` (partie entre # et parenthèse)
  - Exemples: `#488` → `488`, `#3731` → `3731`
- **Quantité**: Premier nombre de la ligne de données suivante

### 4. Règles absolues
- ✅ Un BC CLIENT_A = UNE seule commande (une seule date)
- ✅ Extraire TOUS les produits du tableau
- ✅ Ne pas confondre les catégories `F-` avec les produits
- ✅ Le code article est toujours au format `#[code]([référence])`

## Format de sortie attendu

```json
{
  "commandes": [
    {
      "entete": {
        "origine": "CLIENT_A",
        "codeEtablissement": "910956",
        "numCommande": "910956-1435312",
        "dateLivraison": 20250109,
        ...
      },
      "detailCommande": {
        "produits": [
          {"codeArticle": "488", "libelle": "PORC JAMBON CUIT CHOIX DD TR 40/50G", "quantite": 2.0, ...},
          {"codeArticle": "3731", "libelle": "OEUF ENTIER LIQUIDE 2L", "quantite": 2.0, ...},
          ...
        ]
      }
    }
  ]
}
```

## Différences avec CLIENT_B

| Critère | CLIENT_A | CLIENT_B |
|---------|----------|----------|
| Nb commandes | 1 par BC | Plusieurs possibles |
| Format | Tableau structuré | Texte libre |
| Code article | `#code(ref)` | 5-6 chiffres seuls |
| Libellé | Ligne texte | `[A] description` |
| Catégories | Lignes `F-` | Aucune |
