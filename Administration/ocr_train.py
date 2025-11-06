#!/usr/bin/env python3
"""
OCR Train - Entraînement du système auto-adaptatif
Permet d'uploader des BCs exemples + JSONs attendus pour apprendre les patterns
Zero-code : aucun développement nécessaire pour nouveaux clients
"""

import argparse
import json
import re
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
import shutil

import fitz  # PyMuPDF


class PatternTrainer:
    """
    Système d'entraînement pour l'auto-apprentissage
    Upload BC samples + JSON attendus → Sauvegarde patterns
    """
    
    def __init__(self, patterns_base_dir: Path = None):
        self.patterns_base_dir = patterns_base_dir or Path("patterns")
        self.patterns_base_dir.mkdir(exist_ok=True)
    
    def train_client(
        self,
        client_id: str,
        bc_samples: List[Path],
        expected_jsons: List[Path],
        replace: bool = False,
        multi_json_mode: bool = False
    ) -> bool:
        """
        Entraîne le système sur un nouveau client
        
        Args:
            client_id: Identifiant unique du client (ex: NEWREST, API, SODEXO)
            bc_samples: Liste des PDFs exemples
            expected_jsons: Liste des JSONs attendus correspondants
            replace: Si True, remplace les patterns existants
            multi_json_mode: Si True, 1 BC peut avoir plusieurs JSONs (cas multi-dates)
        """
        
        # Validation
        if not multi_json_mode:
            # Mode classique: 1 BC = 1 JSON
            if len(bc_samples) != len(expected_jsons):
                print(f"❌ Erreur: {len(bc_samples)} BCs mais {len(expected_jsons)} JSONs")
                print(f"💡 Astuce: Si 1 BC génère plusieurs JSONs, utilisez --multi-json")
                return False
        else:
            # Mode multi-json: 1 BC = N JSONs
            if len(bc_samples) != 1:
                print(f"❌ Erreur en mode --multi-json: 1 seul BC attendu, mais {len(bc_samples)} fourni(s)")
                return False
            if len(expected_jsons) == 0:
                print(f"❌ Erreur: Au moins 1 JSON requis")
                return False
        
        if len(bc_samples) == 0:
            print("❌ Erreur: Au moins 1 exemple requis")
            return False
        
        # Vérifier que tous les fichiers existent
        for bc in bc_samples:
            if not bc.exists():
                print(f"❌ BC introuvable: {bc}")
                return False
        
        for json_file in expected_jsons:
            if not json_file.exists():
                print(f"❌ JSON introuvable: {json_file}")
                return False
        
        # Créer dossier client
        client_dir = self.patterns_base_dir / f"CLIENT_{client_id}"
        
        if client_dir.exists() and not replace:
            print(f"⚠️  Client {client_id} existe déjà (utilisez --replace pour écraser)")
            return False
        
        if replace and client_dir.exists():
            print(f"🗑️  Suppression patterns existants pour {client_id}...")
            shutil.rmtree(client_dir)
        
        client_dir.mkdir(exist_ok=True)
        
        print(f"\n{'='*60}")
        print(f"🎓 ENTRAÎNEMENT CLIENT: {client_id}")
        print(f"📚 {len(bc_samples)} BC(s) avec {len(expected_jsons)} JSON(s)")
        if multi_json_mode:
            print(f"🔀 Mode multi-JSON: 1 BC → {len(expected_jsons)} JSONs")
        print(f"{'='*60}\n")
        
        # Traiter chaque exemple
        patterns_detected = {
            "mots_cles_detection": set(),
            "format_dates": set(),
            "codes_articles_typiques": set(),
            "origines": set(),
            "filename_convention": None  # Convention de nommage
        }
        
        # Mode multi-json: 1 BC → plusieurs JSONs
        if multi_json_mode:
            bc_path = bc_samples[0]
            print(f"[1/1] Traitement de {bc_path.name}...")
            
            # 1. Extraction texte du BC (une seule fois)
            bc_text = self._extract_text_from_pdf(bc_path)
            if not bc_text:
                print(f"  ❌ Impossible d'extraire le texte")
                return False
            
            print(f"  ✓ {len(bc_text)} caractères extraits")
            
            # 2. Sauvegarder le BC une fois
            bc_text_file = client_dir / f"training_bc_1.txt"
            with open(bc_text_file, 'w', encoding='utf-8') as f:
                f.write(bc_text)
            print(f"  ✓ BC sauvegardé: {bc_text_file.name}")
            
            # 3. Traiter chaque JSON associé
            for json_idx, json_path in enumerate(expected_jsons, 1):
                print(f"  [{json_idx}/{len(expected_jsons)}] JSON: {json_path.name}...")
                
                # Détecter convention de nommage depuis le nom du fichier
                if json_idx == 1:  # Premier fichier seulement
                    filename_pattern = self._detect_filename_convention(json_path.name)
                    if filename_pattern:
                        patterns_detected["filename_convention"] = filename_pattern
                        print(f"    ✓ Convention détectée: {filename_pattern}")
                
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        expected_json = json.load(f)
                except Exception as e:
                    print(f"    ❌ Erreur lecture JSON: {e}")
                    continue
                
                # Détection automatique de patterns
                detected = self._detect_patterns(bc_text, expected_json)
                
                # Merge patterns
                for key in patterns_detected:
                    if key in detected:
                        # filename_convention est une string, pas un set
                        if key == "filename_convention":
                            if detected[key] and not patterns_detected[key]:
                                patterns_detected[key] = detected[key]
                        elif isinstance(detected[key], (set, list)):
                            patterns_detected[key].update(detected[key])
                        else:
                            patterns_detected[key].add(detected[key])
                
                # Sauvegarde JSON
                json_file = client_dir / f"training_json_{json_idx}.json"
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(expected_json, f, indent=2, ensure_ascii=False)
                
                print(f"    ✓ JSON sauvegardé: {json_file.name}")
        
        # Mode classique: 1 BC = 1 JSON
        else:
            for idx, (bc_path, json_path) in enumerate(zip(bc_samples, expected_jsons), 1):
                print(f"[{idx}/{len(bc_samples)}] Traitement de {bc_path.name}...")
                
                # Détecter convention de nommage depuis le nom du fichier
                if idx == 1:  # Premier fichier seulement
                    filename_pattern = self._detect_filename_convention(json_path.name)
                    if filename_pattern:
                        patterns_detected["filename_convention"] = filename_pattern
                        print(f"  ✓ Convention détectée: {filename_pattern}")
                
                # 1. Extraction texte du BC
                bc_text = self._extract_text_from_pdf(bc_path)
                if not bc_text:
                    print(f"  ❌ Impossible d'extraire le texte")
                    continue
                
                print(f"  ✓ {len(bc_text)} caractères extraits")
                
                # 2. Chargement JSON attendu
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        expected_json = json.load(f)
                except Exception as e:
                    print(f"  ❌ Erreur lecture JSON: {e}")
                    continue
                
                # 3. Détection automatique de patterns
                detected = self._detect_patterns(bc_text, expected_json)
                
                # Merge patterns
                for key in patterns_detected:
                    if key in detected:
                        # filename_convention est une string, pas un set
                        if key == "filename_convention":
                            if detected[key] and not patterns_detected[key]:
                                patterns_detected[key] = detected[key]
                        elif isinstance(detected[key], (set, list)):
                            patterns_detected[key].update(detected[key])
                        else:
                            patterns_detected[key].add(detected[key])
                
                # 4. Sauvegarde dans patterns/CLIENT_XXX/
                bc_text_file = client_dir / f"training_bc_{idx}.txt"
                json_file = client_dir / f"training_json_{idx}.json"
                
                with open(bc_text_file, 'w', encoding='utf-8') as f:
                    f.write(bc_text)
                
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(expected_json, f, indent=2, ensure_ascii=False)
                
                print(f"  ✓ Sauvegardé: {bc_text_file.name} + {json_file.name}")
        
        # 5. Créer metadata.json
        metadata = self._create_metadata(
            client_id,
            len(bc_samples),
            patterns_detected
        )
        
        metadata_file = client_dir / "metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        print(f"\n{'='*60}")
        print(f"✅ ENTRAÎNEMENT TERMINÉ")
        print(f"{'='*60}")
        print(f"\n📊 PATTERNS DÉTECTÉS:")
        print(f"  • Origines: {', '.join(patterns_detected['origines'])}")
        print(f"  • Mots-clés: {', '.join(list(patterns_detected['mots_cles_detection'])[:5])}...")
        print(f"  • Codes articles: {', '.join(list(patterns_detected['codes_articles_typiques'])[:5])}...")
        print(f"\n💾 Patterns sauvegardés dans: {client_dir}")
        print(f"\n🚀 Usage en production:")
        print(f"   python ocr_smart.py --input BC.pdf --client-id {client_id}")
        
        return True
    
    def add_sample(
        self,
        client_id: str,
        bc_sample: Path,
        expected_json: Path
    ) -> bool:
        """
        Ajoute un exemple supplémentaire à un client existant
        """
        client_dir = self.patterns_base_dir / f"CLIENT_{client_id}"
        
        if not client_dir.exists():
            print(f"❌ Client {client_id} introuvable. Utilisez --train d'abord.")
            return False
        
        # Compter exemples existants
        existing = len(list(client_dir.glob("training_bc_*.txt")))
        next_idx = existing + 1
        
        print(f"\n🔧 Ajout d'un exemple au client {client_id}...")
        
        # Extraction texte
        bc_text = self._extract_text_from_pdf(bc_sample)
        if not bc_text:
            print(f"❌ Impossible d'extraire le texte")
            return False
        
        # Chargement JSON
        try:
            with open(expected_json, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
        except Exception as e:
            print(f"❌ Erreur lecture JSON: {e}")
            return False
        
        # Sauvegarde
        bc_text_file = client_dir / f"training_bc_{next_idx}.txt"
        json_file = client_dir / f"training_json_{next_idx}.json"
        
        with open(bc_text_file, 'w', encoding='utf-8') as f:
            f.write(bc_text)
        
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)
        
        # Mettre à jour metadata
        metadata_file = client_dir / "metadata.json"
        if metadata_file.exists():
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            metadata['nb_exemples'] = next_idx
            metadata['date_derniere_modification'] = datetime.now().isoformat()
            
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Exemple #{next_idx} ajouté pour {client_id}")
        print(f"💾 Total: {next_idx} exemple(s)")
        
        return True
    
    def _extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extrait le texte d'un PDF"""
        try:
            doc = fitz.open(pdf_path)
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            return text
        except Exception as e:
            print(f"❌ Erreur extraction PDF: {e}")
            return ""
    
    def _detect_filename_convention(self, filename: str) -> str:
        """
        Détecte la convention de nommage depuis un exemple de fichier
        
        Exemples supportés:
        - "02323-1631-1.json" → "{codeEtablissement}-{numCommande}-{index}"
        - "7992.json" → "{numCommande}"
        - "CLIENT_7992.json" → "{origine}_{numCommande}"
        - "7992_20240109.json" → "{numCommande}_{dateLivraison}"
        """
        filename = Path(filename).stem  # Retirer .json
        
        # Pattern: XXXXX-YYYY-Z (code établissement - num commande - index)
        if re.match(r'^\d{5}-\d+-\d+$', filename):
            return "{codeEtablissement}-{numCommande}-{index}"
        
        # Pattern: XXXXX-YYYY (code établissement - num commande)
        if re.match(r'^\d{5}-\d+$', filename):
            return "{codeEtablissement}-{numCommande}"
        
        # Pattern: CLIENT_YYYY-Z (origine - num commande - index)
        if re.match(r'^[A-Z]+_\d+-\d+$', filename):
            return "{origine}_{numCommande}-{index}"
        
        # Pattern: YYYY-Z (num commande - index)
        if re.match(r'^\d+-\d+$', filename):
            return "{numCommande}-{index}"
        
        # Pattern: YYYY_YYYYMMDD (num commande - date)
        if re.match(r'^\d+_\d{8}$', filename):
            return "{numCommande}_{dateLivraison}"
        
        # Pattern simple: YYYY (num commande uniquement)
        if re.match(r'^\d+$', filename):
            return "{numCommande}"
        
        # Pattern avec origine: CLIENT_YYYY
        if re.match(r'^[A-Z]+_\d+$', filename):
            return "{origine}_{numCommande}"
        
        return None
    
    def _detect_patterns(self, bc_text: str, expected_json: Dict) -> Dict[str, Any]:
        """
        Détecte automatiquement les patterns dans le BC
        Analyse le texte et le JSON pour identifier les caractéristiques
        """
        patterns = {
            "mots_cles_detection": set(),
            "format_dates": set(),
            "codes_articles_typiques": set(),
            "origines": set(),
            "filename_convention": None  # Nouvelle clé pour la convention de nommage
        }
        
        # Extraire origine du JSON
        try:
            if "commandes" in expected_json:
                for cmd in expected_json["commandes"]:
                    if "entete" in cmd and "origine" in cmd["entete"]:
                        patterns["origines"].add(cmd["entete"]["origine"])
        except:
            pass
        
        # Détecter mots-clés du BC (mots en MAJUSCULES, noms d'entreprise)
        keywords = re.findall(r'\b[A-Z][A-Z0-9\s\-]{3,}\b', bc_text)
        patterns["mots_cles_detection"].update(keywords[:10])  # Top 10
        
        # Détecter formats de dates
        date_patterns = [
            r'\d{2}/\d{2}/\d{4}',  # DD/MM/YYYY
            r'\d{2}\.\d{2}\.\d{4}',  # DD.MM.YYYY
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
        ]
        for pattern in date_patterns:
            if re.search(pattern, bc_text):
                patterns["format_dates"].add(pattern)
        
        # Détecter codes articles du JSON
        try:
            if "commandes" in expected_json:
                for cmd in expected_json["commandes"]:
                    if "detailCommande" in cmd and "produits" in cmd["detailCommande"]:
                        for prod in cmd["detailCommande"]["produits"]:
                            if "codeArticle" in prod:
                                code = prod["codeArticle"]
                                # Extraire préfixe (ex: F-, B-, P-)
                                prefix = re.match(r'^[A-Z]-', code)
                                if prefix:
                                    patterns["codes_articles_typiques"].add(prefix.group())
        except:
            pass
        
        return patterns
    
    def _create_metadata(
        self,
        client_id: str,
        nb_exemples: int,
        patterns: Dict
    ) -> Dict[str, Any]:
        """Crée le fichier metadata.json pour le client"""
        
        # Convertir sets en listes pour JSON
        patterns_serializable = {}
        for key, value in patterns.items():
            if isinstance(value, set):
                patterns_serializable[key] = sorted(list(value))
            else:
                patterns_serializable[key] = value
        
        return {
            "client_id": client_id,
            "origine": list(patterns["origines"])[0] if patterns["origines"] else client_id,
            "date_creation": datetime.now().isoformat(),
            "date_derniere_modification": datetime.now().isoformat(),
            "nb_exemples": nb_exemples,
            "patterns_detectes": patterns_serializable,
            "statistiques": {
                "nb_bc_traites": 0,
                "taux_reussite": None,
                "derniere_utilisation": None
            }
        }


