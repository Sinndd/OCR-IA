#!/usr/bin/env python3
"""
Système RAG (Retrieval Augmented Generation) pour OCR avec Qdrant
Version améliorée avec base vectorielle Qdrant au lieu de FAISS

Prérequis:
    pip install qdrant-client sentence-transformers

Usage:
    python rag_qdrant.py --index      # Indexe tous les exemples
    python rag_qdrant.py --query "texte du BC"  # Cherche des exemples similaires
    python rag_qdrant.py --extract fichier.txt  # Extraction avec RAG
"""

import argparse
import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import hashlib
import re

# Configuration
BASE_DIR = Path(__file__).parent.parent
PATTERNS_DIR = BASE_DIR / "patterns"
RAG_DIR = BASE_DIR / "training" / "rag"
QDRANT_DIR = RAG_DIR / "qdrant_storage"
RAG_DIR.mkdir(parents=True, exist_ok=True)

# Modèle d'embedding (léger et efficace)
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Configuration Ollama
OLLAMA_URL = "http://localhost:11434/api/generate"
LLM_MODEL = "qwen2.5:7b"

# Configuration Qdrant
COLLECTION_NAME = "ocr_training_examples"
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333


class QdrantDocumentStore:
    """
    Stockage et indexation des documents avec Qdrant
    Supporte mode local (persiste sur disque) et mode serveur
    """
    
    def __init__(self, persist_dir: Path = None, use_local: bool = True, load_embedder: bool = True):
        """
        Args:
            persist_dir: Dossier de persistance pour mode local
            use_local: True pour mode local (fichiers), False pour serveur Qdrant
            load_embedder: Charge le modèle d'embedding si nécessaire
        """
        self.persist_dir = persist_dir or QDRANT_DIR
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.use_local = use_local
        self.load_embedder = load_embedder
        
        self.embedder = None
        self.client = None
        self.collection_name = COLLECTION_NAME
        
        self._init_vectordb()
    
    def _init_vectordb(self):
        """Initialise la base vectorielle Qdrant"""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams, PointStruct
        except ImportError as e:
            print(f"Dépendances manquantes: {e}")
            print("Installez: pip install qdrant-client sentence-transformers")
            return
        
        # Charger le modèle d'embedding si nécessaire
        if self.load_embedder:
            from sentence_transformers import SentenceTransformer
            print(f"🔧 Chargement du modèle d'embedding: {EMBEDDING_MODEL}")
            self.embedder = SentenceTransformer(EMBEDDING_MODEL)
            self.dimension = self.embedder.get_sentence_embedding_dimension()
        else:
            self.embedder = None
            self.dimension = None
        
        # Initialiser le client Qdrant
        if self.use_local:
            # Mode local: stockage sur disque
            self.client = QdrantClient(path=str(self.persist_dir))
            print(f"📦 Qdrant local initialisé: {self.persist_dir}")
        else:
            # Mode serveur: connexion au serveur Qdrant
            self.client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
            print(f"📦 Connexion Qdrant serveur: {QDRANT_HOST}:{QDRANT_PORT}")
        
        # Créer ou récupérer la collection
        try:
            collection_info = self.client.get_collection(self.collection_name)
            print(f"📚 Collection '{self.collection_name}' trouvée: {collection_info.points_count} documents")
        except Exception:
            # La collection n'existe pas, la créer
            if self.dimension is None:
                # Dimension inconnue sans embedder: éviter création automatique
                print("⚠️  Dimension inconnue (embedder non chargé). Collection non créée automatiquement.")
                return
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.dimension,
                    distance=Distance.COSINE  # Similarité cosinus (meilleure que L2 pour texte)
                )
            )
            print(f"📚 Collection '{self.collection_name}' créée")
    
    def _compute_doc_id(self, text: str) -> str:
        """Génère un ID unique pour un document"""
        return hashlib.md5(text.encode()).hexdigest()
    
    def add_document(self, text: str, metadata: Dict[str, Any], expected_json: Dict = None):
        """Ajoute un document à la base Qdrant"""
        if not self.client or not self.embedder:
            print("Base vectorielle non initialisée")
            return
        
        from qdrant_client.models import PointStruct
        
        doc_id = self._compute_doc_id(text)
        
        # Vérifier si le document existe déjà
        try:
            existing = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[doc_id]
            )
            if existing:
                print(f"  ⏭️  Document déjà indexé: {doc_id[:8]}...")
                return
        except Exception:
            pass
        
        # Créer l'embedding
        embedding = self.embedder.encode(text).tolist()
        
        # Préparer les métadonnées (payload Qdrant)
        payload = {
            "text": text,  # Stocker le texte dans le payload
            "client": metadata.get("client", "unknown"),
            "source": metadata.get("source", ""),
            "indexed_at": datetime.now().isoformat()
        }
        
        # Stocker le JSON attendu s'il existe
        if expected_json:
            payload["expected_json"] = json.dumps(expected_json, ensure_ascii=False)
        
        # Ajouter à Qdrant
        point = PointStruct(
            id=doc_id,
            vector=embedding,
            payload=payload
        )
        
        self.client.upsert(
            collection_name=self.collection_name,
            points=[point]
        )
        
        print(f"  Document indexé: {doc_id[:8]}... ({len(text)} chars)")
    
    def search(self, query: str, top_k: int = 3) -> List[Dict]:
        """Recherche les documents les plus similaires"""
        if not self.client or not self.embedder:
            return []
        
        from qdrant_client.models import Filter, FieldCondition
        
        # Créer l'embedding de la requête
        query_embedding = self.embedder.encode(query).tolist()
        
        # Rechercher dans Qdrant (API correcte)
        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_embedding,
            limit=top_k
        ).points
        
        # Formater les résultats
        formatted = []
        for hit in results:
            formatted.append({
                "id": hit.id,
                "text": hit.payload.get("text", ""),
                "metadata": {
                    "client": hit.payload.get("client"),
                    "source": hit.payload.get("source"),
                    "indexed_at": hit.payload.get("indexed_at"),
                    "expected_json": hit.payload.get("expected_json")
                },
                "score": hit.score,  # Score de similarité (0-1 avec COSINE)
                "similarity": hit.score  # Qdrant retourne directement la similarité
            })
        
        return formatted
    
    def get_stats(self) -> Dict:
        """Retourne les statistiques de la base"""
        if not self.client:
            return {"error": "Client non initialisé"}
        
        try:
            collection_info = self.client.get_collection(self.collection_name)
            return {
                "collection": self.collection_name,
                "total_documents": collection_info.points_count,
                "vector_size": collection_info.config.params.vectors.size,
                "persist_dir": str(self.persist_dir) if self.use_local else f"{QDRANT_HOST}:{QDRANT_PORT}",
                "mode": "local" if self.use_local else "server"
            }
        except Exception as e:
            return {"error": str(e)}
    
    def delete_collection(self):
        """Supprime la collection (utile pour réinitialiser)"""
        if self.client:
            try:
                self.client.delete_collection(self.collection_name)
                print(f"🗑️  Collection '{self.collection_name}' supprimée")
            except Exception as e:
                print(f"⚠️  Erreur suppression: {e}")


