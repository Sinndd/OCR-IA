#!/usr/bin/env python3
"""
OCR Production - Solution Hybride Optimale
- Couche 1: Parsing structuré rapide (2-3s) - 80% des cas
- Couche 2: LLM fallback (20-40s) - 20% des cas difficiles
- Zero-touch: Pas de modification pour nouveaux formats
"""

import sys
import subprocess
from pathlib import Path


def main():
    """
    Architecture hybride intelligente
    """
    import argparse
    
    parser = argparse.ArgumentParser(description="OCR Production Hybride")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--examples-dir", default=".")
    parser.add_argument("--agences-file", required=True)
    parser.add_argument("--clients-file", required=True)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--force-llm", action="store_true", help="Forcer utilisation LLM")
    
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"🚀 OCR Production Hybride")
    print(f"{'='*60}\n")
    
    # Couche 1: Essayer parsing rapide d'abord (sauf si force-llm)
    if not args.force_llm:
        print("[Couche 1] Tentative parsing structuré rapide...")
        
        cmd_structured = [
            "python", "ocr_structured.py",
            "--input", args.input,
            "--out-dir", args.out_dir,
            "--agences-file", args.agences_file,
            "--clients-file", args.clients_file,
        ]
        
        if args.debug:
            cmd_structured.append("--debug")
        
        result = subprocess.run(cmd_structured, capture_output=True, text=True)
        
        # Vérifier si succès (au moins 1 JSON généré)
        output_dir = Path(args.out_dir)
        json_files = list(output_dir.glob("*.json")) if output_dir.exists() else []
        
        if result.returncode == 0 and len(json_files) > 0:
            print(f"\n✅ Succès parsing rapide: {len(json_files)} fichier(s)")
            print(f"⚡ Temps: ~2-3 secondes")
            return 0
        else:
            print(f"\n⚠️  Parsing rapide échoué, passage en mode LLM universel...")
    
    # Couche 2: Fallback LLM universel
    print(f"\n[Couche 2] Analyse LLM universelle (plus lent mais fonctionne sur tout)...")
    print(f"🤖 Utilisation: mistral:7b (rapide) au lieu de mistral-small3.2")
    
    cmd_universal = [
        "python", "ocr_universal.py",
        "--input", args.input,
        "--out-dir", args.out_dir,
        "--examples-dir", args.examples_dir,
        "--agences-file", args.agences_file,
        "--clients-file", args.clients_file,
        "--model", "mistral:7b",  # Plus rapide que mistral-small3.2
    ]
    
    if args.debug:
        cmd_universal.append("--debug")
    
    result = subprocess.run(cmd_universal)
    
    if result.returncode == 0:
        print(f"\n✅ Succès LLM universel")
        print(f"⏱️  Temps: ~20-40 secondes")
        return 0
    else:
        print(f"\n❌ Échec complet")
        return 1


if __name__ == "__main__":
    sys.exit(main())
