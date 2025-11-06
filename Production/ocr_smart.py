#!/usr/bin/env python3
"""
OCR Smart - Production avec auto-apprentissage
Détection automatique du client et chargement des patterns spécifiques
Fallback vers exemples génériques si client inconnu
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
import requests

import fitz  # PyMuPDF


# ---------- Configuration ----------
OLLAMA_URL_DEFAULT = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_NUM_CTX = 8192

# Règles métier fixes
FORCED_MODE_TRANSPORT = "L"
FORCED_ORIGINE_COMMANDE = "D"
FORCED_VERSION = "ACE"
FORCED_TYPE_COMMANDE = "220"


class SmartExtractor:
    """
    Extracteur intelligent avec auto-apprentissage
    - Détecte automatiquement le client
    - Charge les patterns spécifiques appris
    - Fallback vers exemples génériques si inconnu
    """
    
    def __init__(
        self,
        patterns_dir: Path,
        agences_file: Path,
        clients_file: Path,
        generic_examples_dir: Path = None,
        model: str = DEFAULT_MODEL,
        ollama_url: str = OLLAMA_URL_DEFAULT,
        debug: bool = False
    ):
        self.debug = debug  # Initialiser debug en premier
        self.patterns_dir = patterns_dir
        self.agences = self._load_reference_file(agences_file)
        self.clients = self._load_reference_file(clients_file)
        self.generic_examples_dir = generic_examples_dir or Path(".")
        self.model = model
        self.ollama_url = ollama_url
    
    def _load_reference_file(self, filepath: Path) -> List[str]:
        """Charge un fichier de référence"""
        if not filepath or not filepath.exists():
            if self.debug:
                print(f"⚠️  Fichier {filepath} introuvable")
            return []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    
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
    
    def detect_client(
        self,
        bc_text: str,
        client_id_hint: Optional[str] = None
    ) -> Optional[str]:
        """
        Détecte automatiquement le client à partir du texte du BC
        
        Args:
            bc_text: Texte extrait du BC
            client_id_hint: ID client forcé par l'utilisateur (optionnel)
        
        Returns:
            ID du client détecté ou None
        """
        
        # Si client forcé, le valider
        if client_id_hint:
            client_dir = self.patterns_dir / f"CLIENT_{client_id_hint}"
            if client_dir.exists():
                return client_id_hint
            else:
                print(f"⚠️  Client {client_id_hint} inconnu, détection automatique...")
        
        # Scanner tous les clients entraînés
        best_match = None
        best_score = 0
        
        for client_dir in self.patterns_dir.glob("CLIENT_*"):
            metadata_file = client_dir / "metadata.json"
            if not metadata_file.exists():
                continue
            
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                
                # Calculer score de correspondance
                score = 0
                patterns = metadata.get("patterns_detectes", {})
                
                # Vérifier mots-clés
                keywords = patterns.get("mots_cles_detection", [])
                for keyword in keywords:
                    if keyword in bc_text:
                        score += 1
                
                # Vérifier origine
                origine = metadata.get("origine", "")
                if origine and origine in bc_text:
                    score += 5  # Poids fort
                
                if score > best_score:
                    best_score = score
                    best_match = metadata.get("client_id")
            
            except Exception as e:
                if self.debug:
                    print(f"⚠️  Erreur lecture metadata {client_dir}: {e}")
                continue
        
        if best_match and best_score > 0:
            return best_match
        
        return None
    
    def load_client_patterns(self, client_id: str) -> List[Dict]:
        """
        Charge les patterns (exemples) spécifiques d'un client
        
        Returns:
            Liste des JSONs d'exemple pour ce client
        """
        client_dir = self.patterns_dir / f"CLIENT_{client_id}"
        
        if not client_dir.exists():
            if self.debug:
                print(f"⚠️  Dossier client {client_id} introuvable")
            return []
        
        patterns = []
        
        for json_file in sorted(client_dir.glob("training_json_*.json")):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    patterns.append(json.load(f))
                
                if self.debug:
                    print(f"  📚 Pattern chargé: {json_file.name}")
            except Exception as e:
                if self.debug:
                    print(f"⚠️  Erreur chargement {json_file}: {e}")
        
        return patterns
    
    def get_client_filename_convention(self, client_id: str) -> Optional[str]:
        """
        Récupère la convention de nommage du client depuis metadata.json
        
        Returns:
            Convention de nommage (ex: "{codeEtablissement}-{numCommande}-{index}")
            ou None si non définie
        """
        client_dir = self.patterns_dir / f"CLIENT_{client_id}"
        metadata_file = client_dir / "metadata.json"
        
        if not metadata_file.exists():
            return None
        
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            patterns = metadata.get("patterns_detectes", {})
            convention = patterns.get("filename_convention")
            
            if self.debug and convention:
                print(f"  📋 Convention de nommage: {convention}")
            
            return convention
        
        except Exception as e:
            if self.debug:
                print(f"⚠️  Erreur lecture convention: {e}")
            return None
    
    def load_generic_examples(self) -> List[Dict]:
        """Charge les exemples génériques (fallback)"""
        examples = []
        
        for json_file in self.generic_examples_dir.glob("exemple*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    examples.append(json.load(f))
                
                if self.debug:
                    print(f"  📚 Exemple générique: {json_file.name}")
            except Exception as e:
                if self.debug:
                    print(f"⚠️  Erreur chargement {json_file}: {e}")
        
        return examples
    
    def extract_with_llm(
        self,
        bc_text: str,
        examples: List[Dict],
        filename_convention: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extraction intelligente avec LLM
        Utilise les exemples fournis pour guider l'extraction
        
        Args:
            bc_text: Texte du BC
            examples: Liste des JSONs d'exemple
            filename_convention: Convention de nommage pour construire numCommande composite
        """
        
        if not examples:
            raise RuntimeError("Aucun exemple disponible pour l'extraction")
        
        # Prendre le premier exemple comme référence de structure
        example_json = examples[0]
        
        # Simplifier l'exemple pour éviter surcharge
        example_str = json.dumps(example_json, indent=2, ensure_ascii=False)
        if len(example_str) > 2000:
            # Tronquer si trop long
            example_str = example_str[:2000] + "\n  ...\n}"
        
        system = """Tu es un expert en extraction de données de bons de commande.
Tu dois extraire les informations et générer un JSON qui correspond EXACTEMENT à la structure de l'exemple fourni.

Règles STRICTES:
1. La structure doit être IDENTIQUE à l'exemple (mêmes champs, même ordre)
2. NE PAS ajouter de champs qui ne sont pas dans l'exemple
3. NE PAS retirer de champs présents dans l'exemple
4. Les dates au format YYYYMMDD (int) - ATTENTION: Année sur 4 chiffres, Mois sur 2, Jour sur 2
5. Les quantités en float avec 3 décimales (ex: 1.000)
6. Respecter EXACTEMENT les types de données (string, int, float)
7. Pour les champs vides, utiliser "" (string vide) ou null selon l'exemple
8. Pour "codeEtablissement", utiliser le CODE NUMÉRIQUE (ex: "02323"), PAS le nom de ville
9. Pour "origine" et "codeFournisseur", utiliser UNIQUEMENT les valeurs des listes de référence"""

        # Préparer les listes de référence
        ref_clients = "\n".join(f"  - {c}" for c in self.clients) if self.clients else "  (aucun)"
        ref_agences = "\n".join(f"  - {a}" for a in self.agences) if self.agences else "  (aucun)"

        user_prompt = f"""EXEMPLE DE STRUCTURE ATTENDUE (à copier EXACTEMENT):
{example_str}

ATTENTION PARTICULIÈRE:
- Pour "codeEtablissement": Utiliser le CODE NUMÉRIQUE à 5 chiffres (ex: "02323", "01142", "02313"), PAS le nom de ville
- Pour "codeFournisseur": Utiliser le NOM DE LA VILLE du fournisseur/expéditeur (ex: "CHAPONNAY", "CHALETTE"), PAS le code numérique
- Pour "dateCommande": Format YYYYMMDD (Année-Mois-Jour), ex: 20240214 = 14 février 2024
- Pour "dateLivraison": Format YYYYMMDD (Année-Mois-Jour), ex: 20240219 = 19 février 2024
- Pour "heureCommande": Format HHMMSS (Heure-Minute-Seconde), ex: "143000" = 14h30
- Pour "quantite": Toujours en float avec 3 décimales, ex: 3.000, 10.000, 1.500
- Pour "numCommande" et "idCommande": Format "codeEtablissement-numeroCommande" (ex: si codeEtablissement="910956" et numero="1435312", alors numCommande="910956-1435312")
- Pour les produits:
  * "codeArticle": Cherche d'abord dans la colonne "CodeRef" du tableau. Si absent, cherche le nombre entre PARENTHÈSES à la fin du libellé, ex: dans "PRODUIT#488(150508)", codeArticle="150508"
  * "codeArticlePerso": Cherche le nombre après le DIÈSE # dans le libellé, ex: dans "PRODUIT#488(150508)", codeArticlePerso="488"
  * Si un code n'est pas trouvé, utilise "" (chaîne vide)
- **SÉPARATION PAR DATE DE LIVRAISON**: Si le BC contient plusieurs sections "Livraison au : DATE", crée UN objet commande séparé pour CHAQUE date avec UNIQUEMENT les produits de cette section.
- NE PAS ajouter de champs supplémentaires comme "unite", "prixUnitaire", "consommation", etc.

LISTES DE RÉFÉRENCE (à utiliser pour validation):

Clients autorisés (pour "origine" - NOM DU CLIENT qui commande):
{ref_clients}

Villes/Agences autorisées avec codes postaux (format: VILLE, CODE_POSTAL):
{ref_agences}

INSTRUCTIONS IMPORTANTES:
- "codeFournisseur": Cherche la VILLE du fournisseur/expéditeur dans le BC. Compare cette ville avec la liste ci-dessous pour trouver la correspondance exacte (ignore la casse et les accents). Utilise le nom de ville EXACTEMENT comme dans la liste.
- "codePostal": Une fois la ville identifiée, utilise le CODE POSTAL qui apparaît APRÈS LA VIRGULE sur la même ligne dans la liste ci-dessus. Exemple: si tu trouves "LONGUEIL" dans le BC, cherche "LONGUEIL, XXXXX" dans la liste et utilise XXXXX comme codePostal.
- "codeEtablissement": Cherche dans le bon de commande selon le format du client (exemples: "Code site Frns: COR022", "Code client: 12345", code numérique, etc.). Utilise EXACTEMENT le même format que dans l'exemple JSON fourni.

TEXTE DU BON DE COMMANDE À TRAITER:
{bc_text[:20000]}

INSTRUCTIONS FINALES:
1. Génère le JSON en suivant EXACTEMENT la même structure que l'exemple
2. Utilise UNIQUEMENT les champs présents dans l'exemple
3. Pour "codeEtablissement", suis le FORMAT de l'exemple (alphanumérique ou numérique selon le client)
4. Pour "codeFournisseur", cherche le nom de la ville d'où provient la commande (fournisseur/expéditeur)
5. Pour "origine", utilise UNIQUEMENT les valeurs de la liste de référence ci-dessus
6. **IMPORTANT: Extraie TOUS les produits présents dans le bon de commande, du premier au dernier, sans exception**
7. **CODES ARTICLES**: Pour chaque produit, cherche le codeArticle dans la colonne "CodeRef" du tableau. Si cette colonne existe, utilise-la en priorité.
8. **SÉPARATION DES COMMANDES**: Si le BC contient plusieurs sections avec des dates de livraison différentes (ex: "Livraison au : lundi 14 avr. 2025", puis "Livraison au : lundi 05 mai 2025"), crée UN objet commande DISTINCT pour CHAQUE date, en incluant UNIQUEMENT les produits listés sous cette date.
9. Vérifie les formats de dates: YYYYMMDD (année complète sur 4 chiffres)
10. Vérifie que les quantités sont en float avec décimales (ex: 3.0, pas 3)
11. Continue jusqu'à ce que TOUS les produits soient extraits, ne t'arrête pas avant la fin de la liste"""

        if self.debug:
            print(f"\n[DEBUG] Prompt LLM ({len(user_prompt)} chars)")
            print(f"[DEBUG] Modèle: {self.model}")
        
        # Appel LLM
        llm_response = self._call_llm(system, user_prompt)
        
        # Validation et correction structure avec convention de nommage
        validated = self._validate_and_fix_structure(
            llm_response, 
            example_json,
            filename_convention
        )
        
        return validated
    
    def _call_llm(self, system: str, user_prompt: str) -> Dict[str, Any]:
        """Appelle le LLM"""
        payload = {
            "model": self.model,
            "system": system,
            "prompt": user_prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.0,
                "num_ctx": DEFAULT_NUM_CTX,
                "num_predict": 16384,  # Augmenter encore plus pour les BCs avec beaucoup de produits
            }
        }
        
        try:
            r = requests.post(self.ollama_url, json=payload, timeout=600)
            r.raise_for_status()
            
            data = r.json()
            raw = (data.get("response") or "").strip()
            
            if not raw:
                raise RuntimeError("LLM a retourné une réponse vide")
            
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
        
        # Chercher le JSON principal
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return match.group(0)
        
        return raw
    
    def _validate_and_fix_structure(
        self,
        llm_json: Dict,
        example_json: Dict,
        filename_convention: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Valide et corrige la structure du JSON généré
        Force la conformité avec l'exemple
        
        Args:
            llm_json: JSON retourné par le LLM
            example_json: JSON d'exemple
            filename_convention: Convention de nommage (ex: "{codeEtablissement}-{numCommande}-{index}")
        """
        
        # Si pas de clé "commandes", l'ajouter
        if "commandes" not in llm_json:
            llm_json = {"commandes": [llm_json]}
        
        # Déterminer les champs autorisés depuis l'exemple AVEC ORDRE PRÉSERVÉ
        example_produit_fields = []
        if "commandes" in example_json and len(example_json["commandes"]) > 0:
            first_cmd = example_json["commandes"][0]
            if "detailCommande" in first_cmd and "produits" in first_cmd["detailCommande"]:
                if len(first_cmd["detailCommande"]["produits"]) > 0:
                    # Utiliser list() au lieu de set() pour préserver l'ordre
                    example_produit_fields = list(first_cmd["detailCommande"]["produits"][0].keys())
        
        # Valider chaque commande
        for index, cmd in enumerate(llm_json["commandes"], start=1):
            # Forcer structure entete
            if "entete" not in cmd:
                cmd["entete"] = {}
            
            entete = cmd["entete"]
            
            # Construire numCommande et idCommande selon la convention
            if filename_convention:
                # Extraire les valeurs de base
                code_etab = entete.get("codeEtablissement", "")
                num_cmd_base = entete.get("numCommande", "")
                
                # Si la convention utilise le format composite
                if "{codeEtablissement}" in filename_convention and "{numCommande}" in filename_convention and "{index}" in filename_convention:
                    # Construire le format composite: codeEtablissement-numCommande-index
                    if code_etab and num_cmd_base:
                        # Nettoyer num_cmd_base: si c'est déjà un composite, extraire juste le numéro
                        # Sinon garder tel quel
                        if "-" in str(num_cmd_base):
                            # Format potentiel: "XXXX-7992-Y" ou "7992-Y" → extraire 7992
                            parts = str(num_cmd_base).split("-")
                            # Prendre la partie qui ressemble à un numéro (sans le code établissement ni l'index)
                            num_cmd_clean = parts[1] if len(parts) >= 3 else parts[0]
                        else:
                            # C'est déjà le numéro pur (ex: "7992")
                            num_cmd_clean = str(num_cmd_base)
                        
                        # Construire: codeEtablissement-numCommande-index
                        composite_id = f"{code_etab}-{num_cmd_clean}-{index}"
                        entete["numCommande"] = composite_id
                        entete["idCommande"] = composite_id
            
            # Forcer heureCommande à l'heure actuelle si null ou absent
            if not entete.get("heureCommande"):
                from datetime import datetime
                now = datetime.now()
                entete["heureCommande"] = now.strftime("%H%M%S")
            else:
                # S'assurer que heureCommande est bien une string
                entete["heureCommande"] = str(entete["heureCommande"])
            
            # Forcer champs obligatoires (écraser même si vides)
            entete["modeTransport"] = FORCED_MODE_TRANSPORT
            entete["typeCommande"] = FORCED_TYPE_COMMANDE
            entete["origineCommande"] = FORCED_ORIGINE_COMMANDE
            entete["version"] = FORCED_VERSION
            
            # Forcer structure detailCommande
            if "detailCommande" not in cmd:
                cmd["detailCommande"] = {"produits": [], "nbLignes": 0}
            
            detail = cmd["detailCommande"]
            
            if "produits" not in detail:
                detail["produits"] = []
            
            # Nettoyer les produits: ne garder que les champs de l'exemple
            if example_produit_fields:
                cleaned_produits = []
                for produit in detail["produits"]:
                    # Créer un nouveau produit avec uniquement les champs autorisés
                    cleaned_produit = {}
                    for field in example_produit_fields:
                        value = produit.get(field, "" if field == "commentaire" else None)
                        # Normaliser les quantités avec 3 décimales
                        if field == "quantite" and value is not None:
                            try:
                                value = float(value)
                            except (ValueError, TypeError):
                                value = 0.0
                        cleaned_produit[field] = value
                    cleaned_produits.append(cleaned_produit)
                detail["produits"] = cleaned_produits
            
            # Mettre à jour nbLignes
            detail["nbLignes"] = len(detail["produits"])
        
        return llm_json
    
    def process_bc(
        self,
        bc_path: Path,
        client_id_hint: Optional[str] = None
    ) -> tuple[Dict[str, Any], Optional[str], Optional[str]]:
        """
        Traite un BC avec détection automatique du client
        
        Args:
            bc_path: Chemin vers le BC PDF
            client_id_hint: ID client forcé (optionnel)
        
        Returns:
            Tuple (JSON extrait, client_id détecté, convention de nommage)
        """
        
        print(f"\n{'='*60}")
        print(f"🔍 TRAITEMENT: {bc_path.name}")
        print(f"{'='*60}\n")
        
        # 1. Extraction texte
        print("[1/4] Extraction du texte...")
        bc_text = self.extract_text_from_pdf(bc_path)
        
        if not bc_text:
            raise RuntimeError("Impossible d'extraire le texte du BC")
        
        print(f"  ✓ {len(bc_text)} caractères extraits")
        
        # 2. Détection client
        print("[2/4] Détection du client...")
        client_id = self.detect_client(bc_text, client_id_hint)
        
        filename_convention = None
        
        if client_id:
            print(f"  ✓ Client détecté: {client_id}")
            examples = self.load_client_patterns(client_id)
            filename_convention = self.get_client_filename_convention(client_id)
            
            if examples:
                print(f"  📚 {len(examples)} pattern(s) spécifique(s) chargé(s)")
            else:
                print(f"  ⚠️  Aucun pattern, fallback exemples génériques")
                examples = self.load_generic_examples()
        else:
            print(f"  ⚠️  Client inconnu, utilisation exemples génériques")
            examples = self.load_generic_examples()
        
        if not examples:
            raise RuntimeError("Aucun exemple disponible (ni spécifique ni générique)")
        
        # 3. Extraction LLM
        print("[3/4] Extraction avec LLM...")
        print(f"  🤖 Modèle: {self.model}")
        
        result = self.extract_with_llm(bc_text, examples, filename_convention)
        
        print(f"  ✓ Extraction terminée")
        
        # 4. Mise à jour statistiques
        if client_id:
            self._update_client_stats(client_id, success=True)
        
        print("[4/4] ✅ Traitement terminé\n")
        
        return result, client_id, filename_convention
    
    def _update_client_stats(self, client_id: str, success: bool):
        """Met à jour les statistiques d'utilisation du client"""
        client_dir = self.patterns_dir / f"CLIENT_{client_id}"
        metadata_file = client_dir / "metadata.json"
        
        if not metadata_file.exists():
            return
        
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            stats = metadata.get("statistiques", {})
            stats["nb_bc_traites"] = stats.get("nb_bc_traites", 0) + 1
            stats["derniere_utilisation"] = datetime.now().isoformat()
            
            # Calculer taux de réussite (simplifié)
            if success:
                current_rate = stats.get("taux_reussite", 1.0) or 1.0
                stats["taux_reussite"] = current_rate
            
            metadata["statistiques"] = stats
            
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        except Exception as e:
            if self.debug:
                print(f"⚠️  Erreur màj stats: {e}")


def generate_filename(
    convention: Optional[str],
    commande: Dict[str, Any],
    index: int,
    client_id: Optional[str] = None
) -> str:
    """
    Génère le nom de fichier selon la convention du client
    
    Args:
        convention: Convention de nommage (ex: "{codeEtablissement}-{numCommande}-{index}")
        commande: Objet commande contenant l'entête
        index: Index de la commande (1, 2, 3...)
        client_id: ID du client (pour certaines conventions)
    
    Returns:
        Nom de fichier généré (ex: "02313-7992-1.json")
    """
    entete = commande.get("entete", {})
    
    # Valeurs par défaut
    code_etab = entete.get("codeEtablissement", "UNKNOWN")
    num_cmd_full = entete.get("numCommande", "UNKNOWN")
    date_liv = entete.get("dateLivraison", "")
    origine = entete.get("origine", client_id or "UNKNOWN")
    
    # Si numCommande est au format composite (ex: "02313-7992-1"), extraire juste le numéro
    # Sinon, le garder tel quel
    if "-" in str(num_cmd_full):
        parts = str(num_cmd_full).split("-")
        if len(parts) >= 2:
            # Format: code-num-index ou code-num, prendre la partie numérique du milieu
            num_cmd = parts[-2] if len(parts) == 3 else parts[-1]
        else:
            num_cmd = str(num_cmd_full)
    else:
        num_cmd = str(num_cmd_full)
    
    # Si pas de convention, utiliser numCommande tel quel (déjà au bon format)
    if not convention:
        # Si déjà au format composite, utiliser directement
        if "-" in str(num_cmd_full) and str(code_etab) in str(num_cmd_full):
            return f"{num_cmd_full}.json"
        else:
            return f"{code_etab}-{num_cmd}-{index}.json"
    
    # Si la convention produit un format composite et que numCommande est déjà composite,
    # utiliser numCommande directement
    if "{codeEtablissement}" in convention and "{numCommande}" in convention and "{index}" in convention:
        # numCommande contient déjà le format complet
        return f"{num_cmd_full}.json"
    
    # Sinon, construire selon la convention
    filename = convention
    filename = filename.replace("{codeEtablissement}", str(code_etab))
    filename = filename.replace("{numCommande}", num_cmd)
    filename = filename.replace("{index}", str(index))
    filename = filename.replace("{dateLivraison}", str(date_liv))
    filename = filename.replace("{origine}", str(origine))
    
    # Ajouter .json si pas déjà présent
    if not filename.endswith(".json"):
        filename += ".json"
    
    return filename


def save_results(
    result: Dict[str, Any],
    out_dir: Path,
    filename_convention: Optional[str] = None,
    client_id: Optional[str] = None,
    debug: bool = False
):
    """
    Sauvegarde les résultats JSON en utilisant la convention de nommage du client
    
    Args:
        result: Résultat de l'extraction
        out_dir: Dossier de sortie
        filename_convention: Convention de nommage (ex: "{codeEtablissement}-{numCommande}-{index}")
        client_id: ID du client
        debug: Mode debug
    """
    
    # Classe personnalisée pour formater les floats avec 3 décimales
    class DecimalEncoder(json.JSONEncoder):
        def encode(self, obj):
            if isinstance(obj, float):
                return format(obj, '.3f')
            return super().encode(obj)
        
        def iterencode(self, obj, _one_shot=False):
            """Encode JSON avec formatage spécial des floats"""
            for chunk in super().iterencode(obj, _one_shot):
                yield chunk
    
    out_dir.mkdir(parents=True, exist_ok=True)
    
    if "commandes" not in result:
        print("⚠️  Structure JSON invalide, pas de clé 'commandes'")
        return
    
    nb_files = 0
    
    for index, commande in enumerate(result["commandes"], start=1):
        # Générer nom de fichier selon convention
        filename = generate_filename(filename_convention, commande, index, client_id)
        filepath = out_dir / filename
        
        # Envelopper dans structure commandes
        output = {"commandes": [commande]}
        
        # Convertir manuellement pour avoir 3 décimales sur les quantités
        output_str = json.dumps(output, indent=2, ensure_ascii=False)
        # Utiliser une regex pour formater les quantités
        import re
        output_str = re.sub(
            r'"quantite":\s*(-?\d+\.?\d*)',
            lambda m: f'"quantite": {float(m.group(1)):.3f}',
            output_str
        )
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(output_str)
        
        # Infos produits
        entete = commande.get("entete", {})
        date_liv = entete.get("dateLivraison", "")
        detail = commande.get("detailCommande", {})
        produits = detail.get("produits", [])
        
        print(f"  ✅ {filename} → {len(produits)} produit(s), livraison: {date_liv}")
        nb_files += 1
    
    return nb_files


def main():
    parser = argparse.ArgumentParser(
        description="🧠 OCR Smart - Production avec auto-apprentissage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples d'utilisation:

  # Traitement avec détection automatique du client
  python ocr_smart.py --input BC/nouveau_bc.pdf --out-dir resultats/

  # Forcer un client spécifique
  python ocr_smart.py \\
    --input BC/nouveau_bc.pdf \\
    --client-id NEWREST \\
    --out-dir resultats/

  # Mode debug
  python ocr_smart.py --input BC/bc.pdf --out-dir resultats/ --debug
        """
    )
    
    parser.add_argument(
        '--input',
        type=Path,
        required=True,
        help="Chemin vers le BC PDF à traiter"
    )
    
    parser.add_argument(
        '--out-dir',
        type=Path,
        default=Path("resultats"),
        help="Dossier de sortie pour les JSONs (défaut: resultats/)"
    )
    
    parser.add_argument(
        '--client-id',
        help="Forcer un client spécifique (optionnel)"
    )
    
    parser.add_argument(
        '--patterns-dir',
        type=Path,
        default=Path("patterns"),
        help="Dossier des patterns appris (défaut: patterns/)"
    )
    
    parser.add_argument(
        '--agences-file',
        type=Path,
        default=Path("refs/agencesPAP.txt"),
        help="Fichier des agences"
    )
    
    parser.add_argument(
        '--clients-file',
        type=Path,
        default=Path("refs/clients.txt"),
        help="Fichier des clients"
    )
    
    parser.add_argument(
        '--model',
        default=DEFAULT_MODEL,
        help=f"Modèle LLM à utiliser (défaut: {DEFAULT_MODEL})"
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help="Mode debug verbeux"
    )
    
    args = parser.parse_args()
    
    if not args.input.exists():
        print(f"❌ Fichier introuvable: {args.input}")
        exit(1)
    
    # Créer extracteur
    extractor = SmartExtractor(
        patterns_dir=args.patterns_dir,
        agences_file=args.agences_file,
        clients_file=args.clients_file,
        generic_examples_dir=Path("."),
        model=args.model,
        debug=args.debug
    )
    
    try:
        # Traiter BC
        result, client_id, filename_convention = extractor.process_bc(
            bc_path=args.input,
            client_id_hint=args.client_id
        )
        
        # Sauvegarder avec convention de nommage
        print("📦 Génération des fichiers JSON...")
        nb_files = save_results(
            result,
            args.out_dir,
            filename_convention=filename_convention,
            client_id=client_id,
            debug=args.debug
        )
        
        print(f"\n{'='*60}")
        print(f"✅ SUCCÈS: {nb_files} fichier(s) généré(s)")
        print(f"{'='*60}")
        
    except Exception as e:
        print(f"\n{'='*60}")
        print(f"❌ ERREUR: {e}")
        print(f"{'='*60}")
        
        if args.debug:
            import traceback
            traceback.print_exc()
        
        exit(1)


if __name__ == "__main__":
    main()
