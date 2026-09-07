#!/usr/bin/env python3
"""
Système RAG (Retrieval Augmented Generation) pour OCR
Permet au LLM de s'adapter dynamiquement à de nouveaux formats
en consultant une base de connaissances d'exemples

Prérequis:
    pip install sentence-transformers faiss-cpu

Usage:
    python rag_system.py --index      # Indexe tous les exemples
    python rag_system.py --query "texte du BC"  # Cherche des exemples similaires
    python rag_system.py --extract fichier.txt  # Extraction avec RAG
"""

import argparse
import json
from pathlib import Path
from typing import List, Dict, Any, Tuple
from datetime import datetime
import hashlib
import re

# Configuration
BASE_DIR = Path(__file__).parent.parent
PATTERNS_DIR = BASE_DIR / "patterns"
RAG_DIR = BASE_DIR / "training" / "rag"
VECTOR_DB_DIR = RAG_DIR / "vectordb"
RAG_DIR.mkdir(parents=True, exist_ok=True)

# Modèle d'embedding (léger et efficace)
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Configuration Ollama
OLLAMA_URL = "http://localhost:11434/api/generate"
LLM_MODEL = "qwen3-vl:8b"  # Plus précis pour l'extraction structurée


class DocumentStore:
    """Stockage et indexation des documents avec embeddings (FAISS)"""
    
    def __init__(self, persist_dir: Path):
        self.persist_dir = persist_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        
        self.embedder = None
        self.index = None
        self.documents = []  # Liste des documents
        self.metadatas = []  # Liste des métadonnées
        
        self._init_vectordb()
    
    def _init_vectordb(self):
        """Initialise la base vectorielle FAISS"""
        try:
            from sentence_transformers import SentenceTransformer
            import faiss
        except ImportError as e:
            print(f"Dépendances manquantes: {e}")
            print("Installez: pip install sentence-transformers faiss-cpu")
            return
        
        # Charger le modèle d'embedding
        print(f"🔧 Chargement du modèle d'embedding: {EMBEDDING_MODEL}")
        self.embedder = SentenceTransformer(EMBEDDING_MODEL)
        
        # Dimension des embeddings
        self.dimension = self.embedder.get_sentence_embedding_dimension()
        
        # Charger l'index existant ou en créer un nouveau
        index_file = self.persist_dir / "faiss_index.bin"
        docs_file = self.persist_dir / "documents.json"
        
        if index_file.exists() and docs_file.exists():
            # Charger l'index existant
            self.index = faiss.read_index(str(index_file))
            with open(docs_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.documents = data.get("documents", [])
                self.metadatas = data.get("metadatas", [])
            print(f"📦 Base vectorielle chargée: {len(self.documents)} documents")
        else:
            # Créer un nouvel index
            self.index = faiss.IndexFlatL2(self.dimension)
            self.documents = []
            self.metadatas = []
            print("📦 Nouvelle base vectorielle créée")
    
    def _save(self):
        """Sauvegarde l'index et les documents"""
        import faiss
        
        index_file = self.persist_dir / "faiss_index.bin"
        docs_file = self.persist_dir / "documents.json"
        
        faiss.write_index(self.index, str(index_file))
        with open(docs_file, 'w', encoding='utf-8') as f:
            json.dump({
                "documents": self.documents,
                "metadatas": self.metadatas
            }, f, ensure_ascii=False, indent=2)
    
    def _compute_doc_id(self, text: str) -> str:
        """Génère un ID unique pour un document"""
        return hashlib.md5(text.encode()).hexdigest()[:16]
    
    def add_document(self, text: str, metadata: Dict[str, Any], expected_json: Dict = None):
        """Ajoute un document à la base"""
        if not self.index or not self.embedder:
            print("Base vectorielle non initialisée")
            return
        
        import numpy as np
        
        doc_id = self._compute_doc_id(text)
        
        # Vérifier si le document existe déjà
        existing_ids = [m.get("doc_id") for m in self.metadatas]
        if doc_id in existing_ids:
            print(f"  ⏭️  Document déjà indexé: {doc_id[:8]}...")
            return
        
        # Créer l'embedding
        embedding = self.embedder.encode(text)
        embedding = np.array([embedding], dtype=np.float32)
        
        # Préparer les métadonnées
        meta = {
            "doc_id": doc_id,
            "client": metadata.get("client", "unknown"),
            "source": metadata.get("source", ""),
            "indexed_at": datetime.now().isoformat()
        }
        
        # Stocker le JSON attendu s'il existe
        if expected_json:
            meta["expected_json"] = json.dumps(expected_json, ensure_ascii=False)
        
        # Ajouter à l'index
        self.index.add(embedding)
        self.documents.append(text)
        self.metadatas.append(meta)
        
        # Sauvegarder
        self._save()
        
        print(f"  Document indexé: {doc_id[:8]}... ({len(text)} chars)")
    
    def search(self, query: str, top_k: int = 3) -> List[Dict]:
        """Recherche les documents les plus similaires"""
        if not self.index or not self.embedder or len(self.documents) == 0:
            return []
        
        import numpy as np
        
        # Créer l'embedding de la requête
        query_embedding = self.embedder.encode(query)
        query_embedding = np.array([query_embedding], dtype=np.float32)
        
        # Rechercher
        k = min(top_k, len(self.documents))
        distances, indices = self.index.search(query_embedding, k)
        
        # Formater les résultats
        formatted = []
        for i, idx in enumerate(indices[0]):
            if idx >= 0 and idx < len(self.documents):
                formatted.append({
                    "id": self.metadatas[idx].get("doc_id", ""),
                    "text": self.documents[idx],
                    "metadata": self.metadatas[idx],
                    "distance": float(distances[0][i]),
                    "similarity": 1 / (1 + float(distances[0][i]))  # Convertir distance en similarité
                })
        
        return formatted
    
    def get_stats(self) -> Dict:
        """Retourne les statistiques de la base"""
        return {
            "total_documents": len(self.documents),
            "persist_dir": str(self.persist_dir)
        }


class RAGIndexer:
    """Indexe tous les exemples des patterns dans la base vectorielle"""
    
    def __init__(self, patterns_dir: Path, document_store: DocumentStore):
        self.patterns_dir = patterns_dir
        self.store = document_store
    
    def index_all(self):
        """Indexe tous les exemples de tous les clients"""
        print(f"\n{'='*60}")
        print("📚 INDEXATION DES EXEMPLES POUR RAG")
        print(f"{'='*60}\n")
        
        total_indexed = 0
        
        for client_dir in self.patterns_dir.glob("CLIENT_*"):
            if not client_dir.is_dir():
                continue
            
            client_id = client_dir.name.replace("CLIENT_", "")
            print(f"\n📂 Client: {client_id}")
            
            # Indexer les paires BC texte + JSON
            bc_files = list(client_dir.glob("training_bc_*.txt"))
            
            for bc_file in bc_files:
                try:
                    num = bc_file.stem.split("_")[-1]
                    json_file = client_dir / f"training_json_{num}.json"
                    
                    # Lire le texte du BC
                    with open(bc_file, 'r', encoding='utf-8') as f:
                        bc_text = f.read()
                    
                    # Lire le JSON attendu s'il existe
                    expected_json = None
                    if json_file.exists():
                        with open(json_file, 'r', encoding='utf-8') as f:
                            expected_json = json.load(f)
                    
                    # Indexer
                    self.store.add_document(
                        text=bc_text,
                        metadata={
                            "client": client_id,
                            "source": str(bc_file)
                        },
                        expected_json=expected_json
                    )
                    total_indexed += 1
                    
                except Exception as e:
                    print(f"  ⚠️ Erreur: {e}")
        
        print(f"\nIndexation terminée: {total_indexed} documents")
        stats = self.store.get_stats()
        print(f"📊 Total dans la base: {stats.get('total_documents', 0)} documents")


class RAGExtractor:
    """Extracteur OCR augmenté par RAG"""
    
    def __init__(self, document_store: DocumentStore, llm_model: str = LLM_MODEL):
        self.store = document_store
        self.llm_model = llm_model
        self.ollama_url = OLLAMA_URL
    
    def _call_llm(self, prompt: str, temperature: float = 0.1) -> str:
        """Appelle le LLM via Ollama"""
        import requests
        
        try:
            response = requests.post(
                self.ollama_url,
                json={
                    "model": self.llm_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_ctx": 8192
                    }
                },
                timeout=600  # Augmenté à 10 minutes pour BC longs
            )
            
            if response.status_code == 200:
                return response.json().get("response", "")
            else:
                print(f"⚠️ Erreur LLM: {response.status_code}")
                return ""
        except Exception as e:
            print(f"Erreur appel LLM: {e}")
            return ""
    
    def extract_with_rag(self, text: str, top_k: int = 3, file_type: str = "pdf") -> Tuple[Dict, List[Dict]]:
        """
        Extrait les données d'un BC en utilisant RAG
        
        Returns:
            Tuple[Dict, List[Dict]]: (résultat extraction, exemples utilisés)
        """
        import time as time_module
        
        # Prédiction du temps d'extraction
        try:
            from training.time_predictor import predict_extraction_time
            prediction = predict_extraction_time(text, file_type)
            print(f"\n⏱️ Temps estimé: {prediction['estimated_time']}s "
                  f"(intervalle: {prediction['confidence_interval'][0]}s - {prediction['confidence_interval'][1]}s)")
        except Exception as e:
            prediction = None
            print(f"⚠️ Prédiction temps indisponible: {e}")
        
        start_time = time_module.time()
        
        print(f"\n🔍 Recherche d'exemples similaires...")
        
        # Chercher des exemples similaires
        similar_docs = self.store.search(text, top_k=top_k)
        
        if not similar_docs:
            print("⚠️ Aucun exemple trouvé, extraction sans contexte")
            return self._extract_without_context(text), []
        
        print(f"📚 {len(similar_docs)} exemples trouvés:")
        for i, doc in enumerate(similar_docs):
            print(f"  {i+1}. Client: {doc['metadata'].get('client', '?')} "
                  f"(similarité: {doc['similarity']:.2f})")
        
        # Construire le prompt avec les exemples
        prompt = self._build_rag_prompt(text, similar_docs)
        
        print(f"\n🤖 Appel LLM ({self.llm_model})...")
        response = self._call_llm(prompt)
        
        # Parser le JSON
        result = self._parse_json_response(response)
        
        # Scorer l'extraction
        print(f"\n📊 Évaluation de la qualité...")
        quality = self.score_extraction(text, result)
        
        print(f"\n{'='*60}")
        print(f"SCORE DE QUALITÉ: {quality['score']}/100 (Grade: {quality['grade']})")
        print(f"{'='*60}")
        
        if quality['details']:
            print(f"\n📋 Détails:")
            for key, value in quality['details'].items():
                print(f"  • {key}: {value}")
        
        if quality['issues']:
            print(f"\n⚠️  Problèmes détectés ({len(quality['issues'])}):")
            for issue in quality['issues']:
                print(f"  {issue}")
        else:
            print(f"\nAucun problème détecté")
        
        # Enregistrer le temps réel pour améliorer les prédictions futures
        actual_time = time_module.time() - start_time
        print(f"\n⏱️ Temps réel: {actual_time:.1f}s")
        
        try:
            from training.time_predictor import record_extraction_time
            record_extraction_time(text, file_type, actual_time)
        except Exception:
            pass  # Silencieux si erreur
        
        print(f"{'='*60}\n")
        
        return result, similar_docs
    
    def _load_client_prompt(self, client_name: str) -> str:
        """Charge le prompt spécifique d'un client depuis patterns/CLIENT_X/prompt.md"""
        try:
            prompt_path = PATTERNS_DIR / client_name / "prompt.md"
            if prompt_path.exists():
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                print(f"⚠️  Pas de prompt spécifique pour {client_name}")
                return ""
        except Exception as e:
            print(f"Erreur chargement prompt {client_name}: {e}")
            return ""
    
    def _build_rag_prompt(self, text: str, examples: List[Dict]) -> str:
        """Construit le prompt enrichi avec les exemples RAG"""
        
        # Identifier le client depuis le meilleur exemple
        best_example = examples[0] if examples else None
        client_name = best_example['metadata']['client'] if best_example and 'client' in best_example['metadata'] else None
        
        # Convertir le nom court en nom de dossier (B → CLIENT_B)
        if client_name:
            client_folder = f"CLIENT_{client_name}"
        else:
            client_folder = None
        
        # Charger le prompt spécifique du client
        client_prompt = ""
        if client_folder:
            client_prompt = self._load_client_prompt(client_folder)
            if client_prompt:
                print(f"📝 Prompt spécifique chargé pour {client_name}")
        
        # La détection des dates de livraison est gérée par le prompt spécifique de chaque client
        # Ici on laisse le LLM analyser le texte avec les règles du client
        dates_info = ""
        
        # Utiliser le texte complet pour tous les clients
        # Le prompt spécifique de chaque client guide l'extraction
        text_to_send = text
        
        # Ne garder que le meilleur exemple pour éviter les timeouts
        best_example = examples[0] if examples else None
        
        prompt = """Tu es un expert en extraction de données de bons de commande.

EXEMPLE DE RÉFÉRENCE:
"""
        if best_example:
            # Texte du BC (tronqué pour réduire la taille)
            bc_text = best_example['text'][:800] + "..." if len(best_example['text']) > 800 else best_example['text']
            prompt += f"\nTexte BC exemple:\n{bc_text}\n"
            
            # JSON attendu s'il existe
            if 'expected_json' in best_example['metadata']:
                try:
                    expected = json.loads(best_example['metadata']['expected_json'])
                    # Montrer UN produit COMPLET pour que le LLM voie TOUS les champs attendus
                    if expected.get('commandes') and expected['commandes'][0].get('detailCommande', {}).get('produits'):
                        example_structure = {
                            "commandes": [{
                                "entete": expected['commandes'][0]['entete'],
                                "detailCommande": {
                                    "produits": [
                                        expected['commandes'][0]['detailCommande']['produits'][0]  # 1 produit COMPLET
                                    ],
                                    "nbLignes": expected['commandes'][0]['detailCommande'].get('nbLignes', "...")
                                }
                            }]
                        }
                        prompt += f"\nJSON extrait (exemple avec 1 produit complet):\n{json.dumps(example_structure, indent=2, ensure_ascii=False)}\n"
                        prompt += f"\nIMPORTANT: Reproduis cette structure EXACTE pour TOUS les produits.\n"
                except:
                    pass
        
        prompt += f"""
--- FIN DE L'EXEMPLE ---

{'='*60}
SPÉCIFICATIONS DU CLIENT:
{'='*60}
{client_prompt if client_prompt else "Aucune spécification particulière."}
{'='*60}

{dates_info}
NOUVEAU BON DE COMMANDE:
{text_to_send}

INSTRUCTIONS GÉNÉRALES:
1. Extrait TOUTES les informations selon la structure JSON attendue
2. Respecte les spécifications du client ci-dessus (notamment pour le comptage des dates de livraison)
3. N'invente AUCUNE donnée, extrait UNIQUEMENT ce qui est présent

Réponds UNIQUEMENT avec le JSON complet, sans texte avant ou après.
Structure EXACTE attendue:
{{
  "commandes": [
    {{
      "entete": {{
        "origine": "CLIENT_B",
        "codeEtablissement": "XXXXX",
        "codeFournisseur": "FOURNISSEUR_X",
        "codePostal": "XXXXX",
        "numCommande": "XXXXX-XXXX-X",
        "idCommande": "XXXXX-XXXX-X",
        "dateCommande": YYYYMMDD,
        "heureCommande": 60000,
        "dateLivraison": YYYYMMDD,
        "commentaireEntete": "",
        "modeTransport": "L",
        "typeCommande": "220",
        "origineCommande": "D",
        "version": "ACE"
      }},
      "detailCommande": {{
        "produits": [
          {{"numLigne": 1, "codeArticle": "XXXXX", "libelle": "[A] ...", "quantite": X.X, "commentaire": ""}}
        ],
        "nbLignes": X
      }}
    }}
  ]
}}

IMPORTANT: 
- "entete" DOIT être AVANT "detailCommande"
- "nbLignes" DOIT être à la fin de "detailCommande" (après "produits")
- Un seul bloc JSON valide, pas de texte avant/après
"""
        return prompt
    
    def _extract_without_context(self, text: str) -> Dict:
        """Extraction basique sans exemples RAG"""
        prompt = f"""Tu es un expert en extraction de données de bons de commande.

Extrait les informations du bon de commande suivant en JSON:

{text}

Le JSON doit contenir:
- entete: origine, codeEtablissement, codeFournisseur, numCommande, dateCommande, dateLivraison
- detailCommande: produits (liste avec numLigne, codeArticle, libelle, quantite)

Réponds UNIQUEMENT avec le JSON."""
        
        response = self._call_llm(prompt)
        return self._parse_json_response(response)
    
    def _parse_json_response(self, response: str) -> Dict:
        """Parse la réponse JSON du LLM"""
        try:
            # Chercher le JSON dans la réponse
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"⚠️ Erreur parsing JSON: {e}")
        
        return {}
    
    def score_extraction(self, text: str, extracted_json: Dict) -> Dict:
        """
        Évalue la qualité de l'extraction JSON par rapport au texte source
        Retourne un score de confiance et les erreurs détectées
        """
        score = 100
        issues = []
        details = {}
        
        # 1. Vérifier la structure du JSON
        if not extracted_json or not extracted_json.get('commandes'):
            return {
                "score": 0,
                "grade": "F",
                "issues": ["JSON vide ou structure invalide"],
                "details": {}
            }
        
        commandes = extracted_json.get('commandes', [])
        details['nb_commandes'] = len(commandes)
        
        # 2. Détecter le nombre de dates de LIVRAISON (pas les DLC ou dates de création)
        # Chercher uniquement les dates après "Livraison au :" ou similaire
        delivery_patterns = [
            r'(?:livr(?:aison|é|ée)?(?:\s+(?:au|le|du|prévue?)?)?[\s:]+)((?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+\d{1,2}\s+(?:jan|fév|mar|avr|mai|juin|juil|août|sep|oct|nov|déc)[a-z]*\.?\s+\d{4})',
            r'(?:livr(?:aison|é|ée)?(?:\s+(?:au|le|du|prévue?)?)?[\s:]+)(\d{2}/\d{2}/\d{4})',
        ]
        
        delivery_dates = []
        for pattern in delivery_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            delivery_dates.extend(matches)
        
        # Dates uniques seulement
        unique_delivery_dates = list(dict.fromkeys(delivery_dates))
        expected_commandes = len(unique_delivery_dates) if unique_delivery_dates else 1
        details['dates_livraison_detectees'] = expected_commandes
        
        # Ne pénaliser que si le nombre de commandes ne correspond pas aux dates de livraison détectées
        if len(commandes) != expected_commandes and expected_commandes > 0:
            score -= 20
            issues.append(f"{len(commandes)} commande(s) extraite(s), {expected_commandes} date(s) de livraison détectée(s)")
        
        # 3. Vérifier chaque commande
        total_produits = 0
        for idx, commande in enumerate(commandes, 1):
            entete = commande.get('entete', {})
            detail = commande.get('detailCommande', {})
            produits = detail.get('produits', [])
            total_produits += len(produits)
            
            # Vérifier les champs obligatoires de l'entête
            required_entete = ['origine', 'numCommande', 'dateCommande', 'dateLivraison']
            missing_entete = [f for f in required_entete if not entete.get(f)]
            if missing_entete:
                score -= len(missing_entete) * 5
                issues.append(f"Commande {idx}: champs entête manquants ({', '.join(missing_entete)})")
            
            # Vérifier le format des dates
            date_fields = ['dateCommande', 'dateLivraison']
            for field in date_fields:
                date_val = entete.get(field)
                if date_val and not re.match(r'^\d{8}$', str(date_val)):
                    score -= 3
                    issues.append(f"Commande {idx}: {field} format invalide")
            
            # Vérifier les produits
            if not produits:
                score -= 15
                issues.append(f"Commande {idx}: aucun produit")
            else:
                for i, prod in enumerate(produits, 1):
                    missing_prod = [f for f in ['codeArticle', 'libelle', 'quantite'] if not prod.get(f)]
                    if missing_prod:
                        score -= 2
                        issues.append(f"Commande {idx}, Produit {i}: champs manquants")
        
        details['total_produits'] = total_produits
        
        # 4. Vérifier la présence du numéro de commande (validation désactivée car numéro souvent non extractible)
        # Certains PDFs ont le numéro en overlay/image non extractible par PyMuPDF
        
        # 5. Attribution du grade
        score = max(0, min(100, score))
        if score >= 90:
            grade = "A"
        elif score >= 80:
            grade = "B"
        elif score >= 70:
            grade = "C"
        elif score >= 60:
            grade = "D"
        else:
            grade = "F"
        
        return {
            "score": score,
            "grade": grade,
            "issues": issues,
            "details": details
        }
    
    def add_correction_to_rag(self, text: str, corrected_json: Dict, client: str = "unknown"):
        """
        Ajoute une correction à la base RAG pour apprentissage
        """
        print(f"\n📝 Ajout de la correction à la base RAG...")
        
        self.store.add_document(
            text=text,
            metadata={
                "client": client,
                "source": "user_correction",
                "correction_date": datetime.now().isoformat()
            },
            expected_json=corrected_json
        )
        
        print("Correction ajoutée à la base RAG")


