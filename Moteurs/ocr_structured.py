#!/usr/bin/env python3
"""
OCR Structuré - Extraction universelle de bons de commande
Approche hybride : Parsing intelligent + fallback LLM
Optimisé pour production et automatisation
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from difflib import SequenceMatcher

import fitz  # PyMuPDF


# ---------- Configuration ----------
# Règles métier fixes
FORCED_MODE_TRANSPORT = "L"
FORCED_ORIGINE_COMMANDE = "D"
FORCED_VERSION = "ACE"
FORCED_TYPE_COMMANDE = "220"


class StructuredExtractor:
    """Extracteur structuré avec parsing intelligent"""
    
    def __init__(
        self,
        agences_file: Path,
        clients_file: Path,
        debug: bool = False
    ):
        self.agences = self._load_reference_file(agences_file)
        self.clients = self._load_reference_file(clients_file)
        self.debug = debug
    
    def _load_reference_file(self, filepath: Path) -> List[str]:
        """Charge un fichier de référence"""
        if not filepath or not filepath.exists():
            print(f"⚠️  Fichier {filepath} introuvable")
            return []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    
    def _find_best_match(self, text: str, candidates: List[str], min_ratio: float = 0.6) -> Optional[str]:
        """Trouve la meilleure correspondance fuzzy"""
        if not candidates:
            return None
        
        text_upper = text.upper()
        best_match = None
        best_score = 0.0
        
        # Stratégie 1: Recherche exacte
        for candidate in candidates:
            if candidate.upper() in text_upper:
                if self.debug:
                    print(f"  🎯 Match exact: '{candidate}'")
                return candidate
        
        # Stratégie 2: Recherche par mots
        for candidate in candidates:
            candidate_words = candidate.upper().split()
            matches = sum(1 for word in candidate_words if word in text_upper)
            if matches > 0:
                score = matches / len(candidate_words)
                if score > best_score:
                    best_score = score
                    best_match = candidate
        
        if best_score >= min_ratio:
            if self.debug:
                print(f"  🎯 Match partiel: '{best_match}' (score: {best_score:.2f})")
            return best_match
        
        # Stratégie 3: Fuzzy matching
        for candidate in candidates:
            words = text_upper.split()
            for i in range(len(words)):
                window = ' '.join(words[i:i+len(candidate.split())+2])
                ratio = SequenceMatcher(None, candidate.upper(), window).ratio()
                if ratio > best_score:
                    best_score = ratio
                    best_match = candidate
        
        if best_score >= min_ratio:
            if self.debug:
                print(f"  🎯 Match fuzzy: '{best_match}' (score: {best_score:.2f})")
            return best_match
        
        return None
    
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
    
    def detect_delivery_dates(self, text: str) -> List[Tuple[int, str]]:
        """
        Détecte toutes les dates de livraison dans le document
        Returns: Liste de (position, date_string)
        """
        patterns = [
            r'Livraison\s+au\s*:\s*(.+?)(?:\n|$)',
            r'Livraison\s+le\s*:\s*(.+?)(?:\n|$)',
            r'Date\s+de\s+livraison\s*:\s*(.+?)(?:\n|$)',
            # Format INFLIGHT: "Delivery Date" suivi de date quelques lignes plus bas
            r'Delivery\s+Date\s*\n(?:.*?\n){0,5}?(\d{1,2}/\d{1,2}/\d{4})',
        ]
        
        dates_found = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
                position = match.start()
                date_str = match.group(1).strip()
                # Vérifier que c'est bien une date (contient chiffres)
                if re.search(r'\d', date_str):
                    dates_found.append((position, date_str))
        
        # Trier par position dans le document
        dates_found.sort(key=lambda x: x[0])
        
        if self.debug:
            print(f"\n  📅 {len(dates_found)} date(s) de livraison détectée(s):")
            for pos, date in dates_found:
                print(f"    - Position {pos}: {date}")
        
        return dates_found
        
        dates_found = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                position = match.start()
                date_str = match.group(1).strip()
                dates_found.append((position, date_str))
        
        # Trier par position dans le document
        dates_found.sort(key=lambda x: x[0])
        
        if self.debug:
            print(f"\n  📅 {len(dates_found)} date(s) de livraison détectée(s):")
            for pos, date in dates_found:
                print(f"    - Position {pos}: {date}")
        
        return dates_found
    
    def parse_date(self, date_str: str) -> Optional[int]:
        """Parse une date en format YYYYMMDD"""
        if not date_str:
            return None
        
        # Nettoyer
        date_str = date_str.strip()
        
        # Patterns de date français
        patterns = [
            (r'(\d{1,2})\s+(\w+\.?)\s+(\d{4})', self._parse_french_date),  # "14 avr. 2025"
            (r'(\d{1,2})/(\d{1,2})/(\d{4})', self._parse_slash_date),      # "14/04/2025"
            (r'(\d{1,2})-(\d{1,2})-(\d{4})', self._parse_slash_date),      # "14-04-2025"
            (r'(\d{4})-(\d{1,2})-(\d{1,2})', self._parse_iso_date),        # "2025-04-14"
        ]
        
        for pattern, parser in patterns:
            match = re.search(pattern, date_str)
            if match:
                result = parser(match)
                if result:
                    return result
        
        return None
    
    def _parse_french_date(self, match) -> Optional[int]:
        """Parse format français: 14 avr. 2025"""
        day, month_str, year = match.groups()
        
        months = {
            'janv': 1, 'jan': 1, 'février': 2, 'févr': 2, 'fev': 2, 'mars': 3, 'mar': 3,
            'avril': 4, 'avr': 4, 'mai': 5, 'juin': 6, 'juil': 7, 'juillet': 7,
            'août': 8, 'aout': 8, 'sept': 9, 'septembre': 9, 'oct': 10, 'octobre': 10,
            'nov': 11, 'novembre': 11, 'déc': 12, 'dec': 12, 'décembre': 12
        }
        
        month_clean = month_str.lower().replace('.', '').strip()
        month = months.get(month_clean)
        
        if month:
            try:
                return int(f"{year}{month:02d}{int(day):02d}")
            except:
                pass
        
        return None
    
    def _parse_slash_date(self, match) -> Optional[int]:
        """Parse format: DD/MM/YYYY ou DD-MM-YYYY"""
        day, month, year = match.groups()
        try:
            return int(f"{year}{int(month):02d}{int(day):02d}")
        except:
            return None
    
    def _parse_iso_date(self, match) -> Optional[int]:
        """Parse format ISO: YYYY-MM-DD"""
        year, month, day = match.groups()
        try:
            return int(f"{year}{int(month):02d}{int(day):02d}")
        except:
            return None
    
    def extract_header_info(self, text: str) -> Dict[str, Any]:
        """Extrait les informations d'en-tête"""
        info = {}
        
        # Date de commande (chercher différents formats)
        # Format 1: en haut du document (DD/MM/YYYY)
        date_match = re.search(r'^\s*(\d{1,2}/\d{1,2}/\d{4})', text, re.MULTILINE)
        if date_match:
            info['dateCommande'] = self.parse_date(date_match.group(1))
        else:
            # Format 2: INFLIGHT - chercher "Delivery Date" suivi de date
            date_match = re.search(r'Delivery\s+Date\s*\n\s*(\d{1,2}/\d{1,2}/\d{4})', text, re.IGNORECASE)
            if date_match:
                info['dateCommande'] = self.parse_date(date_match.group(1))
        
        # Numéro de commande
        # Format 1: "Commande N°"
        num_match = re.search(r'(?:Commande|Order)\s+N[°º]\s*:?\s*(\d+)', text, re.IGNORECASE)
        if num_match:
            info['numeroCommande'] = num_match.group(1)
        else:
            # Format 2: INFLIGHT - "PURCHASE ORDER No"
            num_match = re.search(r'PURCHASE\s+ORDER\s+No\s*(\d+)', text, re.IGNORECASE)
            if num_match:
                info['numeroCommande'] = num_match.group(1)
        
        # Code API
        api_match = re.search(r'Code\s+API\s*:\s*(\S+)', text, re.IGNORECASE)
        if api_match:
            info['codeEtablissement'] = api_match.group(1).strip()
        
        # Code Region (à ignorer, mais utile pour debug)
        region_match = re.search(r'Code\s+Region\s*:\s*(\S+)', text, re.IGNORECASE)
        if region_match and self.debug:
            print(f"  ℹ️  Code Region détecté (ignoré): {region_match.group(1)}")
        
        # Client (origine)
        info['origine'] = self._find_best_match(text, self.clients)
        
        # Agence (codeFournisseur)
        info['codeFournisseur'] = self._find_best_match(text, self.agences)
        
        # Code postal de l'agence
        if info.get('codeFournisseur'):
            agence_pattern = re.escape(info['codeFournisseur'])
            agence_match = re.search(
                rf'{agence_pattern}[^\n]*\n(.*?)(?:\n\n|Destinataire|Client|CodeRef|$)',
                text, re.DOTALL | re.IGNORECASE
            )
            if agence_match:
                postal_match = re.search(r'\b(\d{5})\b', agence_match.group(1))
                if postal_match:
                    info['codePostal'] = postal_match.group(1)
        
        # Si pas trouvé, chercher code postal général dans le document
        if not info.get('codePostal'):
            # Chercher 5 chiffres isolés
            postal_matches = re.findall(r'\b(\d{5})\b', text)
            if postal_matches:
                # Prendre le premier (souvent le bon)
                info['codePostal'] = postal_matches[0]
        
        if self.debug:
            print(f"\n  📋 Informations en-tête extraites:")
            for key, value in info.items():
                print(f"    {key}: {value}")
        
        return info
    
    def extract_products_between_dates(
        self, 
        text: str, 
        start_pos: int, 
        end_pos: Optional[int]
    ) -> List[Dict[str, Any]]:
        """
        Extrait les produits entre deux positions (dates de livraison)
        Supporte 2 formats:
        
        FORMAT 1 (API standard) - Multi-ligne:
        - Ligne 1: Code article (ex: 101852)
        - Ligne 2: [X] Description partie 1
        - Ligne 3: (Suite description ou marque)
        - Ligne 4: Quantité (ex: 432,00)
        
        FORMAT 2 (INFLIGHT/NEWREST) - Description avec code:
        - Ligne 1: Description complète - code(12345)
        - Ligne 2: Quantité
        - Ligne 3: Conditionnement
        """
        # Extraire la section de texte
        section = text[start_pos:end_pos] if end_pos else text[start_pos:]
        
        lines = section.split('\n')
        products = []
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            # FORMAT 1: Code article seul (4-6 chiffres au début de ligne)
            if re.match(r'^\d{4,6}$', line):
                code = line
                description_parts = []
                quantite = 1.0
                
                # Ligne suivante = description avec [X]
                if i + 1 < len(lines):
                    desc_line = lines[i + 1].strip()
                    if desc_line.startswith('['):
                        # Enlever le [X] du début
                        desc_clean = re.sub(r'^\[.\]\s*', '', desc_line)
                        description_parts.append(desc_clean)
                        
                        # Lignes suivantes peuvent contenir suite description ou marque
                        j = i + 2
                        while j < len(lines) and j < i + 10:  # Max 10 lignes de suite
                            next_line = lines[j].strip()
                            
                            # Si ligne vide, on arrête
                            if not next_line:
                                j += 1
                                continue
                            
                            # Si commence par nombre seul (probablement quantité ou prix)
                            if re.match(r'^\d+[,.]\d+$', next_line):
                                # C'est probablement la quantité
                                try:
                                    quantite = float(next_line.replace(',', '.'))
                                except:
                                    pass
                                j += 1
                                break
                            
                            # Si contient parenthèses = suite description ou marque
                            if '(' in next_line:
                                description_parts.append(next_line)
                            # Si tout en majuscules et court = probablement une marque ou fin
                            elif next_line.isupper() and len(next_line) < 30:
                                # Peut être une marque ou un mot-clé, on l'ajoute
                                description_parts.append(next_line)
                            # Si contient "Pièce", "Sachet", etc. = ligne d'unité
                            elif re.search(r'Pièce|Sachet|Carton|Kg|Litre', next_line, re.IGNORECASE):
                                j += 1
                                break
                            else:
                                # Autre contenu non identifié, on arrête
                                break
                            
                            j += 1
                        
                        i = j  # Avancer le curseur
                
                # Construire description complète
                description = ' '.join(description_parts).strip()
                
                # Nettoyer description
                description = re.sub(r'\s+', ' ', description)  # Normaliser espaces
                
                if description and len(description) > 5:
                    products.append({
                        "codeArticle": code,
                        "libelle": description,
                        "quantite": quantite,
                        "commentaire": ""
                    })
                    
                    if self.debug:
                        print(f"      ✓ {code}: {description[:60]}... (qty: {quantite})")
            
            # FORMAT 2: Description avec code entre parenthèses
            elif '(' in line and ')' in line and len(line) > 20:
                # Extraire code entre parenthèses (ex: "(64417)")
                code_match = re.search(r'\((\d{4,6})\)', line)
                if code_match:
                    code = code_match.group(1)
                    # Description = tout avant les parenthèses
                    description = line[:code_match.start()].strip()
                    
                    # Ligne suivante = quantité
                    quantite = 1.0
                    if i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        # Si c'est un nombre seul
                        if re.match(r'^\d+$', next_line):
                            try:
                                quantite = float(next_line)
                            except:
                                pass
                    
                    # Nettoyer description
                    description = re.sub(r'\s+', ' ', description)
                    
                    if description and len(description) > 5:
                        products.append({
                            "codeArticle": code,
                            "libelle": description,
                            "quantite": quantite,
                            "commentaire": ""
                        })
                        
                        if self.debug:
                            print(f"      ✓ {code}: {description[:60]}... (qty: {quantite})")
                    
                    i += 2  # Sauter la ligne de quantité
                    continue
            
            i += 1
        
        if self.debug:
            print(f"    🛒 {len(products)} produit(s) extraits")
        
        return products
    
    def build_json_structure(
        self,
        header_info: Dict[str, Any],
        delivery_dates: List[Tuple[int, str]],
        text: str
    ) -> Dict[str, Any]:
        """
        Construit la structure JSON finale
        """
        commandes = []
        num_ligne_global = 1
        
        # Heure actuelle
        now = datetime.now()
        heure_commande = int(now.strftime("%H%M%S"))
        
        # Traiter chaque date de livraison
        for idx, (date_pos, date_str) in enumerate(delivery_dates, 1):
            # Position de fin = début de la prochaine date (ou fin du document)
            end_pos = delivery_dates[idx][0] if idx < len(delivery_dates) else None
            
            # Extraire produits
            produits = self.extract_products_between_dates(text, date_pos, end_pos)
            
            if not produits:
                if self.debug:
                    print(f"    ⚠️  Aucun produit pour la date {idx}")
                continue
            
            # Parser la date de livraison
            date_livraison = self.parse_date(date_str)
            if not date_livraison:
                date_livraison = int(now.strftime("%Y%m%d"))
                if self.debug:
                    print(f"    ⚠️  Date non parsée, utilisation date actuelle")
            
            # Numérotation globale des lignes
            for prod in produits:
                prod["numLigne"] = num_ligne_global
                num_ligne_global += 1
            
            # Construire numCommande
            code_etab = header_info.get('codeEtablissement', '00000')
            num_cmd = header_info.get('numeroCommande', '00000')
            num_commande = f"{code_etab}-{num_cmd}-{idx}"
            
            # Construire la commande
            commande = {
                "entete": {
                    "origine": header_info.get('origine', ''),
                    "codeEtablissement": code_etab,
                    "codeFournisseur": header_info.get('codeFournisseur', ''),
                    "codePostal": header_info.get('codePostal', ''),
                    "numCommande": num_commande,
                    "idCommande": num_commande,
                    "dateCommande": header_info.get('dateCommande', int(now.strftime("%Y%m%d"))),
                    "heureCommande": heure_commande,
                    "dateLivraison": date_livraison,
                    "commentaireEntete": "",
                    "modeTransport": FORCED_MODE_TRANSPORT,
                    "typeCommande": FORCED_TYPE_COMMANDE,
                    "origineCommande": FORCED_ORIGINE_COMMANDE,
                    "version": FORCED_VERSION
                },
                "detailCommande": {
                    "produits": produits,
                    "nbLignes": len(produits)
                }
            }
            
            commandes.append(commande)
        
        return {"commandes": commandes}
    
    def process_pdf(self, pdf_path: Path, output_dir: Path) -> List[Path]:
        """Traite un PDF et génère les fichiers JSON"""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\n{'='*60}")
        print(f"📄 Traitement: {pdf_path.name}")
        print(f"{'='*60}")
        
        # Extraction du texte
        print("[1/4] Extraction du texte...")
        text = self.extract_text_from_pdf(pdf_path)
        
        if not text or len(text.strip()) < 50:
            print("❌ PDF vide ou illisible")
            return []
        
        print(f"  ✓ {len(text)} caractères extraits")
        
        # Détection des dates de livraison
        print("[2/4] Détection des dates de livraison...")
        delivery_dates = self.detect_delivery_dates(text)
        
        if not delivery_dates:
            print("❌ Aucune date de livraison détectée")
            return []
        
        print(f"  ✓ {len(delivery_dates)} date(s) détectée(s)")
        
        # Extraction des informations d'en-tête
        print("[3/4] Extraction des informations...")
        header_info = self.extract_header_info(text)
        
        # Construction de la structure JSON
        print("[4/4] Génération des JSON...")
        data = self.build_json_structure(header_info, delivery_dates, text)
        
        # Génération des fichiers
        generated_files = []
        commandes = data.get("commandes", [])
        
        if not commandes:
            print("\n⚠️ Aucune commande à générer")
            return []
        
        print(f"\n📦 Génération de {len(commandes)} fichier(s) JSON...")
        
        for cmd in commandes:
            entete = cmd.get("entete", {})
            num_commande = entete.get("numCommande", "unknown")
            id_commande = entete.get("idCommande", num_commande)
            
            # Nom de fichier
            output_path = output_dir / f"{id_commande}.json"
            
            try:
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump({"commandes": [cmd]}, f, ensure_ascii=False, indent=2)
                generated_files.append(output_path)
                
                # Affichage
                nb_produits = cmd.get("detailCommande", {}).get("nbLignes", 0)
                date_livraison = entete.get("dateLivraison", "")
                print(f"  ✅ {output_path.name} → {nb_produits} produit(s), livraison: {date_livraison}")
            except Exception as e:
                print(f"  ❌ Erreur écriture {output_path.name}: {e}")
        
        return generated_files


