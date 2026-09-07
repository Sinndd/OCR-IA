#!/usr/bin/env python3
"""
Pipeline Complet OCR → LLM → JSON avec RAG et Auto-apprentissage

Ce script unifie toutes les étapes:
1. Upload PDF/HTML/TXT
2. OCR → Extraction texte
3. RAG → Recherche d'exemples similaires
4. LLM → Génération JSON structuré
5. Validation → Feedback utilisateur
6. Correction → Ajout à la base RAG + données fine-tuning

Prérequis:
    pip install pymupdf requests sentence-transformers chromadb

Usage:
    python pipeline_ocr.py --file document.pdf       # Extraction complète
    python pipeline_ocr.py --batch dossier/          # Traitement batch
    python pipeline_ocr.py --interactive             # Mode interactif
    python pipeline_ocr.py --server                  # Mode API REST
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import hashlib
import time

# Ajouter le dossier parent au path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configuration
BASE_DIR = Path(__file__).parent.parent
PATTERNS_DIR = BASE_DIR / "patterns"
TRAINING_DIR = BASE_DIR / "training"
OUTPUT_DIR = BASE_DIR / "resultats"
RAG_DIR = TRAINING_DIR / "rag"
VECTOR_DB_DIR = RAG_DIR / "vectordb"

# Imports locaux (après sys.path)
try:
    from training.rag_system import DocumentStore, RAGExtractor
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False
    print("⚠️ Module RAG non disponible")


class TextExtractor:
    """Extrait le texte de différents formats de fichiers"""
    
    @staticmethod
    def extract(file_path: Path) -> str:
        """Extrait le texte d'un fichier (PDF, HTML, TXT)"""
        suffix = file_path.suffix.lower()
        
        if suffix == '.pdf':
            return TextExtractor._extract_pdf(file_path)
        elif suffix in ['.html', '.htm']:
            return TextExtractor._extract_html(file_path)
        elif suffix == '.txt':
            return TextExtractor._extract_txt(file_path)
        else:
            print(f"⚠️ Format non supporté: {suffix}")
            return ""
    
    @staticmethod
    def _extract_pdf(file_path: Path) -> str:
        """Extrait le texte d'un PDF"""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            return text
        except Exception as e:
            print(f"Erreur extraction PDF: {e}")
            return ""
    
    @staticmethod
    def _extract_html(file_path: Path) -> str:
        """Extrait le texte d'un HTML"""
        try:
            from html.parser import HTMLParser
            
            class TextHTMLParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.text = []
                
                def handle_data(self, data):
                    self.text.append(data.strip())
            
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                html = f.read()
            
            parser = TextHTMLParser()
            parser.feed(html)
            return ' '.join(filter(None, parser.text))
        except Exception as e:
            print(f"Erreur extraction HTML: {e}")
            return ""
    
    @staticmethod
    def _extract_txt(file_path: Path) -> str:
        """Lit un fichier texte"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            print(f"Erreur lecture TXT: {e}")
            return ""


class LLMClient:
    """Client pour appeler le LLM (Ollama)"""
    
    def __init__(self, model: str = "qwen2.5:7b", url: str = "http://localhost:11434/api/generate"):
        self.model = model
        self.url = url
    
    def generate(self, prompt: str, temperature: float = 0.1, max_tokens: int = 4096) -> str:
        """Génère une réponse du LLM"""
        import requests
        
        try:
            response = requests.post(
                self.url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_ctx": 8192,
                        "num_predict": max_tokens
                    }
                },
                timeout=180
            )
            
            if response.status_code == 200:
                return response.json().get("response", "")
            else:
                print(f"⚠️ Erreur LLM ({response.status_code}): {response.text[:200]}")
                return ""
        except requests.exceptions.ConnectionError:
            print("Ollama non accessible. Lancez: ollama serve")
            return ""
        except Exception as e:
            print(f"Erreur LLM: {e}")
            return ""
    
    def is_available(self) -> bool:
        """Vérifie si le LLM est disponible"""
        import requests
        try:
            response = requests.get(self.url.replace("/api/generate", "/api/tags"), timeout=5)
            return response.status_code == 200
        except:
            return False


class OCRPipeline:
    """Pipeline complet OCR → LLM → JSON avec RAG"""
    
    def __init__(
        self,
        use_rag: bool = True,
        model: str = "qwen2.5:7b",
        debug: bool = False
    ):
        self.debug = debug
        self.use_rag = use_rag and RAG_AVAILABLE
        
        # LLM
        self.llm = LLMClient(model=model)
        
        # RAG
        self.rag_store = None
        self.rag_extractor = None
        if self.use_rag:
            try:
                self.rag_store = DocumentStore(VECTOR_DB_DIR)
                self.rag_extractor = RAGExtractor(self.rag_store, llm_model=model)
                print(f"RAG activé ({self.rag_store.get_stats().get('total_documents', 0)} documents)")
            except Exception as e:
                print(f"⚠️ RAG désactivé: {e}")
                self.use_rag = False
        
        # Stats
        self.stats = {
            "processed": 0,
            "success": 0,
            "errors": 0,
            "corrections": 0
        }
    
    def process_file(self, file_path: Path) -> Dict:
        """
        Traite un fichier complet: OCR → RAG → LLM → JSON
        
        Returns:
            Dict avec les clés: success, result, text, examples_used, processing_time
        """
        start_time = time.time()
        result = {
            "success": False,
            "file": str(file_path),
            "result": {},
            "text": "",
            "examples_used": [],
            "processing_time": 0
        }
        
        print(f"\n{'='*60}")
        print(f"📄 TRAITEMENT: {file_path.name}")
        print(f"{'='*60}")
        
        # 1. Extraction du texte
        print("\n1️⃣ Extraction du texte...")
        text = TextExtractor.extract(file_path)
        
        if not text:
            print("Échec de l'extraction du texte")
            self.stats["errors"] += 1
            return result
        
        result["text"] = text
        print(f"   {len(text)} caractères extraits")
        
        # 2. Extraction avec ou sans RAG
        if self.use_rag and self.rag_extractor:
            print("\n2️⃣ Extraction avec RAG...")
            extracted, examples = self.rag_extractor.extract_with_rag(text, top_k=3)
            result["examples_used"] = [
                {"client": ex["metadata"].get("client", "?"), "similarity": ex["similarity"]}
                for ex in examples
            ]
        else:
            print("\n2️⃣ Extraction sans RAG...")
            extracted = self._extract_without_rag(text)
        
        if not extracted:
            print("Échec de l'extraction JSON")
            self.stats["errors"] += 1
            return result
        
        result["result"] = extracted
        result["success"] = True
        
        # 3. Post-traitement (normalisation)
        print("\n3️⃣ Post-traitement...")
        result["result"] = self._post_process(extracted)
        
        # Stats
        self.stats["processed"] += 1
        self.stats["success"] += 1
        
        result["processing_time"] = time.time() - start_time
        print(f"\nExtraction réussie en {result['processing_time']:.1f}s")
        
        return result
    
    def _extract_without_rag(self, text: str) -> Dict:
        """Extraction directe sans RAG"""
        prompt = f"""Tu es un expert en extraction de données de bons de commande.

