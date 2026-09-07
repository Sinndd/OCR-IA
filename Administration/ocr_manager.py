#!/usr/bin/env python3
"""
OCR Manager - Gestion de la base de patterns
Administration des clients, exemples, statistiques
"""

import argparse
import json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
import shutil


class PatternManager:
    """
    Gestionnaire de la base de patterns
    Liste, info, suppression, statistiques
    """
    
    def __init__(self, patterns_dir: Path = None):
        self.patterns_dir = patterns_dir or Path("patterns")
    
    def list_clients(self) -> List[Dict[str, Any]]:
        """Liste tous les clients entraînés"""
        clients = []
        
        if not self.patterns_dir.exists():
            return clients
        
        for client_dir in sorted(self.patterns_dir.glob("CLIENT_*")):
            metadata_file = client_dir / "metadata.json"
            
            if not metadata_file.exists():
                continue
            
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                
                clients.append({
                    "client_id": metadata.get("client_id", "UNKNOWN"),
                    "origine": metadata.get("origine", ""),
                    "nb_exemples": metadata.get("nb_exemples", 0),
                    "nb_bc_traites": metadata.get("statistiques", {}).get("nb_bc_traites", 0),
                    "date_creation": metadata.get("date_creation", ""),
                    "derniere_utilisation": metadata.get("statistiques", {}).get("derniere_utilisation", "")
                })
            except Exception as e:
                print(f"⚠️  Erreur lecture {client_dir.name}: {e}")
        
        return clients
    
    def get_client_info(self, client_id: str) -> Dict[str, Any]:
        """Récupère les informations détaillées d'un client"""
        client_dir = self.patterns_dir / f"CLIENT_{client_id}"
        
        if not client_dir.exists():
            print(f"Client {client_id} introuvable")
            return {}
        
        metadata_file = client_dir / "metadata.json"
        
        if not metadata_file.exists():
            print(f"⚠️  Metadata introuvable pour {client_id}")
            return {}
        
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            # Compter fichiers
            nb_bc_files = len(list(client_dir.glob("training_bc_*.txt")))
            nb_json_files = len(list(client_dir.glob("training_json_*.json")))
            
            metadata["fichiers"] = {
                "nb_bc_txt": nb_bc_files,
                "nb_json": nb_json_files
            }
            
            return metadata
        
        except Exception as e:
            print(f"Erreur lecture metadata: {e}")
            return {}
    
    def delete_client(self, client_id: str, confirm: bool = False) -> bool:
        """Supprime un client et tous ses patterns"""
        client_dir = self.patterns_dir / f"CLIENT_{client_id}"
        
        if not client_dir.exists():
            print(f"Client {client_id} introuvable")
            return False
        
        if not confirm:
            print(f"⚠️  ATTENTION: Cette action va supprimer définitivement tous les patterns de {client_id}")
            print(f"Utilisez --confirm pour confirmer la suppression")
            return False
        
        try:
            shutil.rmtree(client_dir)
            print(f"Client {client_id} supprimé")
            return True
        except Exception as e:
            print(f"Erreur suppression: {e}")
            return False
    
    def get_global_stats(self) -> Dict[str, Any]:
        """Statistiques globales de tous les clients"""
        clients = self.list_clients()
        
        total_clients = len(clients)
        total_exemples = sum(c.get("nb_exemples", 0) for c in clients)
        total_bc_traites = sum(c.get("nb_bc_traites", 0) for c in clients)
        
        # Clients les plus utilisés
        top_clients = sorted(
            clients,
            key=lambda c: c.get("nb_bc_traites", 0),
            reverse=True
        )[:5]
        
        return {
            "total_clients": total_clients,
            "total_exemples": total_exemples,
            "total_bc_traites": total_bc_traites,
            "top_clients": top_clients
        }
    
    def export_client(self, client_id: str, export_dir: Path) -> bool:
        """Exporte les patterns d'un client"""
        client_dir = self.patterns_dir / f"CLIENT_{client_id}"
        
        if not client_dir.exists():
            print(f"Client {client_id} introuvable")
            return False
        
        export_path = export_dir / f"CLIENT_{client_id}"
        
        try:
            shutil.copytree(client_dir, export_path)
            print(f"Client {client_id} exporté vers {export_path}")
            return True
        except Exception as e:
            print(f"Erreur export: {e}")
            return False
    
    def import_client(self, import_dir: Path) -> bool:
        """Importe les patterns d'un client"""
        if not import_dir.exists():
            print(f"Dossier {import_dir} introuvable")
            return False
        
        # Vérifier que c'est un dossier client valide
        if not import_dir.name.startswith("CLIENT_"):
            print(f"Dossier invalide (doit commencer par CLIENT_)")
            return False
        
        metadata_file = import_dir / "metadata.json"
        if not metadata_file.exists():
            print(f"metadata.json introuvable")
            return False
        
        # Copier vers patterns/
        dest = self.patterns_dir / import_dir.name
        
        if dest.exists():
            print(f"⚠️  Client existe déjà dans {dest}")
            print(f"Utilisez --delete puis --import pour remplacer")
            return False
        
        try:
            shutil.copytree(import_dir, dest)
            print(f"Client importé dans {dest}")
            return True
        except Exception as e:
            print(f"Erreur import: {e}")
            return False


