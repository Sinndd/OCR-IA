#!/usr/bin/env python3
"""
Script de visualisation des commandes JSON extraites
Affiche les données de manière lisible et structurée
"""

import json
import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List


def format_date(date_int: int) -> str:
    """Convertit une date YYYYMMDD en format lisible"""
    date_str = str(date_int)
    return f"{date_str[6:8]}/{date_str[4:6]}/{date_str[0:4]}"


def format_time(time_int: int) -> str:
    """Convertit une heure HHMMSS en format lisible"""
    time_str = str(time_int).zfill(6)
    return f"{time_str[0:2]}:{time_str[2:4]}:{time_str[4:6]}"


def display_order(json_data: Dict, filename: str):
    """
    Affiche une commande de manière formatée
    
    Args:
        json_data: Données JSON de la commande
        filename: Nom du fichier source
    """
    print("\n" + "=" * 80)
    print(f"📄 Fichier: {filename}")
    print("=" * 80)
    
    for commande in json_data.get('commandes', []):
        entete = commande.get('entete', {})
        detail = commande.get('detailCommande', {})
        
        print("\n📋 EN-TÊTE DE COMMANDE")
        print("-" * 80)
        print(f"  Numéro de commande    : {entete.get('numCommande', 'N/A')}")
        print(f"  ID Commande           : {entete.get('idCommande', 'N/A')}")
        print(f"  Date de commande      : {format_date(entete.get('dateCommande', 0))}")
        print(f"  Heure de commande     : {format_time(entete.get('heureCommande', 0))}")
        print(f"  Date de livraison     : {format_date(entete.get('dateLivraison', 0))}")
        print(f"  Origine               : {entete.get('origine', 'N/A')}")
        print(f"  Code établissement    : {entete.get('codeEtablissement', 'N/A')}")
        print(f"  Fournisseur           : {entete.get('codeFournisseur', 'N/A')}")
        print(f"  Code postal           : {entete.get('codePostal', 'N/A')}")
        print(f"  Mode transport        : {entete.get('modeTransport', 'N/A')}")
        print(f"  Type commande         : {entete.get('typeCommande', 'N/A')}")
        print(f"  Origine commande      : {entete.get('origineCommande', 'N/A')}")
        print(f"  Version               : {entete.get('version', 'N/A')}")
        
        if entete.get('commentaireEntete'):
            print(f"  Commentaire           : {entete.get('commentaireEntete')}")
        
        print("\n📦 DÉTAIL DES PRODUITS")
        print("-" * 80)
        print(f"  Nombre de lignes      : {detail.get('nbLignes', 0)}")
        print()
        
        produits = detail.get('produits', [])
        
        if not produits:
            print("  ⚠️  Aucun produit dans cette commande")
            continue
        
        # En-tête du tableau
        print(f"  {'#':<4} {'Code':<10} {'Quantité':<12} {'Libellé':<50}")
        print(f"  {'-'*4} {'-'*10} {'-'*12} {'-'*50}")
        
        # Lignes de produits
        total_quantite = 0
        for produit in produits:
            num = produit.get('numLigne', 0)
            code = produit.get('codeArticle', 'N/A')
            quantite = produit.get('quantite', 0.0)
            libelle = produit.get('libelle', 'N/A')
            
            # Troncature du libellé si trop long
            if len(libelle) > 50:
                libelle = libelle[:47] + "..."
            
            print(f"  {num:<4} {code:<10} {quantite:<12.3f} {libelle:<50}")
            total_quantite += quantite
            
            if produit.get('commentaire'):
                print(f"       💬 {produit.get('commentaire')}")
        
        print(f"  {'-'*4} {'-'*10} {'-'*12} {'-'*50}")
        print(f"  {'TOTAL':<15} {total_quantite:<12.3f}")


def display_summary(json_files: List[str]):
    """
    Affiche un résumé de toutes les commandes
    
    Args:
        json_files: Liste des fichiers JSON à analyser
    """
    print("\n" + "=" * 80)
    print("📊 RÉSUMÉ DES COMMANDES")
    print("=" * 80)
    
    total_commandes = 0
    total_produits = 0
    dates_livraison = set()
    
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            for commande in data.get('commandes', []):
                total_commandes += 1
                entete = commande.get('entete', {})
                detail = commande.get('detailCommande', {})
                
                date_liv = entete.get('dateLivraison')
                if date_liv:
                    dates_livraison.add(date_liv)
                
                total_produits += detail.get('nbLignes', 0)
        
        except Exception as e:
            print(f"⚠️  Erreur lors de la lecture de {json_file}: {e}")
    
    print(f"\n  Nombre de fichiers    : {len(json_files)}")
    print(f"  Nombre de commandes   : {total_commandes}")
    print(f"  Nombre de produits    : {total_produits}")
    print(f"  Dates de livraison    : {len(dates_livraison)}")
    
    if dates_livraison:
        print("\n  📅 Dates de livraison:")
        for date in sorted(dates_livraison):
            print(f"     - {format_date(date)}")


def main():
    """Point d'entrée principal du script"""
    parser = argparse.ArgumentParser(
        description="Visualisation des commandes JSON extraites"
    )
    parser.add_argument(
        '--dir', '-d',
        default='resultats',
        help="Répertoire contenant les fichiers JSON (défaut: resultats)"
    )
    parser.add_argument(
        '--file', '-f',
        help="Visualiser un fichier JSON spécifique"
    )
    parser.add_argument(
        '--summary', '-s',
        action='store_true',
        help="Afficher uniquement le résumé"
    )
    
    args = parser.parse_args()
    
    print("\n" + "=" * 80)
    print("  VISUALISATEUR DE COMMANDES JSON")
    print("=" * 80)
    
    json_files = []
    
    # Cas 1: Fichier spécifique
    if args.file:
        if not os.path.exists(args.file):
            print(f"\n❌ Fichier non trouvé: {args.file}")
            sys.exit(1)
        json_files = [args.file]
    
    # Cas 2: Tous les fichiers du répertoire
    else:
        if not os.path.exists(args.dir):
            print(f"\n❌ Répertoire non trouvé: {args.dir}")
            sys.exit(1)
        
        json_files = sorted([
            os.path.join(args.dir, f)
            for f in os.listdir(args.dir)
            if f.endswith('.json')
        ])
        
        if not json_files:
            print(f"\n⚠️  Aucun fichier JSON trouvé dans {args.dir}")
            sys.exit(1)
    
    # Affichage du résumé
    if args.summary:
        display_summary(json_files)
        return
    
    # Affichage détaillé de chaque commande
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            display_order(data, os.path.basename(json_file))
        
        except json.JSONDecodeError as e:
            print(f"\n❌ Erreur de parsing JSON dans {json_file}: {e}")
        except Exception as e:
            print(f"\n❌ Erreur lors de la lecture de {json_file}: {e}")
    
    # Résumé final
    if len(json_files) > 1:
        display_summary(json_files)
    
    print("\n" + "=" * 80)
    print()


if __name__ == "__main__":
    main()