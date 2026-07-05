#!/usr/bin/env python3
"""
Visualisation de la base vectorielle Qdrant
Affiche statistiques, documents, et projections 2D des embeddings

Usage:
    python view_qdrant.py                    # Vue d'ensemble
    python view_qdrant.py --list             # Liste tous les documents
    python view_qdrant.py --visualize        # Projection 2D des embeddings
    python view_qdrant.py --search "query"   # Recherche avec visualisation
"""

import argparse
import json
from pathlib import Path
from typing import List, Dict
from rag_qdrant import QdrantDocumentStore, QDRANT_DIR, COLLECTION_NAME

def print_stats(store: QdrantDocumentStore):
    """Affiche les statistiques de la base"""
    stats = store.get_stats()
    
    print(f"\n{'='*70}")
    print(f"📊 STATISTIQUES QDRANT")
    print(f"{'='*70}\n")
    
    for key, value in stats.items():
        print(f"  {key:20s}: {value}")
    
    print(f"\n{'='*70}\n")


def list_all_documents(store: QdrantDocumentStore, limit: int = None):
    """Liste tous les documents de la collection"""
    if not store.client:
        print("❌ Client Qdrant non initialisé")
        return
    
    print(f"\n{'='*70}")
    print(f"📚 DOCUMENTS DANS LA COLLECTION '{COLLECTION_NAME}'")
    print(f"{'='*70}\n")
    
    # Récupérer tous les points (avec scroll pour pagination)
    offset = None
    count = 0
    
    while True:
        response = store.client.scroll(
            collection_name=store.collection_name,
            limit=10,  # Par batch de 10
            offset=offset,
            with_payload=True,
            with_vectors=False  # Pas besoin des vecteurs ici
        )
        
        points, next_offset = response
        
        if not points:
            break
        
        for point in points:
            count += 1
            
            if limit and count > limit:
                break
            
            print(f"┌─ Document #{count} (ID: {point.id[:16]}...)")
            print(f"│")
            
            # Métadonnées
            payload = point.payload or {}
            print(f"│  Client:     {payload.get('client', 'N/A')}")
            print(f"│  Source:     {payload.get('source', 'N/A')}")
            print(f"│  Indexé:     {payload.get('indexed_at', 'N/A')}")
            print(f"│  Taille:     {len(payload.get('text', ''))} caractères")
            
            # Aperçu du texte
            text = payload.get('text', '')
            preview = text[:150].replace('\n', ' ') + "..." if len(text) > 150 else text
            print(f"│")
            print(f"│  Aperçu:     {preview}")
            
            # JSON attendu si disponible
            if payload.get('expected_json'):
                try:
                    expected = json.loads(payload['expected_json'])
                    print(f"│  JSON:       {len(expected)} champs")
                except:
                    pass
            
            print(f"└{'─'*68}\n")
        
        if limit and count >= limit:
            break
            
        offset = next_offset
        if not offset:
            break
    
    print(f"Total: {count} documents affichés\n")


def visualize_embeddings(store: QdrantDocumentStore):
    """Visualise les embeddings en 2D avec t-SNE ou UMAP"""
    try:
        import numpy as np
        import matplotlib.pyplot as plt
        from sklearn.manifold import TSNE
    except ImportError:
        print("❌ Installation requise: pip install matplotlib scikit-learn")
        return
    
    if not store.client:
        print("❌ Client Qdrant non initialisé")
        return
    
    print(f"\n{'='*70}")
    print(f"🎨 VISUALISATION DES EMBEDDINGS")
    print(f"{'='*70}\n")
    
    # Récupérer tous les points avec vecteurs
    print("📥 Récupération des vecteurs...")
    offset = None
    vectors = []
    labels = []
    texts = []
    
    while True:
        response = store.client.scroll(
            collection_name=store.collection_name,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=True
        )
        
        points, next_offset = response
        
        if not points:
            break
        
        for point in points:
            vectors.append(point.vector)
            client = point.payload.get('client', 'Unknown')
            labels.append(client)
            text = point.payload.get('text', '')[:50]
            texts.append(text)
        
        offset = next_offset
        if not offset:
            break
    
    if len(vectors) < 2:
        print("⚠️  Pas assez de documents pour visualiser (minimum 2)")
        return
    
    print(f"✅ {len(vectors)} vecteurs récupérés\n")
    
    # Convertir en numpy
    X = np.array(vectors)
    
    # Réduction de dimension avec t-SNE
    print("🔄 Réduction de dimension avec t-SNE...")
    perplexity = min(30, len(vectors) - 1)
    tsne = TSNE(n_components=2, random_state=42, perplexity=perplexity)
    X_2d = tsne.fit_transform(X)
    
    # Créer le graphique
    plt.figure(figsize=(12, 8))
    
    # Couleurs par client
    unique_clients = list(set(labels))
    colors = plt.cm.rainbow(np.linspace(0, 1, len(unique_clients)))
    client_to_color = {client: colors[i] for i, client in enumerate(unique_clients)}
    
    for i, (x, y) in enumerate(X_2d):
        color = client_to_color[labels[i]]
        plt.scatter(x, y, c=[color], s=100, alpha=0.6, edgecolors='black', linewidth=1)
        
        # Annoter avec un numéro
        plt.annotate(str(i+1), (x, y), fontsize=8, ha='center', va='center')
    
    # Légende
    legend_elements = [
        plt.Line2D([0], [0], marker='o', color='w', 
                   markerfacecolor=client_to_color[client], 
                   markersize=10, label=client)
        for client in unique_clients
    ]
    plt.legend(handles=legend_elements, loc='best', title='Clients')
    
    plt.title('Projection 2D des Embeddings (t-SNE)', fontsize=14, fontweight='bold')
    plt.xlabel('Dimension 1')
    plt.ylabel('Dimension 2')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    # Sauvegarder
    output_file = Path(__file__).parent / "qdrant_visualization.png"
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"✅ Visualisation sauvegardée: {output_file}\n")
    
    # Afficher
    try:
        plt.show()
    except:
        print("⚠️  Impossible d'afficher (environnement sans GUI)")


