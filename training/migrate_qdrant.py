#!/usr/bin/env python3
"""
Migration de la base Qdrant locale vers serveur avec dashboard
Permet d'utiliser l'interface web Qdrant
"""

import sys
from pathlib import Path
from rag_qdrant import QdrantDocumentStore

def migrate_to_server():
    """Migre les données du mode local vers serveur"""
    print("🔄 Migration Qdrant: Local → Serveur\n")
    
    # 1. Charger base locale
    print("1️⃣  Chargement base locale...")
    local_store = QdrantDocumentStore(use_local=True)
    local_stats = local_store.get_stats()
    print(f"   {local_stats.get('total_documents', 0)} documents trouvés\n")
    
    if local_stats.get('total_documents', 0) == 0:
        print("⚠️  Aucun document à migrer")
        return
    
    # 2. Connecter au serveur
    print("2️⃣  Connexion au serveur Qdrant (localhost:6333)...")
    try:
        server_store = QdrantDocumentStore(use_local=False)
        print("   Connecté\n")
    except Exception as e:
        print(f"   Erreur: {e}")
        print("\n💡 Démarrez d'abord le serveur Qdrant:")
        print("   docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant")
        return
    
    # 3. Migration
    print("3️⃣  Migration des documents...")
    
    offset = None
    migrated = 0
    
    while True:
        response = local_store.client.scroll(
            collection_name=local_store.collection_name,
            limit=10,
            offset=offset,
            with_payload=True,
            with_vectors=True
        )
        
        points, next_offset = response
        
        if not points:
            break
        
        # Transférer vers serveur
        from qdrant_client.models import PointStruct
        
        server_points = [
            PointStruct(
                id=point.id,
                vector=point.vector,
                payload=point.payload
            )
            for point in points
        ]
        
        server_store.client.upsert(
            collection_name=server_store.collection_name,
            points=server_points
        )
        
        migrated += len(points)
        print(f"   📦 {migrated} documents migrés...")
        
        offset = next_offset
        if not offset:
            break
    
    print(f"\nMigration terminée: {migrated} documents\n")
    
    # 4. Vérification
    server_stats = server_store.get_stats()
    print("📊 Statistiques serveur:")
    print(f"   Total: {server_stats.get('total_documents', 0)} documents")
    print(f"   Mode: {server_stats.get('mode', 'N/A')}")
    
    print("\n" + "="*70)
    print("🎉 MIGRATION RÉUSSIE")
    print("="*70)
    print("\n🌐 Dashboard Qdrant disponible sur:")
    print("   http://localhost:6333/dashboard")
    print("\n💡 Votre application peut maintenant utiliser:")
    print("   QdrantDocumentStore(use_local=False)")
    print("="*70 + "\n")


def start_instructions():
    """Affiche les instructions de démarrage"""
    print("\n" + "="*70)
    print("🚀 DÉMARRAGE QDRANT SERVEUR + DASHBOARD")
    print("="*70 + "\n")
    
    print("📋 Étapes:\n")
    
    print("1️⃣  Démarrer Qdrant serveur:")
    print("   docker run -d -p 6333:6333 -p 6334:6334 \\")
    print("       -v $(pwd)/OCR/training/rag/qdrant_storage_server:/qdrant/storage:z \\")
    print("       --name qdrant \\")
    print("       qdrant/qdrant\n")
    
    print("2️⃣  Migrer vos données:")
    print("   python OCR/training/migrate_qdrant.py --migrate\n")
    
    print("3️⃣  Ouvrir le dashboard:")
    print("   http://localhost:6333/dashboard\n")
    
    print("4️⃣  Mettre à jour votre code:")
    print("   store = QdrantDocumentStore(use_local=False)\n")
    
    print("="*70)
    print("📚 Documentation: https://qdrant.tech/documentation/")
    print("="*70 + "\n")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Migration Qdrant")
    parser.add_argument("--migrate", action="store_true", help="Migrer local → serveur")
    parser.add_argument("--instructions", action="store_true", help="Afficher instructions")
    
    args = parser.parse_args()
    
    if args.migrate:
        migrate_to_server()
    elif args.instructions:
        start_instructions()
    else:
        start_instructions()