def print_clients_table(clients: List[Dict[str, Any]]):
    """Affiche un tableau des clients"""
    if not clients:
        print("Aucun client entraîné")
        return
    
    print(f"\n{'='*80}")
    print(f"{'CLIENT':<20} {'ORIGINE':<15} {'EXEMPLES':<10} {'BC TRAITÉS':<12} {'CRÉATION':<20}")
    print(f"{'='*80}")
    
    for client in clients:
        client_id = client.get("client_id", "?")
        origine = client.get("origine", "?")
        nb_exemples = client.get("nb_exemples", 0)
        nb_traites = client.get("nb_bc_traites", 0)
        date_creation = client.get("date_creation", "")
        
        # Formatter date
        try:
            dt = datetime.fromisoformat(date_creation)
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except:
            date_str = date_creation[:16] if date_creation else "?"
        
        print(f"{client_id:<20} {origine:<15} {nb_exemples:<10} {nb_traites:<12} {date_str:<20}")
    
    print(f"{'='*80}\n")


def print_client_detail(metadata: Dict[str, Any]):
    """Affiche les détails d'un client"""
    print(f"\n{'='*80}")
    print(f"CLIENT: {metadata.get('client_id', 'UNKNOWN')}")
    print(f"{'='*80}\n")
    
    print(f"📋 INFORMATIONS GÉNÉRALES")
    print(f"  • Origine: {metadata.get('origine', '?')}")
    print(f"  • Date création: {metadata.get('date_creation', '?')}")
    print(f"  • Dernière modification: {metadata.get('date_derniere_modification', '?')}")
    print(f"  • Nombre d'exemples: {metadata.get('nb_exemples', 0)}")
    
    fichiers = metadata.get("fichiers", {})
    print(f"\n📁 FICHIERS")
    print(f"  • BCs (txt): {fichiers.get('nb_bc_txt', 0)}")
    print(f"  • JSONs: {fichiers.get('nb_json', 0)}")
    
    patterns = metadata.get("patterns_detectes", {})
    print(f"\n🔍 PATTERNS DÉTECTÉS")
    
    origines = patterns.get("origines", [])
    if origines:
        print(f"  • Origines: {', '.join(origines)}")
    
    keywords = patterns.get("mots_cles_detection", [])
    if keywords:
        print(f"  • Mots-clés: {', '.join(keywords[:5])}")
        if len(keywords) > 5:
            print(f"    ... et {len(keywords)-5} autres")
    
    codes = patterns.get("codes_articles_typiques", [])
    if codes:
        print(f"  • Codes articles: {', '.join(codes)}")
    
    stats = metadata.get("statistiques", {})
    print(f"\n📊 STATISTIQUES D'UTILISATION")
    print(f"  • BCs traités: {stats.get('nb_bc_traites', 0)}")
    print(f"  • Taux de réussite: {stats.get('taux_reussite', 'N/A')}")
    print(f"  • Dernière utilisation: {stats.get('derniere_utilisation', 'Jamais')}")
    
    print(f"\n{'='*80}\n")


