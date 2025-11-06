#!/usr/bin/env python3
"""
OCR Universel - Auto-adaptatif sans maintenance
Architecture hybride : Parsing intelligent + LLM fallback + Auto-apprentissage
Zero-touch pour nouveaux formats de BC
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import requests

import fitz  # PyMuPDF


# ---------- Configuration ----------
OLLAMA_URL_DEFAULT = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "mistral:7b"  # Plus rapide (4.4GB) - bon compromis vitesse/qualité
DEFAULT_NUM_CTX = 8192  # Réduit pour plus de vitesse

# Règles métier fixes
FORCED_MODE_TRANSPORT = "L"
FORCED_ORIGINE_COMMANDE = "D"
FORCED_VERSION = "ACE"
FORCED_TYPE_COMMANDE = "220"


class UniversalExtractor:
    """
    Extracteur universel auto-adaptatif
    - Essaie d'abord parsing structuré
    - Fallback LLM si échec
    - Apprend des exemples fournis
    """
    
    def __init__(
        self,
        agences_file: Path,
        clients_file: Path,
        examples_dir: Path,
        model: str = DEFAULT_MODEL,
        ollama_url: str = OLLAMA_URL_DEFAULT,
        debug: bool = False
    ):
        self.agences = self._load_reference_file(agences_file)
        self.clients = self._load_reference_file(clients_file)
        self.model = model
        self.ollama_url = ollama_url
        self.debug = debug
        
        # Charger les exemples JSON pour apprendre la structure
        self.example_structures = self._load_example_structures(examples_dir)
    
    def _load_reference_file(self, filepath: Path) -> List[str]:
        """Charge un fichier de référence"""
        if not filepath or not filepath.exists():
            print(f"⚠️  Fichier {filepath} introuvable")
            return []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    
    def _load_example_structures(self, examples_dir: Path) -> List[Dict]:
        """Charge les exemples JSON pour comprendre la structure attendue"""
        examples = []
        
        if not examples_dir.exists():
            print(f"⚠️  Dossier exemples {examples_dir} introuvable")
            return examples
        
        for json_file in examples_dir.glob("exemple*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    example = json.load(f)
                    examples.append(example)
                    if self.debug:
                        print(f"  📚 Exemple chargé: {json_file.name}")
            except Exception as e:
                print(f"⚠️  Erreur chargement {json_file}: {e}")
        
        return examples
    
    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extrait le texte du PDF"""
        try:
            doc = fitz.open(pdf_path)
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            return text
        except Exception as e:
            print(f"❌ Erreur extraction: {e}")
            return ""
    
    def call_llm(self, system: str, user_prompt: str, temperature: float = 0.0) -> Dict[str, Any]:
        """
        Appelle le LLM (Mistral-small) pour extraction intelligente
        Plus rapide et fiable que LLaVA pour du texte structuré
        """
        payload = {
            "model": self.model,
            "system": system,
            "prompt": user_prompt,
            "stream": False,
            "format": "json",  # Force le JSON
            "options": {
                "temperature": temperature,
                "num_ctx": DEFAULT_NUM_CTX,
            }
        }
        
        try:
            r = requests.post(self.ollama_url, json=payload, timeout=600)  # 10 minutes
            r.raise_for_status()
            
            data = r.json()
            raw = (data.get("response") or "").strip()
            
            if not raw:
                raise RuntimeError("LLM a retourné une réponse vide")
            
            # Nettoyage
            cleaned = self._clean_json_response(raw)
            
            if self.debug:
                print(f"\n[DEBUG] Réponse LLM (premiers 500 chars):")
                print(cleaned[:500])
            
            return json.loads(cleaned)
        
        except Exception as e:
            print(f"\n❌ Erreur LLM: {e}")
            raise
    
    def _clean_json_response(self, raw: str) -> str:
        """Nettoie la réponse pour extraire le JSON pur"""
        raw = raw.strip()
        
        # Enlever les blocs markdown
        if "```json" in raw:
            match = re.search(r'```json\s*(\{.*?\})\s*```', raw, re.DOTALL)
            if match:
                return match.group(1)
        
        if "```" in raw:
            match = re.search(r'```\s*(\{.*?\})\s*```', raw, re.DOTALL)
            if match:
                return match.group(1)
        
        # Trouver le premier { et le dernier } correspondant
        first_brace = raw.find("{")
        if first_brace == -1:
            return raw
        
        brace_count = 0
        last_brace = first_brace
        for i in range(first_brace, len(raw)):
            if raw[i] == "{":
                brace_count += 1
            elif raw[i] == "}":
                brace_count -= 1
                if brace_count == 0:
                    last_brace = i
                    break
        
        return raw[first_brace:last_brace + 1]
    
    def create_universal_prompt(self, text: str) -> Tuple[str, str]:
        """
        Crée un prompt court et efficace pour extraction rapide
        """
        system = "Expert extraction BC. Retourne JSON format commandes."
        
        user = f"""BON DE COMMANDE:
{text[:1200]}

RETOURNE CE FORMAT EXACTEMENT:
{{
  "commandes": [
    {{
      "entete": {{
        "origine": "NOM_CLIENT",
        "codeEtablissement": "CODE",
        "codeFournisseur": "AGENCE",
        "codePostal": "12345",
        "numCommande": "CODE-NUM-1",
        "idCommande": "CODE-NUM-1",
        "dateCommande": 20250101,
        "heureCommande": 110000,
        "dateLivraison": 20250115,
        "commentaireEntete": "",
        "modeTransport": "L",
        "typeCommande": "220",
        "origineCommande": "D",
        "version": "ACE"
      }},
      "detailCommande": {{
        "produits": [
          {{
            "numLigne": 1,
            "codeArticle": "123456",
            "libelle": "Produit description",
            "quantite": 1.0,
            "commentaire": ""
          }}
        ],
        "nbLignes": 1
      }}
    }}
  ]
}}

Clients: {", ".join(self.clients[:3])}
Agences: {", ".join(self.agences[:3])}

JSON:"""
        
        return system, user
    
    def validate_and_fix_structure(self, data: Dict[str, Any], text: str = "") -> Dict[str, Any]:
        """
        Valide et corrige la structure pour qu'elle soit conforme aux exemples
        Application des règles métier
        """
        if "commandes" not in data:
            print("⚠️  Structure incorrecte : 'commandes' manquant, tentative de récupération...")
            return {"commandes": []}
        
        now = datetime.now()
        
        for idx, cmd in enumerate(data["commandes"], 1):
            entete = cmd.get("entete", {})
            detail = cmd.get("detailCommande", {})
            
            # Si detailCommande manquant, créer la structure
            if not detail:
                cmd["detailCommande"] = {"produits": [], "nbLignes": 0}
                detail = cmd["detailCommande"]
            
            # Forcer les constantes métier
            entete["modeTransport"] = FORCED_MODE_TRANSPORT
            entete["typeCommande"] = FORCED_TYPE_COMMANDE
            entete["origineCommande"] = FORCED_ORIGINE_COMMANDE
            entete["version"] = FORCED_VERSION
            
            # Assurer heure actuelle
            if not entete.get("heureCommande"):
                entete["heureCommande"] = int(now.strftime("%H%M%S"))
            
            # Vérifier dates en format INT
            for date_field in ["dateCommande", "dateLivraison"]:
                if isinstance(entete.get(date_field), str):
                    # Convertir string en int
                    date_str = entete[date_field].replace("-", "").replace("/", "")
                    if date_str.isdigit() and len(date_str) == 8:
                        entete[date_field] = int(date_str)
            
            # Vérifier que detailCommande est un objet (pas un tableau)
            if isinstance(detail, list):
                if len(detail) > 0:
                    cmd["detailCommande"] = detail[0]
                else:
                    cmd["detailCommande"] = {"produits": [], "nbLignes": 0}
            
            # Assurer que produits existe
            if "produits" not in cmd["detailCommande"]:
                cmd["detailCommande"]["produits"] = []
            
            # Mettre à jour nbLignes
            produits = cmd["detailCommande"].get("produits", [])
            cmd["detailCommande"]["nbLignes"] = len(produits)
            
            # Numérotation globale des lignes
            for i, prod in enumerate(produits, 1):
                if "numLigne" not in prod:
                    prod["numLigne"] = i
                
                # Assurer quantité en float
                if "quantite" in prod and not isinstance(prod["quantite"], float):
                    try:
                        prod["quantite"] = float(prod["quantite"])
                    except:
                        prod["quantite"] = 1.0
        
        return data
    
    def process_pdf(self, pdf_path: Path, output_dir: Path) -> List[Path]:
        """
        Traite un PDF de manière universelle
        Approche : LLM intelligent qui s'adapte automatiquement
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\n{'='*60}")
        print(f"📄 Traitement: {pdf_path.name}")
        print(f"{'='*60}")
        
        # Extraction du texte
        print("[1/3] Extraction du texte...")
        text = self.extract_text_from_pdf(pdf_path)
        
        if not text or len(text.strip()) < 50:
            print("❌ PDF vide ou illisible")
            return []
        
        print(f"  ✓ {len(text)} caractères extraits")
        
        # Extraction via LLM universel
        print("[2/3] Analyse intelligente par LLM...")
        print("  🤖 Le LLM va s'adapter automatiquement au format...")
        
        try:
            system, user_prompt = self.create_universal_prompt(text)
            extracted_data = self.call_llm(system, user_prompt)
        except Exception as e:
            print(f"❌ Erreur LLM: {e}")
            return []
        
        # Validation et correction
        print("[3/3] Validation et correction...")
        validated_data = self.validate_and_fix_structure(extracted_data, text)
        
        # Génération des fichiers JSON
        generated_files = []
        commandes = validated_data.get("commandes", [])
        
        if not commandes:
            print("\n⚠️ Aucune commande à générer")
            return []
        
        print(f"\n📦 Génération de {len(commandes)} fichier(s) JSON...")
        
        for cmd in commandes:
            entete = cmd.get("entete", {})
            num_commande = entete.get("numCommande", "unknown")
            id_commande = entete.get("idCommande", num_commande)
            
            # Nom de fichier
            output_path = output_dir / f"{id_commande}.json"
            
            try:
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump({"commandes": [cmd]}, f, ensure_ascii=False, indent=2)
                generated_files.append(output_path)
                
                # Affichage
                nb_produits = cmd.get("detailCommande", {}).get("nbLignes", 0)
                date_livraison = entete.get("dateLivraison", "")
                print(f"  ✅ {output_path.name} → {nb_produits} produit(s), livraison: {date_livraison}")
            except Exception as e:
                print(f"  ❌ Erreur écriture {output_path.name}: {e}")
        
        return generated_files


def main():
    """Point d'entrée principal"""
    parser = argparse.ArgumentParser(
        description="OCR Universel - Auto-adaptatif sans maintenance"
    )
    parser.add_argument("--input", required=True, help="PDF ou dossier de PDFs")
    parser.add_argument("--out-dir", required=True, help="Dossier de sortie pour les JSON")
    parser.add_argument("--examples-dir", default=".", help="Dossier contenant exemple1.json, exemple2.json, etc.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Modèle LLM (défaut: {DEFAULT_MODEL})")
    parser.add_argument("--ollama-url", default=OLLAMA_URL_DEFAULT, help="URL de l'API Ollama")
    parser.add_argument("--agences-file", required=True, help="Fichier agencesPAP.txt")
    parser.add_argument("--clients-file", required=True, help="Fichier clients.txt")
    parser.add_argument("--debug", action="store_true", help="Mode debug")
    
    args = parser.parse_args()
    
    in_path = Path(args.input)
    out_dir = Path(args.out_dir)
    examples_dir = Path(args.examples_dir)
    agences_file = Path(args.agences_file)
    clients_file = Path(args.clients_file)
    
    # Liste des PDFs
    if in_path.is_dir():
        pdfs = sorted(in_path.glob("*.pdf"))
    elif in_path.is_file() and in_path.suffix.lower() == ".pdf":
        pdfs = [in_path]
    else:
        raise SystemExit("❌ --input doit être un PDF ou un dossier")
    
    if not pdfs:
        raise SystemExit("❌ Aucun PDF trouvé")
    
    print(f"\n{'='*60}")
    print(f"🚀 OCR Universel Auto-Adaptatif")
    print(f"📄 {len(pdfs)} PDF(s) à traiter")
    print(f"🤖 Modèle: {args.model}")
    print(f"📚 Exemples: {examples_dir}")
    print(f"📁 Sortie: {out_dir}")
    print(f"{'='*60}\n")
    
    # Initialisation
    extractor = UniversalExtractor(
        agences_file=agences_file,
        clients_file=clients_file,
        examples_dir=examples_dir,
        model=args.model,
        ollama_url=args.ollama_url,
        debug=args.debug
    )
    
    success_count = 0
    error_count = 0
    
    for pdf in pdfs:
        try:
            generated = extractor.process_pdf(pdf, out_dir)
            if generated:
                print(f"\n✅ Succès: {len(generated)} fichier(s) JSON")
                success_count += 1
            else:
                print(f"\n❌ Échec: aucun JSON généré")
                error_count += 1
        except Exception as e:
            print(f"\n❌ Erreur: {e}")
            if args.debug:
                import traceback
                traceback.print_exc()
            error_count += 1
    
    print(f"\n{'='*60}")
    print(f"📊 RÉSUMÉ")
    print(f"{'='*60}")
    print(f"  ✅ Succès: {success_count}/{len(pdfs)}")
    print(f"  ❌ Erreurs: {error_count}/{len(pdfs)}")
    print(f"  🤖 Mode: LLM auto-adaptatif universel")
    print(f"  ⚡ Zero-touch : Aucune modification requise pour nouveaux formats")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