def search_with_context(store: QdrantDocumentStore, query: str, top_k: int = 5):
    """Recherche avec affichage détaillé du contexte"""
    print(f"\n{'='*70}")
    print(f"🔍 RECHERCHE: '{query}'")
    print(f"{'='*70}\n")
    
    results = store.search(query, top_k=top_k)
    
    if not results:
        print("❌ Aucun résultat")
        return
    
    print(f"✅ {len(results)} résultats trouvés\n")
    
    for i, result in enumerate(results, 1):
        print(f"┌─ Résultat #{i}")
        print(f"│")
        print(f"│  ID:          {result['id'][:16]}...")
        print(f"│  Similarité:  {result['similarity']:.2%} {'█' * int(result['similarity'] * 20)}")
        print(f"│  Score:       {result['score']:.4f}")
        print(f"│")
        print(f"│  Client:      {result['metadata'].get('client', 'N/A')}")
        print(f"│  Source:      {result['metadata'].get('source', 'N/A')}")
        print(f"│")
        
        # Texte
        text = result.get('text', '')
        preview = text[:300].replace('\n', ' ') + "..." if len(text) > 300 else text
        print(f"│  Texte:")
        for line in preview.split('\n')[:5]:
            print(f"│    {line}")
        
        print(f"└{'─'*68}\n")


def export_to_json(store: QdrantDocumentStore, output_file: Path):
    """Export tous les documents en JSON"""
    if not store.client:
        print("❌ Client Qdrant non initialisé")
        return
    
    print(f"\n📤 Export en cours...")
    
    offset = None
    documents = []
    
    while True:
        response = store.client.scroll(
            collection_name=store.collection_name,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False
        )
        
        points, next_offset = response
        
        if not points:
            break
        
        for point in points:
            doc = {
                "id": point.id,
                "client": point.payload.get('client'),
                "source": point.payload.get('source'),
                "indexed_at": point.payload.get('indexed_at'),
                "text": point.payload.get('text'),
                "text_length": len(point.payload.get('text', '')),
            }
            
            if point.payload.get('expected_json'):
                try:
                    doc['expected_json'] = json.loads(point.payload['expected_json'])
                except:
                    pass
            
            documents.append(doc)
        
        offset = next_offset
        if not offset:
            break
    
    # Sauvegarder
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(documents, f, indent=2, ensure_ascii=False)
    
    print(f"✅ {len(documents)} documents exportés vers: {output_file}\n")


def main():
    parser = argparse.ArgumentParser(description="Visualisation base Qdrant")
    parser.add_argument("--list", action="store_true", help="Liste tous les documents")
    parser.add_argument("--limit", type=int, help="Limite nombre de documents affichés")
    parser.add_argument("--visualize", action="store_true", help="Projection 2D des embeddings")
    parser.add_argument("--search", type=str, help="Recherche avec contexte détaillé")
    parser.add_argument("--top-k", type=int, default=5, help="Nombre de résultats (défaut: 5)")
    parser.add_argument("--export", type=Path, help="Exporter vers fichier JSON")
    parser.add_argument("--server", action="store_true", help="Mode serveur Qdrant")
    
    args = parser.parse_args()
    
    # Initialiser le store
    use_local = not args.server
    store = QdrantDocumentStore(use_local=use_local)
    
    if args.list:
        list_all_documents(store, limit=args.limit)
    elif args.visualize:
        visualize_embeddings(store)
    elif args.search:
        search_with_context(store, args.search, top_k=args.top_k)
    elif args.export:
        export_to_json(store, args.export)
    else:
        # Vue d'ensemble par défaut
        print_stats(store)
        print("\n💡 Options disponibles:")
        print("  --list              Liste tous les documents")
        print("  --visualize         Graphique 2D des embeddings")
        print("  --search 'query'    Recherche avec détails")
        print("  --export file.json  Export JSON")


if __name__ == "__main__":
    main()