def print_global_stats(stats: Dict[str, Any]):
    """Affiche les statistiques globales"""
    print(f"\n{'='*80}")
    print(f"STATISTIQUES GLOBALES")
    print(f"{'='*80}\n")
    
    print(f"📊 RÉSUMÉ")
    print(f"  • Total clients: {stats['total_clients']}")
    print(f"  • Total exemples: {stats['total_exemples']}")
    print(f"  • Total BCs traités: {stats['total_bc_traites']}")
    
    top_clients = stats.get("top_clients", [])
    if top_clients:
        print(f"\n🏆 TOP 5 CLIENTS LES PLUS UTILISÉS")
        for i, client in enumerate(top_clients, 1):
            client_id = client.get("client_id", "?")
            nb_traites = client.get("nb_bc_traites", 0)
            print(f"  {i}. {client_id}: {nb_traites} BC(s)")
    
    print(f"\n{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(
        description="🔧 OCR Manager - Gestion de la base de patterns",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples d'utilisation:

  # Lister tous les clients
  python ocr_manager.py --list

  # Voir détails d'un client
  python ocr_manager.py --client-id NEWREST --info

  # Supprimer un client
  python ocr_manager.py --client-id NEWREST --delete --confirm

  # Statistiques globales
  python ocr_manager.py --stats

  # Exporter un client
  python ocr_manager.py --client-id NEWREST --export ./backup/

  # Importer un client
  python ocr_manager.py --import ./backup/CLIENT_NEWREST/
        """
    )
    
    parser.add_argument(
        '--patterns-dir',
        type=Path,
        default=Path("patterns"),
        help="Dossier des patterns (défaut: patterns/)"
    )
    
    parser.add_argument(
        '--list',
        action='store_true',
        help="Lister tous les clients entraînés"
    )
    
    parser.add_argument(
        '--client-id',
        help="Identifiant du client"
    )
    
    parser.add_argument(
        '--info',
        action='store_true',
        help="Afficher les informations détaillées d'un client"
    )
    
    parser.add_argument(
        '--delete',
        action='store_true',
        help="Supprimer un client"
    )
    
    parser.add_argument(
        '--confirm',
        action='store_true',
        help="Confirmer la suppression"
    )
    
    parser.add_argument(
        '--stats',
        action='store_true',
        help="Afficher les statistiques globales"
    )
    
    parser.add_argument(
        '--export',
        type=Path,
        help="Exporter un client vers un dossier"
    )
    
    parser.add_argument(
        '--import',
        type=Path,
        dest='import_dir',
        help="Importer un client depuis un dossier"
    )
    
    args = parser.parse_args()
    
    manager = PatternManager(patterns_dir=args.patterns_dir)
    
    # Liste
    if args.list:
        clients = manager.list_clients()
        print_clients_table(clients)
        exit(0)
    
    # Info client
    if args.info and args.client_id:
        metadata = manager.get_client_info(args.client_id)
        if metadata:
            print_client_detail(metadata)
        exit(0)
    
    # Suppression
    if args.delete and args.client_id:
        success = manager.delete_client(args.client_id, args.confirm)
        exit(0 if success else 1)
    
    # Statistiques globales
    if args.stats:
        stats = manager.get_global_stats()
        print_global_stats(stats)
        exit(0)
    
    # Export
    if args.export and args.client_id:
        success = manager.export_client(args.client_id, args.export)
        exit(0 if success else 1)
    
    # Import
    if args.import_dir:
        success = manager.import_client(args.import_dir)
        exit(0 if success else 1)
    
    # Si aucune action, afficher l'aide
    parser.print_help()


if __name__ == "__main__":
    main()