def main():
    parser = argparse.ArgumentParser(
        description="🎓 Entraînement du système OCR auto-adaptatif",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples d'utilisation:

  # Entraîner un nouveau client avec 2 exemples (mode classique 1 BC = 1 JSON)
  python ocr_train.py \\
    --client-id NEWREST \\
    --bc-samples BC/newrest_1.pdf BC/newrest_2.pdf \\
    --expected-json training/newrest_1.json training/newrest_2.json

  # Mode multi-JSON: 1 BC génère plusieurs JSONs (ex: multi-dates)
  python ocr_train.py \\
    --client-id API \\
    --bc-samples examples/API/exemple_2_multi/bc.pdf \\
    --expected-json examples/API/exemple_2_multi/expected_1.json \\
                    examples/API/exemple_2_multi/expected_2.json \\
    --multi-json

  # Remplacer les patterns existants
  python ocr_train.py \\
    --client-id NEWREST \\
    --bc-samples BC/newrest_1.pdf \\
    --expected-json training/newrest_1.json \\
    --replace

  # Ajouter un exemple à un client existant
  python ocr_train.py \\
    --client-id NEWREST \\
    --add-sample BC/newrest_3.pdf \\
    --add-json training/newrest_3.json
        """
    )
    
    parser.add_argument(
        '--client-id',
        required=True,
        help="Identifiant unique du client (ex: NEWREST, API, SODEXO)"
    )
    
    parser.add_argument(
        '--bc-samples',
        nargs='+',
        type=Path,
        help="Liste des PDFs exemples pour entraînement"
    )
    
    parser.add_argument(
        '--expected-json',
        nargs='+',
        type=Path,
        help="Liste des JSONs attendus correspondants"
    )
    
    parser.add_argument(
        '--add-sample',
        type=Path,
        help="Ajouter un BC exemple à un client existant"
    )
    
    parser.add_argument(
        '--add-json',
        type=Path,
        help="JSON attendu pour l'exemple ajouté"
    )
    
    parser.add_argument(
        '--replace',
        action='store_true',
        help="Remplacer les patterns existants du client"
    )
    
    parser.add_argument(
        '--multi-json',
        action='store_true',
        help="Mode multi-JSON: 1 BC peut générer plusieurs JSONs (ex: multi-dates)"
    )
    
    parser.add_argument(
        '--patterns-dir',
        type=Path,
        default=Path("patterns"),
        help="Dossier de sauvegarde des patterns (défaut: patterns/)"
    )
    
    args = parser.parse_args()
    
    trainer = PatternTrainer(patterns_base_dir=args.patterns_dir)
    
    # Mode ajout d'exemple
    if args.add_sample and args.add_json:
        success = trainer.add_sample(
            client_id=args.client_id,
            bc_sample=args.add_sample,
            expected_json=args.add_json
        )
        exit(0 if success else 1)
    
    # Mode entraînement complet
    if not args.bc_samples or not args.expected_json:
        print("❌ Erreur: --bc-samples et --expected-json requis pour l'entraînement")
        parser.print_help()
        exit(1)
    
    success = trainer.train_client(
        client_id=args.client_id,
        bc_samples=args.bc_samples,
        expected_jsons=args.expected_json,
        replace=args.replace,
        multi_json_mode=args.multi_json
    )
    
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