TEXTE DU BON DE COMMANDE:
{text[:6000]}

INSTRUCTIONS:
Extrait toutes les informations dans un JSON structuré avec:
- entete: origine (nom entreprise), codeEtablissement, codeFournisseur, numCommande, 
         dateCommande (format YYYYMMDD), dateLivraison (format YYYYMMDD),
         modeTransport ("L"), typeCommande ("220"), origineCommande ("D"), version ("ACE")
- detailCommande: 
    - produits: liste avec numLigne, codeArticle, libelle, quantite (nombre décimal)
    - nbLignes: nombre total de produits

Réponds UNIQUEMENT avec le JSON, sans explication."""

        response = self.llm.generate(prompt)
        return self._parse_json(response)
    
    def _parse_json(self, response: str) -> Dict:
        """Parse la réponse JSON du LLM"""
        try:
            # Chercher le JSON
            start = response.find('{')
            end = response.rfind('}') + 1
            
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except json.JSONDecodeError as e:
            if self.debug:
                print(f"⚠️ Erreur parsing: {e}")
        
        return {}
    
    def _post_process(self, data: Dict) -> Dict:
        """Normalise et complète les données extraites"""
        # Valeurs par défaut pour l'entête
        if "entete" in data:
            defaults = {
                "modeTransport": "L",
                "typeCommande": "220",
                "origineCommande": "D",
                "version": "ACE"
            }
            for key, value in defaults.items():
                if key not in data["entete"] or not data["entete"][key]:
                    data["entete"][key] = value
        
        # Normaliser les dates (YYYYMMDD)
        if "entete" in data:
            for date_field in ["dateCommande", "dateLivraison"]:
                if date_field in data["entete"]:
                    data["entete"][date_field] = self._normalize_date(data["entete"][date_field])
        
        # Compter les produits
        if "detailCommande" in data and "produits" in data["detailCommande"]:
            data["detailCommande"]["nbLignes"] = len(data["detailCommande"]["produits"])
            
            # Numéroter les lignes si nécessaire
            for i, prod in enumerate(data["detailCommande"]["produits"]):
                if "numLigne" not in prod:
                    prod["numLigne"] = i + 1
                
                # S'assurer que quantite est un nombre
                if "quantite" in prod:
                    try:
                        prod["quantite"] = float(prod["quantite"])
                    except:
                        prod["quantite"] = 0.0
        
        return data
    
    def _normalize_date(self, date_str: Any) -> Optional[int]:
        """Normalise une date au format YYYYMMDD"""
        if not date_str:
            return None
        
        date_str = str(date_str)
        
        # Déjà au bon format
        if len(date_str) == 8 and date_str.isdigit():
            return int(date_str)
        
        # Format DD/MM/YYYY
        import re
        match = re.match(r'(\d{2})/(\d{2})/(\d{4})', date_str)
        if match:
            d, m, y = match.groups()
            return int(f"{y}{m}{d}")
        
        # Format YYYY-MM-DD
        match = re.match(r'(\d{4})-(\d{2})-(\d{2})', date_str)
        if match:
            y, m, d = match.groups()
            return int(f"{y}{m}{d}")
        
        return None
    
    def save_result(self, result: Dict, output_dir: Path = None) -> Path:
        """Sauvegarde le résultat en JSON"""
        output_dir = output_dir or OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Générer le nom du fichier
        if result.get("result", {}).get("entete", {}).get("numCommande"):
            filename = f"{result['result']['entete']['numCommande']}.json"
        else:
            filename = f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        output_path = output_dir / filename
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result["result"], f, indent=2, ensure_ascii=False)
        
        print(f"💾 Résultat sauvegardé: {output_path}")
        return output_path
    
    def add_correction(self, text: str, corrected_json: Dict, client: str = "unknown"):
        """
        Ajoute une correction à la base RAG et aux données de fine-tuning
        """
        print(f"\n📝 Enregistrement de la correction...")
        
        # 1. Ajouter à RAG
        if self.use_rag and self.rag_extractor:
            self.rag_extractor.add_correction_to_rag(text, corrected_json, client)
        
        # 2. Ajouter aux données de fine-tuning
        self._save_training_pair(text, corrected_json, client)
        
        self.stats["corrections"] += 1
        print("Correction enregistrée")
    
    def _save_training_pair(self, text: str, expected_json: Dict, client: str):
        """Sauvegarde une paire d'entraînement"""
        client_dir = PATTERNS_DIR / f"CLIENT_{client}"
        client_dir.mkdir(parents=True, exist_ok=True)
        
        # Trouver le prochain numéro
        existing = list(client_dir.glob("training_bc_*.txt"))
        next_num = len(existing) + 1
        
        # Sauvegarder le texte
        bc_file = client_dir / f"training_bc_{next_num}.txt"
        with open(bc_file, 'w', encoding='utf-8') as f:
            f.write(text)
        
        # Sauvegarder le JSON
        json_file = client_dir / f"training_json_{next_num}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(expected_json, f, indent=2, ensure_ascii=False)
        
        print(f"  📄 Sauvegardé: {bc_file.name} + {json_file.name}")
    
    def process_batch(self, input_dir: Path, output_dir: Path = None) -> List[Dict]:
        """Traite tous les fichiers d'un dossier"""
        results = []
        
        files = list(input_dir.glob("*.pdf")) + \
                list(input_dir.glob("*.html")) + \
                list(input_dir.glob("*.htm")) + \
                list(input_dir.glob("*.txt"))
        
        print(f"\n📂 Traitement batch: {len(files)} fichiers")
        
        for file in files:
            result = self.process_file(file)
            if result["success"]:
                self.save_result(result, output_dir)
            results.append(result)
        
        # Résumé
        print(f"\n{'='*60}")
        print("📊 RÉSUMÉ DU TRAITEMENT BATCH")
        print(f"{'='*60}")
        print(f"  Traités: {self.stats['processed']}")
        print(f"  Réussis: {self.stats['success']}")
        print(f"  Erreurs: {self.stats['errors']}")
        
        return results
    
    def interactive_mode(self):
        """Mode interactif pour traitement et corrections"""
        print(f"\n{'='*60}")
        print("🎮 MODE INTERACTIF")
        print("Commandes: quit, stats, help")
        print(f"{'='*60}\n")
        
        while True:
            try:
                user_input = input("\n📄 Fichier à traiter (ou commande): ").strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() == 'quit':
                    print("👋 Au revoir!")
                    break
                
                if user_input.lower() == 'stats':
                    print(f"\n📊 Statistiques:")
                    print(f"  Traités: {self.stats['processed']}")
                    print(f"  Réussis: {self.stats['success']}")
                    print(f"  Erreurs: {self.stats['errors']}")
                    print(f"  Corrections: {self.stats['corrections']}")
                    continue
                
                if user_input.lower() == 'help':
                    print("\n📖 Commandes:")
                    print("  <fichier>  - Traite un fichier PDF/HTML/TXT")
                    print("  stats      - Affiche les statistiques")
                    print("  quit       - Quitte le mode interactif")
                    continue
                
                # Traiter le fichier
                file_path = Path(user_input)
                if not file_path.exists():
                    print(f"Fichier introuvable: {file_path}")
                    continue
                
                result = self.process_file(file_path)
                
                if result["success"]:
                    print(f"\n📤 Résultat:")
                    print(json.dumps(result["result"], indent=2, ensure_ascii=False))
                    
                    # Demander validation
                    save = input("\n💾 Sauvegarder? (o/n): ").strip().lower()
                    if save == 'o':
                        self.save_result(result)
                    
                    # Proposer correction
                    correct = input("✏️ Corriger? (o/n): ").strip().lower()
                    if correct == 'o':
                        print("📝 Entrez le JSON corrigé (finir par une ligne vide):")
                        lines = []
                        while True:
                            line = input()
                            if not line:
                                break
                            lines.append(line)
                        
                        try:
                            corrected = json.loads('\n'.join(lines))
                            client = input("👤 Client: ").strip() or "unknown"
                            self.add_correction(result["text"], corrected, client)
                        except json.JSONDecodeError:
                            print("JSON invalide")
                
            except KeyboardInterrupt:
                print("\n👋 Au revoir!")
                break
            except Exception as e:
                print(f"Erreur: {e}")


