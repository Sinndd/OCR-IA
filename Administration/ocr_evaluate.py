#!/usr/bin/env python3
"""
OCR Evaluate - Évaluation de la précision du système
Compare les JSONs générés avec les JSONs attendus pour mesurer la performance
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
from datetime import datetime
import tempfile
import shutil

# Import du système de production
sys.path.insert(0, str(Path(__file__).parent.parent / "Production"))
from ocr_smart import SmartExtractor


class JSONComparator:
    """Compare deux JSONs et calcule la précision"""
    
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.stats = {
            "total_fields": 0,
            "correct_fields": 0,
            "errors": []
        }
    
    def compare_value(self, path: str, expected: Any, actual: Any) -> bool:
        """Compare deux valeurs et enregistre le résultat"""
        self.stats["total_fields"] += 1
        
        # Normalisation pour comparaison
        exp_normalized = self._normalize_value(expected)
        act_normalized = self._normalize_value(actual)
        
        if exp_normalized == act_normalized:
            self.stats["correct_fields"] += 1
            return True
        else:
            self.stats["errors"].append({
                "path": path,
                "expected": expected,
                "actual": actual
            })
            return False
    
    def _normalize_value(self, value: Any) -> Any:
        """Normalise une valeur pour la comparaison"""
        if isinstance(value, str):
            return value.strip().lower()
        elif value is None or value == "":
            return None
        return value
    
    def compare_dicts(self, expected: Dict, actual: Dict, path: str = "") -> None:
        """Compare deux dictionnaires récursivement"""
        
        # Vérifier toutes les clés de expected
        for key, exp_value in expected.items():
            current_path = f"{path}.{key}" if path else key
            
            if key not in actual:
                self.stats["errors"].append({
                    "path": current_path,
                    "expected": exp_value,
                    "actual": "MISSING"
                })
                self.stats["total_fields"] += 1
                continue
            
            act_value = actual[key]
            
            # Comparaison récursive selon le type
            if isinstance(exp_value, dict):
                self.compare_dicts(exp_value, act_value, current_path)
            elif isinstance(exp_value, list):
                self.compare_lists(exp_value, act_value, current_path)
            else:
                self.compare_value(current_path, exp_value, act_value)
    
    def compare_lists(self, expected: List, actual: List, path: str) -> None:
        """Compare deux listes"""
        
        # Comparer la longueur
        if len(expected) != len(actual):
            self.stats["errors"].append({
                "path": f"{path}.length",
                "expected": len(expected),
                "actual": len(actual)
            })
        
        # Comparer chaque élément
        for i, (exp_item, act_item) in enumerate(zip(expected, actual)):
            if isinstance(exp_item, dict):
                self.compare_dicts(exp_item, act_item, f"{path}[{i}]")
            else:
                self.compare_value(f"{path}[{i}]", exp_item, act_item)
    
    def get_precision(self) -> float:
        """Calcule la précision globale"""
        if self.stats["total_fields"] == 0:
            return 0.0
        return (self.stats["correct_fields"] / self.stats["total_fields"]) * 100
    
    def get_field_stats(self) -> Dict[str, Dict]:
        """Calcule les statistiques par champ"""
        field_stats = {}
        
        # Compter les erreurs par champ racine
        for error in self.stats["errors"]:
            field = error["path"].split(".")[0].split("[")[0]
            if field not in field_stats:
                field_stats[field] = {"errors": 0, "total": 0}
            field_stats[field]["errors"] += 1
        
        # Compter le total par champ
        # (approximation basée sur les erreurs)
        for field in field_stats:
            field_stats[field]["total"] = field_stats[field]["errors"]
        
        return field_stats


class OCREvaluator:
    """Évalue la précision du système OCR"""
    
    def __init__(
        self,
        patterns_dir: Path,
        agences_file: Path,
        clients_file: Path,
        debug: bool = False
    ):
        self.patterns_dir = patterns_dir
        self.agences_file = agences_file
        self.clients_file = clients_file
        self.debug = debug
        
        # Initialiser l'extracteur
        self.extractor = SmartExtractor(
            patterns_dir=patterns_dir,
            agences_file=agences_file,
            clients_file=clients_file,
            debug=debug
        )
    
    def evaluate_client(
        self,
        client_id: str,
        test_dir: Path = None
    ) -> Dict[str, Any]:
        """
        Évalue un client en testant sur ses exemples
        
        Args:
            client_id: ID du client à évaluer
            test_dir: Dossier contenant les exemples (défaut: examples/{client_id}/)
        
        Returns:
            Dictionnaire avec les résultats d'évaluation
        """
        
        if test_dir is None:
            test_dir = Path("examples") / client_id
        
        if not test_dir.exists():
            raise FileNotFoundError(f"Dossier de test introuvable: {test_dir}")
        
        print(f"\n{'='*60}")
        print(f"📊 ÉVALUATION CLIENT: {client_id}")
        print(f"{'='*60}\n")
        print(f"📂 Dossier de test: {test_dir}\n")
        
        # Trouver tous les exemples
        examples = self._find_examples(test_dir)
        
        if not examples:
            print("❌ Aucun exemple trouvé")
            return {"error": "No examples found"}
        
        print(f"🧪 {len(examples)} exemple(s) à tester\n")
        
        # Évaluer chaque exemple
        results = []
        global_comparator = JSONComparator(debug=self.debug)
        
        for i, (bc_path, expected_jsons) in enumerate(examples, 1):
            print(f"[{i}/{len(examples)}] Test: {bc_path.name}")
            
            result = self._evaluate_single(bc_path, expected_jsons, global_comparator)
            results.append(result)
            
            if result["success"]:
                print(f"  ✅ Précision: {result['precision']:.1f}%")
            else:
                print(f"  ❌ Erreur: {result.get('error', 'Unknown')}")
            print()
        
        # Statistiques globales
        precision = global_comparator.get_precision()
        
        print(f"\n{'='*60}")
        print(f"📈 RÉSULTATS GLOBAUX")
        print(f"{'='*60}\n")
        print(f"Précision globale: {precision:.1f}%")
        print(f"Champs corrects: {global_comparator.stats['correct_fields']}/{global_comparator.stats['total_fields']}")
        print(f"Erreurs: {len(global_comparator.stats['errors'])}")
        
        # Afficher les erreurs détaillées si debug
        if self.debug and global_comparator.stats['errors']:
            print(f"\n❌ Erreurs détectées:\n")
            for error in global_comparator.stats['errors'][:10]:  # Limiter à 10
                print(f"  • {error['path']}")
                print(f"    Attendu: {error['expected']}")
                print(f"    Obtenu:  {error['actual']}")
                print()
        
        return {
            "client_id": client_id,
            "test_dir": str(test_dir),
            "nb_examples": len(examples),
            "precision": precision,
            "total_fields": global_comparator.stats["total_fields"],
            "correct_fields": global_comparator.stats["correct_fields"],
            "nb_errors": len(global_comparator.stats["errors"]),
            "errors": global_comparator.stats["errors"],
            "results": results
        }
    
    def _find_examples(self, test_dir: Path) -> List[Tuple[Path, List[Path]]]:
        """Trouve tous les exemples dans le dossier de test"""
        examples = []
        
        # Parcourir les sous-dossiers (exemple_1_*, exemple_2_*, etc.)
        for subdir in sorted(test_dir.glob("exemple_*")):
            if not subdir.is_dir():
                continue
            
            # Trouver le BC PDF
            bc_files = list(subdir.glob("*.pdf"))
            if not bc_files:
                continue
            
            bc_path = bc_files[0]  # Prendre le premier PDF
            
            # Trouver tous les JSONs attendus
            json_files = sorted(subdir.glob("*.json"))
            
            if json_files:
                examples.append((bc_path, json_files))
        
        return examples
    
    def _evaluate_single(
        self,
        bc_path: Path,
        expected_jsons: List[Path],
        global_comparator: JSONComparator
    ) -> Dict[str, Any]:
        """Évalue un seul BC"""
        
        try:
            # Créer un dossier temporaire pour les résultats
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_out = Path(tmp_dir)
                
                # Générer le JSON
                result_json = self.extractor.process_bc(bc_path=bc_path)
                
                # Sauvegarder le JSON généré
                output_file = tmp_out / f"{bc_path.stem}.json"
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(result_json, f, indent=2, ensure_ascii=False)
                
                # Le JSON généré
                generated_jsons = [output_file]
                
                if not generated_jsons:
                    return {
                        "success": False,
                        "error": "Aucun JSON généré"
                    }
                
                # Comparer chaque JSON
                comparator = JSONComparator(debug=self.debug)
                
                for expected_json in expected_jsons:
                    # Charger le JSON attendu
                    with open(expected_json, 'r', encoding='utf-8') as f:
                        expected = json.load(f)
                    
                    # Trouver le JSON généré correspondant (par nom ou index)
                    # Pour simplifier, on compare dans l'ordre
                    idx = expected_jsons.index(expected_json)
                    if idx < len(generated_jsons):
                        actual_path = generated_jsons[idx]
                        
                        with open(actual_path, 'r', encoding='utf-8') as f:
                            actual = json.load(f)
                        
                        # Comparer
                        comparator.compare_dicts(expected, actual)
                        global_comparator.compare_dicts(expected, actual)
                
                return {
                    "success": True,
                    "bc_path": str(bc_path),
                    "nb_expected": len(expected_jsons),
                    "nb_generated": len(generated_jsons),
                    "precision": comparator.get_precision(),
                    "errors": comparator.stats["errors"]
                }
        
        except Exception as e:
            return {
                "success": False,
                "bc_path": str(bc_path),
                "error": str(e)
            }


def main():
    parser = argparse.ArgumentParser(
        description="🧪 Évaluation de la précision du système OCR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples d'utilisation:

  # Évaluer un client
  python ocr_evaluate.py --client-id API

  # Évaluer avec dossier de test personnalisé
  python ocr_evaluate.py \\
    --client-id API \\
    --test-dir examples/API

  # Mode debug (affiche les erreurs détaillées)
  python ocr_evaluate.py --client-id API --debug
        """
    )
    
    parser.add_argument(
        '--client-id',
        required=True,
        help="Identifiant du client à évaluer (ex: API, NEWREST)"
    )
    
    parser.add_argument(
        '--test-dir',
        type=Path,
        help="Dossier contenant les exemples de test (défaut: examples/{client_id}/)"
    )
    
    parser.add_argument(
        '--patterns-dir',
        type=Path,
        default=Path("patterns"),
        help="Dossier des patterns (défaut: patterns/)"
    )
    
    parser.add_argument(
        '--agences-file',
        type=Path,
        default=Path("Données/refs/agencesPAP.txt"),
        help="Fichier des agences de référence"
    )
    
    parser.add_argument(
        '--clients-file',
        type=Path,
        default=Path("Données/refs/clients.txt"),
        help="Fichier des clients de référence"
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help="Mode debug (affiche les détails)"
    )
    
    parser.add_argument(
        '--output',
        type=Path,
        help="Fichier JSON pour sauvegarder les résultats"
    )
    
    args = parser.parse_args()
    
    # Créer l'évaluateur
    evaluator = OCREvaluator(
        patterns_dir=args.patterns_dir,
        agences_file=args.agences_file,
        clients_file=args.clients_file,
        debug=args.debug
    )
    
    # Évaluer
    results = evaluator.evaluate_client(
        client_id=args.client_id,
        test_dir=args.test_dir
    )
    
    # Sauvegarder si demandé
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Résultats sauvegardés: {args.output}")
    
    # Code de sortie selon la précision
    precision = results.get("precision", 0)
    if precision >= 95:
        print(f"\n🎉 Excellent ! Précision >= 95%")
        exit(0)
    elif precision >= 80:
        print(f"\n👍 Bon ! Précision >= 80%")
        exit(0)
    else:
        print(f"\n⚠️  Attention ! Précision < 80% - Entraînement nécessaire")
        exit(1)


if __name__ == "__main__":
    main()