class RAGIndexer:
    """Indexe tous les exemples des patterns dans Qdrant"""
    
    def __init__(self, patterns_dir: Path, document_store: QdrantDocumentStore):
        self.patterns_dir = patterns_dir
        self.store = document_store
    
    def index_all(self):
        """Indexe tous les exemples de tous les clients"""
        print(f"\n{'='*60}")
        print("📚 INDEXATION DES EXEMPLES POUR RAG (QDRANT)")
        print(f"{'='*60}\n")
        
        total_indexed = 0
        
        for client_dir in self.patterns_dir.glob("CLIENT_*"):
            if not client_dir.is_dir():
                continue
            
            client_id = client_dir.name.replace("CLIENT_", "")
            print(f"\n📂 Client: {client_id}")
            
            # Indexer les paires BC texte + JSON
            bc_files = list(client_dir.glob("training_bc_*.txt"))
            
            # Accepter aussi training_bc.txt sans numéro
            bc_file_single = client_dir / "training_bc.txt"
            if bc_file_single.exists() and bc_file_single not in bc_files:
                bc_files.append(bc_file_single)
            
            for bc_file in bc_files:
                try:
                    # Extraire le numéro du fichier (ou utiliser 1 par défaut)
                    if bc_file.name == "training_bc.txt":
                        num = "1"
                    else:
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
        print(f"📊 Statistiques: {json.dumps(stats, indent=2, ensure_ascii=False)}")