def main():
    parser = argparse.ArgumentParser(description="Pipeline OCR complet avec RAG")
    parser.add_argument('--file', type=str, help='Fichier à traiter')
    parser.add_argument('--batch', type=str, help='Dossier à traiter en batch')
    parser.add_argument('--output', type=str, help='Dossier de sortie')
    parser.add_argument('--interactive', action='store_true', help='Mode interactif')
    parser.add_argument('--no-rag', action='store_true', help='Désactive RAG')
    parser.add_argument('--model', type=str, default='qwen2.5:7b', help='Modèle LLM')
    parser.add_argument('--debug', action='store_true', help='Mode debug')
    
    args = parser.parse_args()
    
    # Vérifier que le LLM est disponible
    llm = LLMClient(model=args.model)
    if not llm.is_available():
        print("Ollama n'est pas accessible!")
        print("💡 Lancez: ollama serve")
        print("💡 Puis: ollama pull qwen2.5:7b")
        return
    
    # Créer le pipeline
    pipeline = OCRPipeline(
        use_rag=not args.no_rag,
        model=args.model,
        debug=args.debug
    )
    
    if args.file:
        file_path = Path(args.file)
        result = pipeline.process_file(file_path)
        
        if result["success"]:
            print(f"\n📤 Résultat:")
            print(json.dumps(result["result"], indent=2, ensure_ascii=False))
            
            output_dir = Path(args.output) if args.output else None
            pipeline.save_result(result, output_dir)
    
    elif args.batch:
        input_dir = Path(args.batch)
        output_dir = Path(args.output) if args.output else None
        pipeline.process_batch(input_dir, output_dir)
    
    elif args.interactive:
        pipeline.interactive_mode()
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
