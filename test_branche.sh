#!/bin/bash
# Script de test pour comparer les deux versions

echo "🧪 TEST DE LA BRANCHE EXPÉRIMENTALE"
echo "===================================="
echo ""

# Couleurs
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
BC_TEST="Données/BC/Bon_de_commande_anonymisé.pdf"
RESULTATS_DIR="resultats/test_comparaison"

echo -e "${BLUE}📍 Branche actuelle:${NC}"
git branch --show-current
echo ""

echo -e "${BLUE}📂 Test avec:${NC} $BC_TEST"
echo ""

# Vérifier que le BC existe
if [ ! -f "$BC_TEST" ]; then
    echo "❌ Fichier BC introuvable: $BC_TEST"
    exit 1
fi

# Créer le dossier de résultats
mkdir -p "$RESULTATS_DIR"

# Activer l'environnement virtuel
echo -e "${YELLOW}🔧 Activation de l'environnement virtuel...${NC}"
source venv/bin/activate

echo ""
echo -e "${GREEN}🚀 Lancement de l'extraction (mode debug)...${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Lancer l'extraction avec debug
python Production/ocr_smart.py \
    --input "$BC_TEST" \
    --out-dir "$RESULTATS_DIR" \
    --agences-file Données/refs/agencesPAP.txt \
    --clients-file Données/refs/clients.txt \
    --debug

EXIT_CODE=$?

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✅ Extraction réussie !${NC}"
    echo ""
    echo -e "${BLUE}📊 Résultats générés:${NC}"
    ls -lh "$RESULTATS_DIR"/*.json 2>/dev/null || echo "Aucun fichier JSON trouvé"
    
    echo ""
    echo -e "${BLUE}📝 Contenu d'un fichier (aperçu):${NC}"
    FIRST_JSON=$(ls "$RESULTATS_DIR"/*.json 2>/dev/null | head -1)
    if [ -n "$FIRST_JSON" ]; then
        echo "Fichier: $(basename $FIRST_JSON)"
        echo ""
        # Afficher les premières lignes
        head -30 "$FIRST_JSON"
        echo "..."
        # Compter les produits
        NB_PRODUITS=$(grep -o '"produits":' "$FIRST_JSON" | wc -l)
        echo ""
        echo -e "${GREEN}→ Nombre de sections produits: $NB_PRODUITS${NC}"
    fi
    
    # Vérifier si le cache a été créé
    echo ""
    if [ -f "patterns/patterns_cache.json" ]; then
        echo -e "${GREEN}⚡ Cache de patterns créé/mis à jour${NC}"
        CACHE_SIZE=$(du -h "patterns/patterns_cache.json" | cut -f1)
        echo "   Taille: $CACHE_SIZE"
    fi
else
    echo -e "${YELLOW}⚠️  Extraction terminée avec erreur (code: $EXIT_CODE)${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${BLUE}💡 Prochaines étapes:${NC}"
echo "   1. Vérifier la qualité des résultats dans: $RESULTATS_DIR"
echo "   2. Comparer avec les anciens résultats si disponibles"
echo "   3. Si satisfait: git checkout master puis git merge feature/multi-examples-smart-extraction"
echo "   4. Si non satisfait: git checkout master (pour revenir en arrière)"
echo ""