class RAGExtractor:
    """Extracteur OCR augmenté par RAG avec Qdrant"""
    
    def __init__(self, document_store: QdrantDocumentStore, llm_model: str = LLM_MODEL):
        self.store = document_store
        self.llm_model = llm_model
    
    def extract_with_rag(self, bc_text: str, top_k: int = 3) -> Dict[str, Any]:
        """
        Extraction avec RAG:
        1. Rechercher des exemples similaires
        2. Enrichir le prompt avec ces exemples
        3. Appeler le LLM pour extraction
        """
        print(f"\n{'='*60}")
        print("🔍 EXTRACTION AVEC RAG")
        print(f"{'='*60}\n")
        
        # Étape 1: Rechercher des exemples similaires
        print("🔎 Recherche d'exemples similaires...")
        similar_docs = self.store.search(bc_text, top_k=top_k)
        
        if not similar_docs:
            print("⚠️  Aucun exemple similaire trouvé, extraction sans RAG")
            return self._extract_without_rag(bc_text)
        
        print(f"{len(similar_docs)} exemples trouvés\n")
        
        # Afficher les similarités
        for i, doc in enumerate(similar_docs, 1):
            print(f"  {i}. Client: {doc['metadata']['client']} | "
                  f"Similarité: {doc['similarity']:.2%}")
        
        # Étape 2: Construire le prompt enrichi
        prompt = self._build_rag_prompt(bc_text, similar_docs)
        
        # Étape 3: Appeler le LLM
        print(f"\n🤖 Appel LLM ({self.llm_model})...")
        result = self._call_llm(prompt)
        
        # Ajouter métadonnées RAG
        result["rag_metadata"] = {
            "examples_used": len(similar_docs),
            "top_client": similar_docs[0]["metadata"]["client"] if similar_docs else None,
            "top_similarity": similar_docs[0]["similarity"] if similar_docs else 0
        }
        
        return result
    
    def _build_rag_prompt(self, bc_text: str, similar_docs: List[Dict]) -> str:
        """Construit un prompt enrichi avec des exemples"""
        prompt = """Tu es un expert en extraction de données structurées depuis des bons de commande.

EXEMPLES DE RÉFÉRENCE (similaires au document à traiter):
"""
        
        for i, doc in enumerate(similar_docs, 1):
            prompt += f"\n--- Exemple {i} (similarité: {doc['similarity']:.1%}) ---\n"
            
            # Ajouter le texte
            prompt += f"TEXTE:\n{doc['text'][:500]}...\n"  # Limiter pour économiser tokens
            
            # Ajouter le JSON attendu si disponible
            if doc['metadata'].get('expected_json'):
                try:
                    expected = json.loads(doc['metadata']['expected_json'])
                    prompt += f"\nJSON EXTRAIT:\n{json.dumps(expected, indent=2, ensure_ascii=False)}\n"
                except:
                    pass
        
        prompt += f"""
{'='*60}

DOCUMENT À TRAITER:
{bc_text}

{'='*60}

INSTRUCTIONS:
- Analyse le document à traiter en t'inspirant des exemples ci-dessus
- Extrais les données dans le même format JSON que les exemples
- Retourne UNIQUEMENT le JSON, sans texte supplémentaire
- Champs obligatoires: numero_commande, client, date_commande, articles, montant_total
"""
        
        return prompt
    
    def _call_llm(self, prompt: str) -> Dict[str, Any]:
        """Appelle Ollama pour extraction"""
        import requests
        
        payload = {
            "model": self.llm_model,
            "prompt": prompt,
            "stream": False,
            "temperature": 0.0,
            "options": {
                "num_ctx": 8192
            }
        }
        
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
            resp.raise_for_status()
            
            response_text = resp.json().get("response", "")
            
            # Extraire le JSON de la réponse
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
            else:
                return {"error": "Pas de JSON dans la réponse", "raw": response_text}
        
        except Exception as e:
            return {"error": str(e)}
    
    def _extract_without_rag(self, bc_text: str) -> Dict[str, Any]:
        """Extraction sans RAG (fallback)"""
        prompt = f"""Extrais les données de ce bon de commande au format JSON:

{bc_text}

JSON (champs: numero_commande, client, date_commande, articles, montant_total):"""
        
        return self._call_llm(prompt)


