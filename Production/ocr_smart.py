#!/usr/bin/env python3
"""
OCR Smart - Production avec auto-apprentissage OPTIMISÉ
+ Tri intelligent des exemples par similarité
+ Détection de similarité multi-critères
+ Cache de patterns généralisés
+ Prompts moins spécifiques pour plus de flexibilité
"""

import argparse
import json
import re
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from collections import Counter
from difflib import SequenceMatcher
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
    Extracteur intelligent avec auto-apprentissage OPTIMISÉ
    + Tri intelligent des exemples
    + Détection de similarité
    + Cache de patterns généralisés
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
        self.debug = debug
        self.patterns_dir = patterns_dir
        self.agences = self._load_reference_file(agences_file)
        self.clients = self._load_reference_file(clients_file)
        self.generic_examples_dir = generic_examples_dir or Path(".")
        self.model = model
        self.ollama_url = ollama_url
        
        # NOUVEAU: Cache de patterns généralisés
        self.patterns_cache = {}
        self.cache_file = patterns_dir / "patterns_cache.json"
        self._load_patterns_cache()
    
    def _load_patterns_cache(self):
        """Charge le cache des patterns généralisés"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.patterns_cache = json.load(f)
                if self.debug:
                    print(f"📦 Cache chargé: {len(self.patterns_cache)} patterns")
            except Exception as e:
                if self.debug:
                    print(f"⚠️  Erreur chargement cache: {e}")
                self.patterns_cache = {}
    
    def _save_patterns_cache(self):
        """Sauvegarde le cache des patterns"""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.patterns_cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            if self.debug:
                print(f"⚠️  Erreur sauvegarde cache: {e}")
    
    def _load_reference_file(self, filepath: Path) -> List[str]:
        """Charge un fichier de référence"""
        if not filepath or not filepath.exists():
            if self.debug:
                print(f"⚠️  Fichier {filepath} introuvable")
            return []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    
    def _compute_text_signature(self, text: str) -> str:
        """Calcule une signature du texte pour cache et similarité"""
        # Nettoyer et normaliser
        clean_text = re.sub(r'\s+', ' ', text.lower())
        clean_text = re.sub(r'\d+', 'N', clean_text)  # Remplacer nombres par N
        
        # Hash court
        return hashlib.md5(clean_text[:5000].encode()).hexdigest()[:16]
    
    def _extract_text_features(self, text: str) -> Dict[str, Any]:
        """
        Extrait les features caractéristiques d'un texte de BC
        Pour la détection de similarité
        """
        features = {
            "length": len(text),
            "has_table": bool(re.search(r'(Code\s+Ref|Référence|Désignation)', text, re.I)),
            "date_format": None,
            "number_density": len(re.findall(r'\d+', text)) / max(len(text), 1),
        }
        
        # Détecter format de date dominant
        if re.search(r'\d{2}/\d{2}/\d{4}', text):
            features["date_format"] = "dd/mm/yyyy"
        elif re.search(r'\d{4}-\d{2}-\d{2}', text):
            features["date_format"] = "yyyy-mm-dd"
        elif re.search(r'\d{2}\s+\w+\s+\d{4}', text, re.I):
            features["date_format"] = "dd month yyyy"
        
        # Mots-clés fréquents
        words = re.findall(r'\b[a-zàéèêë]{4,}\b', text.lower())
        features["top_keywords"] = [w for w, _ in Counter(words).most_common(10)]
        
        # Structure détectée
        features["has_header"] = bool(re.search(r'(expéditeur|destinataire|commande)', text[:1000], re.I))
        features["has_footer"] = bool(re.search(r'(total|signature|page)', text[-1000:], re.I))
        
        return features
    
    def _compute_similarity(self, features1: Dict, features2: Dict) -> float:
        """
        Calcule un score de similarité entre deux BC (0-1)
        Basé sur leurs features
        """
        score = 0.0
        weights_sum = 0.0
        
        # Format de date (poids: 0.3)
        if features1.get("date_format") == features2.get("date_format"):
            score += 0.3
        weights_sum += 0.3
        
        # Présence de tableau (poids: 0.2)
        if features1.get("has_table") == features2.get("has_table"):
            score += 0.2
        weights_sum += 0.2
        
        # Mots-clés communs (poids: 0.3)
        kw1 = set(features1.get("top_keywords", []))
        kw2 = set(features2.get("top_keywords", []))
        if kw1 and kw2:
            kw_overlap = len(kw1 & kw2) / max(len(kw1), len(kw2))
            score += 0.3 * kw_overlap
        weights_sum += 0.3
        
        # Densité numérique similaire (poids: 0.2)
        dens1 = features1.get("number_density", 0)
        dens2 = features2.get("number_density", 0)
        if dens1 > 0 and dens2 > 0:
            dens_sim = 1 - abs(dens1 - dens2) / max(dens1, dens2)
            score += 0.2 * dens_sim
        weights_sum += 0.2
        
        return score / weights_sum if weights_sum > 0 else 0.0
    
    def _rank_examples_by_similarity(
        self,
        bc_text: str,
        examples: List[Dict],
        max_examples: int = 5
    ) -> List[Dict]:
        """
        AMÉLIORATION 1 & 2: Tri intelligent + Détection de similarité
        Sélectionne les exemples les plus pertinents pour le BC
        """
        if not examples or len(examples) <= max_examples:
            return examples
        
        if self.debug:
            print(f"\n🔍 Analyse de similarité ({len(examples)} exemples disponibles)...")
        
        # Extraire features du BC cible
        bc_features = self._extract_text_features(bc_text)
        
        # Calculer scores pour chaque exemple
        scored_examples = []
        
        for ex in examples:
            # Essayer de récupérer le texte original de l'exemple
            ex_text = ex.get("_source_text", "")
            
            if not ex_text:
                # Reconstruire approximativement depuis le JSON
                ex_text = json.dumps(ex, ensure_ascii=False)
            
            ex_features = self._extract_text_features(ex_text)
            similarity = self._compute_similarity(bc_features, ex_features)
            
            scored_examples.append((similarity, ex))
            
            if self.debug:
                # Identifier l'exemple
                ex_id = "unknown"
                if "commandes" in ex and ex["commandes"]:
                    entete = ex["commandes"][0].get("entete", {})
                    ex_id = f"{entete.get('origine', '?')}-{entete.get('numCommande', '?')}"
                print(f"  📊 {ex_id}: similarité = {similarity:.3f}")
        
        # Trier par score décroissant
        scored_examples.sort(key=lambda x: x[0], reverse=True)
        
        # Prendre les top N
        selected = [ex for _, ex in scored_examples[:max_examples]]
        
        if self.debug:
            print(f"  ✓ {len(selected)} exemples sélectionnés (les plus similaires)")
        
        return selected
    
    def _get_or_build_generalized_pattern(
        self,
        client_id: str,
        examples: List[Dict]
    ) -> Dict[str, Any]:
        """
        AMÉLIORATION 3: Cache de patterns généralisés
        Extrait ou construit un pattern généralisé pour le client
        """
        cache_key = f"CLIENT_{client_id}"
        
        # Vérifier cache
        if cache_key in self.patterns_cache:
            if self.debug:
                print(f"  ⚡ Pattern généralisé trouvé en cache")
            return self.patterns_cache[cache_key]
        
        if self.debug:
            print(f"  🔨 Construction du pattern généralisé...")
        
        # Construire pattern généralisé
        pattern = {
            "structure": {},
            "field_types": {},
            "common_fields": [],
            "optional_fields": [],
            "field_constraints": {}
        }
        
        if not examples:
            return pattern
        
        # Analyser tous les exemples
        all_entete_fields = []
        all_produit_fields = []
        field_types = {}
        
        for ex in examples:
            if "commandes" not in ex or not ex["commandes"]:
                continue
            
            cmd = ex["commandes"][0]
            
            # Collecter champs entête
            if "entete" in cmd:
                entete_fields = list(cmd["entete"].keys())
                all_entete_fields.append(set(entete_fields))
                
                # Analyser types
                for field, value in cmd["entete"].items():
                    if field not in field_types:
                        field_types[field] = []
                    field_types[field].append(type(value).__name__)
            
            # Collecter champs produits
            if "detailCommande" in cmd and "produits" in cmd["detailCommande"]:
                produits = cmd["detailCommande"]["produits"]
                if produits:
                    produit_fields = list(produits[0].keys())
                    all_produit_fields.append(set(produit_fields))
                    
                    # Analyser types
                    for field, value in produits[0].items():
                        prod_field = f"produit.{field}"
                        if prod_field not in field_types:
                            field_types[prod_field] = []
                        field_types[prod_field].append(type(value).__name__)
        
        # Déterminer champs communs (présents dans tous)
        if all_entete_fields:
            common_entete = set.intersection(*all_entete_fields)
            pattern["common_fields"].extend([f"entete.{f}" for f in common_entete])
            
            # Champs optionnels (présents dans au moins un)
            all_entete_union = set.union(*all_entete_fields)
            optional_entete = all_entete_union - common_entete
            pattern["optional_fields"].extend([f"entete.{f}" for f in optional_entete])
        
        if all_produit_fields:
            common_produit = set.intersection(*all_produit_fields)
            
            # ORDRE FIXE pour les champs produits
            preferred_order = [
                "numLigne",
                "codeArticle", 
                "codeArticlePerso",
                "libelle",
                "quantite",
                "commentaire"
            ]
            
            # Ajouter les champs dans l'ordre préféré d'abord
            for field in preferred_order:
                if field in common_produit:
                    pattern["common_fields"].append(f"produit.{field}")
            
            # Ajouter les champs restants (s'il y en a)
            remaining = sorted([f for f in common_produit if f not in preferred_order])
            pattern["common_fields"].extend([f"produit.{f}" for f in remaining])
            
            all_produit_union = set.union(*all_produit_fields)
            optional_produit = all_produit_union - common_produit
            pattern["optional_fields"].extend([f"produit.{f}" for f in optional_produit])
        
        # Types majoritaires pour chaque champ
        for field, types in field_types.items():
            most_common_type = Counter(types).most_common(1)[0][0]
            pattern["field_types"][field] = most_common_type
        
        # Sauvegarder en cache
        self.patterns_cache[cache_key] = pattern
        self._save_patterns_cache()
        
        if self.debug:
            print(f"  ✓ Pattern construit: {len(pattern['common_fields'])} champs communs")
        
        return pattern
    
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
        + Enrichit avec métadonnées pour similarité
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
                    pattern = json.load(f)
                
                # Essayer de charger le texte source associé si disponible
                txt_file = json_file.with_suffix('.txt')
                if txt_file.exists():
                    with open(txt_file, 'r', encoding='utf-8') as f:
                        pattern["_source_text"] = f.read()
                
                patterns.append(pattern)
                
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
        filename_convention: Optional[str] = None,
        client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extraction intelligente avec LLM - Version OPTIMISÉE
        + Sélection intelligente des exemples
        + Utilisation du pattern généralisé
        """
        
        if not examples:
            raise RuntimeError("Aucun exemple disponible pour l'extraction")
        
        # AMÉLIORATION 1 & 2: Sélectionner exemples les plus similaires
        selected_examples = self._rank_examples_by_similarity(bc_text, examples, max_examples=5)
        
        # AMÉLIORATION 3: Récupérer pattern généralisé
        generalized_pattern = None
        if client_id:
            generalized_pattern = self._get_or_build_generalized_pattern(client_id, examples)
        
        # Formater les exemples
        examples_formatted = []
        for i, ex in enumerate(selected_examples, 1):
            ex_str = json.dumps(ex, indent=2, ensure_ascii=False)
            if len(ex_str) > 1500:
                lines = ex_str.split('\n')
                ex_str = '\n'.join(lines[:30]) + "\n      ...(produits supprimés)...\n" + '\n'.join(lines[-5:])
            examples_formatted.append(f"EXEMPLE {i}:\n{ex_str}")
        
        examples_block = "\n\n".join(examples_formatted)
        
        # Ajouter pattern généralisé au prompt
        pattern_guidance = ""
        if generalized_pattern:
            common_fields_str = ", ".join(generalized_pattern.get("common_fields", [])[:20])
            pattern_guidance = f"""
PATTERN GÉNÉRALISÉ (basé sur {len(examples)} BCs similaires):
- Champs OBLIGATOIRES: {common_fields_str}
- Types attendus: {json.dumps(generalized_pattern.get("field_types", {}), indent=2)[:500]}
"""

        system = """Tu es un expert en extraction de données de bons de commande.

Tu dois extraire les informations et générer un JSON structuré selon le format des exemples fournis.

PRINCIPES FONDAMENTAUX:
1. **Analyse des exemples** : Les exemples fournis ont été sélectionnés car ils sont SIMILAIRES au BC à traiter
2. **Flexibilité** : Adapte-toi aux variations de format du BC
3. **Cohérence** : Maintiens la même structure de sortie que les exemples
4. **Complétude** : Extrais TOUS les produits, du premier au dernier

RÈGLES DE STRUCTURE:
- Utilise une structure {"commandes": [...]} avec un tableau d'objets commande
- Chaque commande contient: "entete" et "detailCommande"
- L'entête contient les infos générales (dates, codes, origine...)
- Le détail contient un tableau "produits" et un "nbLignes"

RÈGLES DE TYPES:
- Dates: format YYYYMMDD (int) - ex: 20250214 = 14 février 2025
- Heures: format HHMMSS (string) - ex: "143000" = 14h30
- Quantités: float avec décimales - ex: 3.0, 10.5, 1.000
- Codes: strings, même s'ils contiennent que des chiffres
- Champs vides: "" (string) ou null selon le contexte

RÈGLES MÉTIER IMPORTANTES:
- **codeEtablissement**: Code numérique du site (ex: "02323", "910956")
- **codeFournisseur**: Nom de la VILLE du fournisseur/expéditeur
- **origine**: Nom du CLIENT qui passe commande
- **Codes articles**: 
  * Cherche d'abord dans colonne "CodeRef" si elle existe
  * Sinon: nombre entre PARENTHÈSES dans le libellé (ex: "PRODUIT#488(150508)" → "150508")
- **Codes articles perso**: nombre après le DIÈSE # (ex: "PRODUIT#488(150508)" → "488")

RÈGLES DE SÉPARATION:
- Si le BC contient plusieurs sections avec dates de livraison DIFFÉRENTES, crée une commande SÉPARÉE pour chaque date
- Chaque commande ne contient QUE les produits de sa section

CHAMPS OBLIGATOIRES (toujours présents):
- modeTransport: "L"
- typeCommande: "220"
- origineCommande: "D"
- version: "ACE"
"""

        # Préparer les listes de référence (limitées)
        ref_clients = "\n".join(f"  - {c}" for c in self.clients[:30]) if self.clients else "  (aucun)"
        ref_agences = "\n".join(f"  - {a}" for a in self.agences[:50]) if self.agences else "  (aucun)"

        user_prompt = f"""EXEMPLES SÉLECTIONNÉS (les plus similaires à ton BC):

{examples_block}

{pattern_guidance}

LISTES DE RÉFÉRENCE (extraits):

Clients autorisés (pour "origine"):
{ref_clients}
{f"  ... et {len(self.clients)-30} autres" if len(self.clients) > 30 else ""}

Agences autorisées (format: VILLE, CODE_POSTAL):
{ref_agences}
{f"  ... et {len(self.agences)-50} autres" if len(self.agences) > 50 else ""}

INSTRUCTIONS SPÉCIFIQUES:

1. **Identification des codes**:
   - codeEtablissement: Cherche mentions "Code site", "Code client", codes numériques proches du destinataire
   - codeFournisseur: Cherche la VILLE d'où vient la commande (expéditeur), compare avec liste agences
   - codePostal: Une fois la ville trouvée, utilise le code postal associé dans la liste

2. **Extraction des produits**:
   - Extrais TOUS les produits sans exception
   - Pour chaque produit, cherche: référence, libellé, quantité
   - Si tableau avec colonnes: utilise les colonnes (CodeRef, Désignation, Qté...)
   - Si format libre: parse intelligemment le texte

3. **Dates et heures**:
   - Convertis toutes les dates en YYYYMMDD (ex: "14 avril 2025" → 20250414)
   - Heures au format HHMMSS (ex: "14h30" → "143000")

4. **Séparation des commandes**:
   - Si plusieurs dates de livraison → plusieurs objets commande
   - Une commande = une date de livraison + ses produits

5. **Génération du numCommande**:
   - Format standard: "codeEtablissement-numeroCommande-index"
   - Exemple: si codeEtablissement="02323" et numéro="7992" → "02323-7992-1"

TEXTE DU BON DE COMMANDE:
{bc_text[:25000]}

GÉNÈRE le JSON en suivant la structure des exemples ci-dessus.
Les exemples fournis sont SIMILAIRES à ce BC, donc leur structure est particulièrement pertinente.
Assure-toi d'extraire TOUS les produits présents dans le bon de commande."""

        if self.debug:
            print(f"\n[DEBUG] Prompt LLM optimisé")
            print(f"  - {len(selected_examples)} exemples sélectionnés (sur {len(examples)} disponibles)")
            print(f"  - Pattern généralisé: {'OUI' if generalized_pattern else 'NON'}")
            print(f"  - Taille prompt: {len(user_prompt)} chars")
            print(f"  - Modèle: {self.model}")
        
        # Appel LLM
        llm_response = self._call_llm(system, user_prompt)
        
        # Validation SOUPLE avec pattern généralisé
        validated = self._validate_and_fix_structure_flexible(
            llm_response,
            selected_examples,
            filename_convention,
            generalized_pattern
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
    
    def _extract_common_fields(self, examples: List[Dict]) -> List[str]:
        """
        Extrait les champs COMMUNS des produits dans tous les exemples
        AVEC ORDRE SPÉCIFIQUE
        """
        if not examples:
            return []
        
        fields_sets = []
        
        for ex in examples:
            if "commandes" in ex and len(ex["commandes"]) > 0:
                cmd = ex["commandes"][0]
                if "detailCommande" in cmd and "produits" in cmd["detailCommande"]:
                    produits = cmd["detailCommande"]["produits"]
                    if produits and len(produits) > 0:
                        fields_sets.append(set(produits[0].keys()))
        
        if not fields_sets:
            return []
        
        # Intersection de tous les champs
        common = fields_sets[0]
        for fields in fields_sets[1:]:
            common &= fields
        
        # ORDRE FIXE SOUHAITÉ pour les produits
        preferred_order = [
            "numLigne",
            "codeArticle", 
            "codeArticlePerso",
            "libelle",
            "quantite",
            "commentaire"
        ]
        
        # Construire liste ordonnée: d'abord les champs dans l'ordre préféré, puis les autres
        ordered_fields = []
        for field in preferred_order:
            if field in common:
                ordered_fields.append(field)
        
        # Ajouter les champs restants (s'il y en a) triés alphabétiquement
        remaining = sorted([f for f in common if f not in preferred_order])
        ordered_fields.extend(remaining)
        
        return ordered_fields
    
    def _validate_and_fix_structure_flexible(
        self,
        llm_json: Dict,
        examples: List[Dict],
        filename_convention: Optional[str] = None,
        generalized_pattern: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Validation FLEXIBLE avec utilisation du pattern généralisé
        """
        
        # Envelopper si nécessaire
        if "commandes" not in llm_json:
            llm_json = {"commandes": [llm_json]}
        
        # Extraire les champs communs (priorité au pattern généralisé)
        if generalized_pattern and generalized_pattern.get("common_fields"):
            # Extraire uniquement les champs produits
            common_produit_fields = [
                f.replace("produit.", "") 
                for f in generalized_pattern["common_fields"] 
                if f.startswith("produit.")
            ]
        else:
            common_produit_fields = self._extract_common_fields(examples)
        
        for index, cmd in enumerate(llm_json["commandes"], start=1):
            # S'assurer de la structure minimale
            if "entete" not in cmd:
                cmd["entete"] = {}
            if "detailCommande" not in cmd:
                cmd["detailCommande"] = {"produits": [], "nbLignes": 0}
            
            entete = cmd["entete"]
            detail = cmd["detailCommande"]
            
            # Construire numCommande composite si convention définie
            if filename_convention and "{codeEtablissement}" in filename_convention:
                code_etab = entete.get("codeEtablissement", "")
                num_cmd_base = entete.get("numCommande", "")
                
                if code_etab and num_cmd_base:
                    if "-" in str(num_cmd_base):
                        parts = str(num_cmd_base).split("-")
                        num_cmd_clean = parts[1] if len(parts) >= 3 else parts[0]
                    else:
                        num_cmd_clean = str(num_cmd_base)
                    
                    composite_id = f"{code_etab}-{num_cmd_clean}-{index}"
                    entete["numCommande"] = composite_id
                    entete["idCommande"] = composite_id
            
            # Forcer heureCommande si absente
            if not entete.get("heureCommande"):
                from datetime import datetime
                entete["heureCommande"] = datetime.now().strftime("%H%M%S")
            
            # Forcer champs obligatoires
            entete["modeTransport"] = FORCED_MODE_TRANSPORT
            entete["typeCommande"] = FORCED_TYPE_COMMANDE
            entete["origineCommande"] = FORCED_ORIGINE_COMMANDE
            entete["version"] = FORCED_VERSION
            
            # Nettoyer produits selon pattern
            if common_produit_fields and detail.get("produits"):
                cleaned_produits = []
                for produit in detail["produits"]:
                    cleaned = {}
                    for field in common_produit_fields:
                        value = produit.get(field)
                        
                        # Validation de type si pattern disponible
                        if generalized_pattern:
                            expected_type = generalized_pattern.get("field_types", {}).get(f"produit.{field}")
                            if expected_type == "float" and value is not None:
                                try:
                                    value = float(value)
                                except (ValueError, TypeError):
                                    value = 0.0
                            elif expected_type == "int" and value is not None:
                                try:
                                    value = int(value)
                                except (ValueError, TypeError):
                                    value = 0
                            elif expected_type == "str" and value is not None:
                                value = str(value)
                        
                        # Normaliser quantité par défaut
                        if field == "quantite" and value is not None:
                            try:
                                value = float(value)
                            except (ValueError, TypeError):
                                value = 0.0
                        
                        # Forcer commentaire à string vide si null/None
                        if field == "commentaire" and (value is None or value == "null"):
                            value = ""
                        
                        cleaned[field] = value
                    
                    cleaned_produits.append(cleaned)
                
                detail["produits"] = cleaned_produits
            
            # Mettre à jour nbLignes
            detail["nbLignes"] = len(detail.get("produits", []))
        
        return llm_json
    
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
        
        result = self.extract_with_llm(bc_text, examples, filename_convention, client_id)
        
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
