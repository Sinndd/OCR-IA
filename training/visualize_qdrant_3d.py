#!/usr/bin/env python3
"""
Visualisation 3D interactive des embeddings Qdrant
Affiche les points en 3D avec distances et métadonnées
"""

import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path
from rag_qdrant import QdrantDocumentStore
import argparse

def visualize_3d(store: QdrantDocumentStore, method='tsne', save_html=True):
    """
    Visualisation 3D interactive des embeddings
    
    Args:
        store: Instance QdrantDocumentStore
        method: 'tsne' ou 'umap' pour la réduction de dimension
        save_html: Si True, sauvegarde en HTML interactif
    """
    print(f"\n{'='*70}")
    print(f"🎨 VISUALISATION 3D DES EMBEDDINGS ({method.upper()})")
    print(f"{'='*70}\n")
    
    if not store.client:
        print("Client Qdrant non initialisé")
        return
    
    # 1. Récupération des données
    print("📥 Récupération des vecteurs...")
    offset = None
    vectors = []
    clients = []
    texts = []
    ids = []
    sources = []
    
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
            clients.append(point.payload.get('client', 'Unknown'))
            text = point.payload.get('text', '')
            texts.append(text[:200] + '...' if len(text) > 200 else text)
            ids.append(str(point.id)[:16])
            sources.append(point.payload.get('source', 'N/A'))
        
        offset = next_offset
        if not offset:
            break
    
    if len(vectors) < 3:
        print("⚠️  Besoin d'au moins 3 documents pour visualisation 3D")
        return
    
    print(f"{len(vectors)} vecteurs récupérés")
    print(f"📊 Dimension originale: {len(vectors[0])}D\n")
    
    # 2. Réduction de dimension à 3D
    X = np.array(vectors)
    
    # Pour très petits datasets (≤5 points), forcer PCA (UMAP/t-SNE ne fonctionnent pas bien)
    if len(vectors) <= 5 and method in ['umap', 'tsne']:
        print(f"⚠️  Dataset trop petit pour {method.upper()} ({len(vectors)} points)")
        print(f"    Utilisation de PCA à la place\n")
        method = 'pca'
    
    print(f"🔄 Réduction de dimension avec {method.upper()}...")
    
    if method == 'tsne':
        from sklearn.manifold import TSNE
        perplexity = min(30, len(vectors) - 1)
        reducer = TSNE(n_components=3, random_state=42, perplexity=perplexity)
    elif method == 'umap':
        try:
            import umap
            # UMAP nécessite n_neighbors < n_samples
            n_neighbors = max(2, min(15, len(vectors) - 1))
            # Pour petits datasets (< 10 points), utiliser des paramètres conservateurs
            if len(vectors) < 10:
                reducer = umap.UMAP(
                    n_components=3, 
                    random_state=42, 
                    n_neighbors=n_neighbors,
                    min_dist=0.1,
                    metric='cosine'
                )
            else:
                reducer = umap.UMAP(n_components=3, random_state=42, n_neighbors=n_neighbors)
        except ImportError:
            print("⚠️  UMAP non installé, utilisation de t-SNE")
            print("   Installation: pip install umap-learn")
            from sklearn.manifold import TSNE
            perplexity = min(30, len(vectors) - 1)
            reducer = TSNE(n_components=3, random_state=42, perplexity=perplexity)
    else:
        from sklearn.decomposition import PCA
        reducer = PCA(n_components=3, random_state=42)
    
    X_3d = reducer.fit_transform(X)
    print(f"Réduction terminée: {X.shape[1]}D → 3D\n")
    
    # Pour petits datasets, vérifier si points trop proches et ajouter jitter
    if len(vectors) <= 10:
        coord_range = X_3d.max(axis=0) - X_3d.min(axis=0)
        if np.any(coord_range < 0.01):  # Points trop proches
            print("⚠️  Points très proches détectés, ajout de jitter pour visibilité...")
            # Ajouter un petit décalage aléatoire (5% de la plage)
            jitter_scale = 0.05 * (np.abs(X_3d).mean() + 0.1)
            X_3d += np.random.RandomState(42).normal(0, jitter_scale, X_3d.shape)
            print(f"   Jitter appliqué: ±{jitter_scale:.4f}\n")
    
    # 3. Calcul des distances moyennes entre points
    from scipy.spatial.distance import pdist, squareform
    distances_matrix = squareform(pdist(X))
    avg_distances = distances_matrix.mean(axis=1)
    
    # 4. Création de la visualisation interactive
    print("🎨 Génération de la visualisation 3D...")
    
    # Assigner des couleurs par client
    unique_clients = list(set(clients))
    color_map = {client: i for i, client in enumerate(unique_clients)}
    colors = [color_map[client] for client in clients]
    
    # Créer le hover text détaillé
    hover_texts = [
        f"<b>Client:</b> {client}<br>"
        f"<b>ID:</b> {doc_id}<br>"
        f"<b>Source:</b> {source}<br>"
        f"<b>Distance moy:</b> {dist:.3f}<br>"
        f"<b>Texte:</b> {text[:100]}..."
        for client, doc_id, source, dist, text in zip(clients, ids, sources, avg_distances, texts)
    ]
    
    # Créer le scatter 3D
    fig = go.Figure(data=[go.Scatter3d(
        x=X_3d[:, 0],
        y=X_3d[:, 1],
        z=X_3d[:, 2],
        mode='markers+text',
        marker=dict(
            size=20,  # Augmenté de 8 à 20 pour meilleure visibilité
            color=colors,
            colorscale='Rainbow',
            showscale=True,
            colorbar=dict(
                title="Client",
                ticktext=unique_clients,
                tickvals=list(range(len(unique_clients))),
            ),
            line=dict(color='black', width=2),
            opacity=0.9
        ),
        text=[f"{i+1}" for i in range(len(X_3d))],
        textposition="top center",
        textfont=dict(size=12, color='black', family='Arial Black'),
        hovertext=hover_texts,
        hoverinfo='text'
    )])
    
    # Configuration du layout
    method_description = {
        'tsne': 't-SNE (regroupement par similarité)',
        'pca': 'PCA (analyse en composantes principales)'
    }
    
    fig.update_layout(
        title=dict(
            text=f"Visualisation 3D des Embeddings OCR - {method_description.get(method, method.upper())}<br>"
                 f"<sub>{len(vectors)} documents | {len(unique_clients)} clients | "
                 f"Plus les points sont proches, plus les documents se ressemblent</sub>",
            x=0.5,
            xanchor='center'
        ),
        scene=dict(
            xaxis_title='Similarité Structurelle →',
            yaxis_title='Similarité Sémantique →',
            zaxis_title='Complexité Document →',
            xaxis=dict(showgrid=True, gridwidth=1, gridcolor='lightgray'),
            yaxis=dict(showgrid=True, gridwidth=1, gridcolor='lightgray'),
            zaxis=dict(showgrid=True, gridwidth=1, gridcolor='lightgray'),
            camera=dict(
                eye=dict(x=1.5, y=1.5, z=1.5)
            )
        ),
        width=1200,
        height=800,
        hovermode='closest'
    )
    
    # 5. Sauvegarder et afficher
    if save_html:
        output_file = Path(__file__).parent / f"qdrant_3d_{method}.html"
        fig.write_html(str(output_file))
        print(f"Visualisation sauvegardée: {output_file}")
        print(f"   Ouvrir avec: open {output_file}\n")
    
    # Afficher dans le navigateur
    try:
        fig.show()
        print("Visualisation ouverte dans le navigateur\n")
    except:
        print("⚠️  Impossible d'ouvrir automatiquement (utilisez le fichier HTML)\n")
    
    # 6. Statistiques d'espacement
    print(f"{'='*70}")
    print("📏 STATISTIQUES D'ESPACEMENT")
    print(f"{'='*70}")
    print(f"Distance moyenne entre points:     {distances_matrix[np.triu_indices_from(distances_matrix, k=1)].mean():.4f}")
    print(f"Distance minimale:                 {distances_matrix[distances_matrix > 0].min():.4f}")
    print(f"Distance maximale:                 {distances_matrix.max():.4f}")
    print(f"Écart-type:                        {distances_matrix[np.triu_indices_from(distances_matrix, k=1)].std():.4f}")
    
    # Statistiques par client
    print(f"\n{'─'*70}")
    print("📊 DISTANCES MOYENNES PAR CLIENT")
    print(f"{'─'*70}")
    for client in unique_clients:
        client_indices = [i for i, c in enumerate(clients) if c == client]
        if len(client_indices) > 1:
            client_distances = distances_matrix[np.ix_(client_indices, client_indices)]
            client_distances = client_distances[np.triu_indices_from(client_distances, k=1)]
            print(f"  {client:20s}: {client_distances.mean():.4f} ± {client_distances.std():.4f}")
    
    print(f"{'='*70}\n")
    
    # 7. Clusters automatiques
    try:
        from sklearn.cluster import KMeans
        n_clusters = min(len(unique_clients) + 1, len(vectors) - 1)
        if n_clusters >= 2:
            print("🔍 Détection de clusters automatique...")
            kmeans = KMeans(n_clusters=n_clusters, random_state=42)
            clusters = kmeans.fit_predict(X)
            
            print(f"   {n_clusters} clusters détectés:")
            for i in range(n_clusters):
                cluster_clients = [clients[j] for j in range(len(clients)) if clusters[j] == i]
                print(f"   Cluster {i+1}: {len(cluster_clients)} docs | Clients: {set(cluster_clients)}")
            print()
    except:
        pass


def main():
    parser = argparse.ArgumentParser(description="Visualisation 3D Qdrant")
    parser.add_argument("--method", choices=['tsne', 'umap', 'pca'], default='tsne',
                       help="Méthode de réduction (défaut: tsne)")
    parser.add_argument("--server", action="store_true", help="Utiliser serveur Qdrant")
    parser.add_argument("--local", action="store_true", default=True, help="Utiliser Qdrant local (défaut)")
    
    args = parser.parse_args()
    
    # Initialiser le store
    use_local = not args.server if args.server else True
    store = QdrantDocumentStore(use_local=use_local, load_embedder=False)
    
    # Vérifier qu'il y a des données
    stats = store.get_stats()
    if stats.get('total_documents', 0) == 0:
        print("Aucun document dans la base")
        print("   Indexez d'abord: python rag_qdrant.py --index")
        return
    
    # Visualiser
    visualize_3d(store, method=args.method, save_html=True)


if __name__ == "__main__":
    main()