# ========== CLI ==========

def main():
    parser = argparse.ArgumentParser(description="Système RAG avec Qdrant pour OCR")
    parser.add_argument("--index", action="store_true", help="Indexer tous les exemples")
    parser.add_argument("--query", type=str, help="Rechercher des exemples similaires")
    parser.add_argument("--extract", type=Path, help="Extraire avec RAG depuis un fichier")
    parser.add_argument("--reset", action="store_true", help="Réinitialiser la collection")
    parser.add_argument("--local", action="store_true", default=True, 
                       help="Mode local (défaut)")
    parser.add_argument("--server", action="store_true", 
                       help="Mode serveur Qdrant")
    parser.add_argument("--top-k", type=int, default=3, 
                       help="Nombre d'exemples à récupérer (défaut: 3)")
    
    args = parser.parse_args()
    
    # Déterminer le mode
    use_local = not args.server
    
    # Initialiser le store
    store = QdrantDocumentStore(use_local=use_local)
    
    if args.reset:
        print("🗑️  Réinitialisation de la collection...")
        store.delete_collection()
        store._init_vectordb()
        return
    
    if args.index:
        # Indexer tous les exemples
        indexer = RAGIndexer(PATTERNS_DIR, store)
        indexer.index_all()
    
    elif args.query:
        # Rechercher des exemples similaires
        print(f"\n🔍 Recherche: '{args.query[:50]}...'\n")
        results = store.search(args.query, top_k=args.top_k)
        
        if not results:
            print("Aucun résultat")
        else:
            for i, result in enumerate(results, 1):
                print(f"\n{'='*60}")
                print(f"Résultat #{i} | Similarité: {result['similarity']:.2%}")
                print(f"{'='*60}")
                print(f"Client: {result['metadata']['client']}")
                print(f"Source: {result['metadata']['source']}")
                print(f"\nTexte:\n{result['text'][:300]}...\n")
    
    elif args.extract:
        # Extraction avec RAG
        if not args.extract.exists():
            print(f"Fichier introuvable: {args.extract}")
            return
        
        # Lire le contenu (texte ou PDF)
        if args.extract.suffix.lower() == '.pdf':
            # Extraire le texte du PDF
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(args.extract)
                bc_text = ""
                for page in doc:
                    bc_text += page.get_text()
                doc.close()
                print(f"📄 PDF extrait: {len(bc_text)} caractères")
            except ImportError:
                print("PyMuPDF non installé. Installez: pip install pymupdf")
                return
            except Exception as e:
                print(f"Erreur lecture PDF: {e}")
                return
        else:
            # Fichier texte
            with open(args.extract, 'r', encoding='utf-8') as f:
                bc_text = f.read()
        
        extractor = RAGExtractor(store)
        result = extractor.extract_with_rag(bc_text, top_k=args.top_k)
        
        print(f"\n{'='*60}")
        print("📄 RÉSULTAT D'EXTRACTION")
        print(f"{'='*60}\n")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    else:
        # Stats par défaut
        stats = store.get_stats()
        print(f"\n📊 STATISTIQUES QDRANT")
        print(f"{'='*60}")
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        print(f"\nUsage:")
        print(f"  python {Path(__file__).name} --index          # Indexer")
        print(f"  python {Path(__file__).name} --query 'texte'  # Rechercher")
        print(f"  python {Path(__file__).name} --extract file   # Extraire avec RAG")


if __name__ == "__main__":
    main()
