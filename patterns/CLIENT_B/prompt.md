# Spécifications CLIENT_B

## Structure du BC
- **Multi-commandes** : Plusieurs dates de livraison possibles
- **Marqueur de section** : `[jour] [JJ] [mois]. [AAAA]` suivi de `Livraison au :`
  - Exemple : `lundi 08 jan. 2024` puis ligne `Livraison au :`

## ⚠️ DÉTECTION DES DATES DE LIVRAISON (CRITIQUE)

### Format de la date de livraison
La date de livraison apparaît UNIQUEMENT après le texte "Livraison au :" :
```
Livraison au : lundi 19 jan. 2026
```

### Ce qui N'EST PAS une date de livraison
- **Date en haut du BC** (ex: `12/01/2026`) = Date de création du BC
- **Dates répétées sur chaque ligne produit** (ex: `20/01/2026`) = Date de péremption/DLC
- **Colonne "Conso"** = Dates de consommation

### Règle de comptage
1. Chercher TOUTES les occurrences de "Livraison au :" dans le texte
2. Extraire la date qui suit chaque occurrence
3. Compter les dates UNIQUES (si la même date apparaît 2 fois = 1 commande)
4. **Nombre de commandes = Nombre de dates de livraison UNIQUES**

### Exemples
- `Livraison au : lundi 19 jan. 2026` (une seule fois) → **1 commande**
- `Livraison au : lundi 08 jan. 2024` + `Livraison au : mercredi 10 jan. 2024` + `Livraison au : lundi 15 jan. 2024` → **3 commandes**

## Pattern produit (CRITIQUE)

**Chaque produit suit ce pattern strict :**
1. **Code article** : 5-6 chiffres seuls sur une ligne (ex: `32732`, `115195`)
2. **Libellé** : Ligne commençant par `[A]` (peut être avant OU après le code)
3. **Quantité** : Deux formats possibles :
   - **Format 1** : `XX,""` ou `XXX,""` (ex: `5,""` = 5, `100,""` = 100)
   - **Format 2** : `(XX Sachet...)` ou `XX,00 Pièce/Seau/Boîte` (ex: `(20 Sachet de 1 Kg)` = 20)
   - **NE PAS confondre avec les poids** (ex: `1 Kg` ou `2.5 Kg` ne sont PAS des quantités)

**Exemples de lecture :**
```
32732
[A] Cornichons fins...
Boîte 5/1 de 2.12 Kg     ← 2.12 Kg est le POIDS, pas la quantité
5,""                      ← Quantité = 5 (format 1)
X,XXXJ                    ← Prix (ignorer)

114820
[A] Farandole de champignons 1K (Import)
(METRO CHEF)
Kg (20 Sachet de 1 Kg)   ← Quantité = 20 (format 2: dans "20 Sachet")
X,XXXJ                    ← Prix (ignorer)

115195
[A] Frites 9/9mm...
Kg (40 Sachet)           ← Quantité = 40 (format 2)
100,""                    ← OU Quantité = 100 si cette ligne existe (format 1)
```

⚠️ **RÈGLE QUANTITÉ** : 
- Si tu vois `(XX Sachet...)` → la quantité est XX
- Si tu vois `XX,""` → la quantité est XX
- Si tu vois `XX,00 Pièce/Seau/Boîte` → la quantité est XX
- **JAMAIS** prendre le poids (Kg, Gr, L) comme quantité !

**IMPORTANT** : Le code peut apparaître AVANT ou APRÈS le libellé `[A]`

## Règles d'extraction

### Segmentation par dates (multi-commandes)
- **Section 1** : De la 1ère occurrence "Livraison au :" à la 2ème
- **Section 2** : De la 2ème occurrence "Livraison au :" à la 3ème
- etc.
- **Ne JAMAIS mélanger** les produits entre sections

### Dates de commande
- **Date de commande** : Date de livraison - 1 jour
- Si date de livraison = 08/01/2024, alors date de commande = 07/01/2024
- Format : YYYYMMDD

### Extraction des produits
- Chercher TOUS les codes 5-6 chiffres isolés dans la section
- Associer chaque code au libellé `[A]` le plus proche
- **Quantité** : Ligne au format `XX,""` juste avant `X,XXXJ`

## Exemple attendu
**BC 02313_BC_7992** (3 occurrences "Livraison au :" avec 3 dates différentes) :
- Date 1 (08/01): 6 produits (32732, 01454, 115195, 118035, 100749, 32085)
- Date 2 (10/01): 4 produits (155472, 11845, 161515, 32180)
- Date 3 (15/01): 3 produits (32732, 153470, 114820)
- **Total: 13 produits** avec leurs quantités réelles

**BC 05284_BC_1933** (1 seule occurrence "Livraison au : lundi 19 jan. 2026") :
- **1 SEULE commande** avec EXACTEMENT 25 produits :
  `157358, 166606, 67156, 157545, 162423, 152938, 40073, 158733, 166495, 32734, 164239, 55304, 33245, 13005, 157558, 01880, 34384, 10384, 34823, 166464, 36907, 34341, 160113, 67179, 159320`

## ⚠️ EXTRACTION COMPLÈTE (CRITIQUE)

**Tu DOIS extraire TOUS les produits sans exception.**

Méthode de comptage :
1. Cherche TOUS les codes 5-6 chiffres seuls sur une ligne
2. Chaque code = 1 produit à extraire
3. **Ne saute AUCUN code**, même s'il est au milieu du document
4. Les codes `40073` et `160113` sont souvent oubliés → NE PAS les oublier

**Liste de vérification pour BC 1933** : 25 codes exactement
- Début: 157358, 166606, 67156...
- Milieu: **40073** (Cantal), 158733, 166495...
- Fin: **160113** (Semoule), 67179, 159320