def main():
    """Point d'entrée principal"""
    parser = argparse.ArgumentParser(
        description="OCR Structuré - Extraction universelle de bons de commande"
    )
    parser.add_argument("--input", required=True, help="PDF ou dossier de PDFs")
    parser.add_argument("--out-dir", required=True, help="Dossier de sortie pour les JSON")
    parser.add_argument("--agences-file", required=True, help="Fichier agencesPAP.txt")
    parser.add_argument("--clients-file", required=True, help="Fichier clients.txt")
    parser.add_argument("--debug", action="store_true", help="Mode debug")
    
    args = parser.parse_args()
    
    in_path = Path(args.input)
    out_dir = Path(args.out_dir)
    agences_file = Path(args.agences_file)
    clients_file = Path(args.clients_file)
    
    # Liste des PDFs
    if in_path.is_dir():
        pdfs = sorted(in_path.glob("*.pdf"))
    elif in_path.is_file() and in_path.suffix.lower() == ".pdf":
        pdfs = [in_path]
    else:
        raise SystemExit("❌ --input doit être un PDF ou un dossier")
    
    if not pdfs:
        raise SystemExit("❌ Aucun PDF trouvé")
    
    print(f"\n{'='*60}")
    print(f"🚀 OCR Structuré (Parsing Intelligent)")
    print(f"📄 {len(pdfs)} PDF(s) à traiter")
    print(f"📁 Sortie: {out_dir}")
    print(f"{'='*60}\n")
    
    # Initialisation
    extractor = StructuredExtractor(
        agences_file=agences_file,
        clients_file=clients_file,
        debug=args.debug
    )
    
    success_count = 0
    error_count = 0
    
    for pdf in pdfs:
        try:
            generated = extractor.process_pdf(pdf, out_dir)
            if generated:
                print(f"\n✅ Succès: {len(generated)} fichier(s) JSON")
                success_count += 1
            else:
                print(f"\n❌ Échec: aucun JSON généré")
                error_count += 1
        except Exception as e:
            print(f"\n❌ Erreur: {e}")
            if args.debug:
                import traceback
                traceback.print_exc()
            error_count += 1
    
    print(f"\n{'='*60}")
    print(f"📊 RÉSUMÉ")
    print(f"{'='*60}")
    print(f"  ✅ Succès: {success_count}/{len(pdfs)}")
    print(f"  ❌ Erreurs: {error_count}/{len(pdfs)}")
    print(f"  ⚡ Mode: Parsing structuré (rapide et fiable)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