def main():
    parser = argparse.ArgumentParser(description="Système RAG pour OCR")
    parser.add_argument('--index', action='store_true', help='Indexe tous les exemples')
    parser.add_argument('--query', type=str, help='Recherche des exemples similaires')
    parser.add_argument('--extract', type=str, help='Extraction avec RAG (fichier texte)')
    parser.add_argument('--stats', action='store_true', help='Affiche les statistiques')
    parser.add_argument('--top-k', type=int, default=3, help='Nombre d\'exemples à utiliser')
    
    args = parser.parse_args()
    
    # Initialiser le document store
    store = DocumentStore(VECTOR_DB_DIR)
    
    if args.index:
        indexer = RAGIndexer(PATTERNS_DIR, store)
        indexer.index_all()
    
    elif args.query:
        print(f"\n🔍 Recherche: {args.query[:100]}...")
        results = store.search(args.query, top_k=args.top_k)
        
        print(f"\n📚 {len(results)} résultats:")
        for i, doc in enumerate(results):
            print(f"\n--- Résultat {i+1} ---")
            print(f"Client: {doc['metadata'].get('client', '?')}")
            print(f"Similarité: {doc['similarity']:.3f}")
            print(f"Texte: {doc['text'][:200]}...")
    
    elif args.extract:
        file_path = Path(args.extract)
        if not file_path.exists():
            print(f"Fichier introuvable: {file_path}")
            return
        
        # Extraire le texte selon le type de fichier
        print(f"📄 Extraction du texte de: {file_path.name}")
        if file_path.suffix.lower() == '.pdf':
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
        else:
            # Fichier texte/HTML
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
        
        print(f"{len(text)} caractères extraits")
        
        extractor = RAGExtractor(store)
        result, examples = extractor.extract_with_rag(text, top_k=args.top_k)
        
        print(f"\n📤 RÉSULTAT DE L'EXTRACTION:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    elif args.stats:
        stats = store.get_stats()
        print(f"\n📊 STATISTIQUES RAG")
        print(f"  Documents indexés: {stats.get('total_documents', 0)}")
        print(f"  Dossier: {stats.get('persist_dir', '?')}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
