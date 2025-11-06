from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
from pathlib import Path
import json
import tempfile
import subprocess
import sys

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'
app.config['UPLOAD_FOLDER'] = Path(tempfile.gettempdir()) / 'ocr_uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max
app.config['UPLOAD_FOLDER'].mkdir(exist_ok=True)

# Configurations par défaut
AGENCES_FILE = Path("Données/refs/agencesPAP.txt")
CLIENTS_FILE = Path("Données/refs/clients.txt")
OUT_DIR = Path("Données/resultats")
PATTERNS_DIR = Path("patterns")

@app.route('/')
def index():
    # Charger la liste des clients entraînés
    clients = []
    if PATTERNS_DIR.exists():
        for client_dir in PATTERNS_DIR.glob("CLIENT_*"):
            metadata_file = client_dir / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                        clients.append(client_dir.name)
                except:
                    pass
    return render_template('index.html', clients=sorted(clients))

@app.route('/training')
def training():
    """Page d'entraînement"""
    # Charger les statistiques des clients
    clients = []
    if PATTERNS_DIR.exists():
        for client_dir in PATTERNS_DIR.glob("CLIENT_*"):
            metadata_file = client_dir / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                        patterns = metadata.get('patterns_detectes', {})
                        
                        # Compter les exemples
                        examples_count = patterns.get('nb_exemples', 0) or 0
                        
                        # Compter les patterns (training files)
                        patterns_count = len(list(client_dir.glob("training_*.txt")))
                        
                        # Date de dernière modification
                        training_date = "Récemment"
                        if metadata_file.stat().st_mtime:
                            from datetime import datetime
                            dt = datetime.fromtimestamp(metadata_file.stat().st_mtime)
                            training_date = dt.strftime("%d/%m/%y")
                        
                        clients.append({
                            'name': client_dir.name,
                            'examples_count': examples_count,
                            'patterns_count': patterns_count,
                            'training_date': training_date
                        })
                except Exception as e:
                    print(f"⚠️  Erreur lecture metadata {client_dir}: {e}")
                    pass
    
    return render_template('training.html', clients=sorted(clients, key=lambda x: x['name']))

@app.route('/train', methods=['POST'])
def train():
    """Endpoint pour entraîner un nouveau client"""
    client_id = request.form.get('client_id', '').strip()
    
    if 'bc_file' not in request.files or 'json_file' not in request.files:
        flash('Fichiers BC et JSON requis', 'error')
        return redirect(url_for('training'))
    
    bc_file = request.files['bc_file']
    json_file = request.files['json_file']
    
    if not client_id:
        flash('ID client requis', 'error')
        return redirect(url_for('training'))
    
    if bc_file.filename == '' or json_file.filename == '':
        flash('Fichiers BC et JSON requis', 'error')
        return redirect(url_for('training'))
    
    try:
        # Sauvegarder les fichiers temporairement
        temp_dir = Path(tempfile.mkdtemp())
        bc_path = temp_dir / bc_file.filename
        json_path = temp_dir / json_file.filename
        
        bc_file.save(str(bc_path))
        json_file.save(str(json_path))
        
        # Exécuter l'entraînement
        cmd = [
            sys.executable,
            'Administration/ocr_train.py',
            '--client-id', client_id,
            '--bc-samples', str(bc_path),
            '--expected-json', str(json_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path.cwd())
        
        # Nettoyer
        try:
            bc_path.unlink()
            json_path.unlink()
            temp_dir.rmdir()
        except:
            pass
        
        if result.returncode == 0:
            flash(f'✅ Client {client_id} entraîné avec succès !', 'success')
            return redirect(url_for('training'))
        else:
            error_msg = result.stderr if result.stderr else "Erreur inconnue"
            flash(f'❌ Erreur lors de l\'entraînement: {error_msg[:200]}', 'error')
            return redirect(url_for('training'))
            
    except Exception as e:
        flash(f'❌ Erreur: {str(e)}', 'error')
        return redirect(url_for('training'))

@app.route('/evaluate/<client_id>')
def evaluate(client_id):
    """Évaluer la précision d'un client"""
    try:
        cmd = [
            sys.executable,
            'Administration/ocr_evaluate.py',
            '--client-id', client_id
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path.cwd())
        
        if result.returncode == 0:
            # Parser la sortie pour extraire la précision
            output = result.stdout
            precision = 0.0
            
            # Chercher la ligne de précision
            for line in output.split('\n'):
                if 'Précision globale' in line or 'précision' in line.lower():
                    try:
                        # Extraire le pourcentage
                        import re
                        match = re.search(r'(\d+\.?\d*)%', line)
                        if match:
                            precision = float(match.group(1))
                    except:
                        pass
            
            return jsonify({'success': True, 'precision': precision, 'output': output})
        else:
            return jsonify({'success': False, 'error': result.stderr}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'files' not in request.files:
        flash('Aucun fichier sélectionné', 'error')
        return redirect(url_for('index'))
    
    files = request.files.getlist('files')
    client_id = request.form.get('client_id', 'UNKNOWN')
    
    if not files or files[0].filename == '':
        flash('Aucun fichier sélectionné', 'error')
        return redirect(url_for('index'))
    
    # Vérifier que tous les fichiers sont des PDFs
    for file in files:
        if not file.filename.endswith('.pdf'):
            flash(f'Fichier {file.filename}: seuls les fichiers PDF sont acceptés', 'error')
            return redirect(url_for('index'))
    
    try:
        all_commandes = []
        processed_files = []
        
        # Traiter chaque fichier
        for file in files:
            # Sauvegarder temporairement
            temp_path = app.config['UPLOAD_FOLDER'] / file.filename
            file.save(str(temp_path))
            
            # Exécuter ocr_smart.py
            cmd = [
                sys.executable,
                'Production/ocr_smart.py',
                '--input', str(temp_path),
                '--out-dir', str(OUT_DIR),
                '--agences-file', str(AGENCES_FILE),
                '--clients-file', str(CLIENTS_FILE)
            ]
            
            # Capturer le timestamp AVANT traitement
            import time
            timestamp_avant = time.time()
            
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path.cwd())
            
            if result.returncode == 0:
                # Attendre que les fichiers soient écrits
                time.sleep(0.5)
                
                # Charger UNIQUEMENT les fichiers JSON modifiés/créés APRÈS le traitement
                json_files = [
                    f for f in OUT_DIR.glob('*.json')
                    if f.stat().st_mtime > timestamp_avant
                ]
                
                # Trier par nom de fichier (ordre croissant: -1, -2, -3)
                json_files = sorted(json_files, key=lambda p: p.name)
                
                print(f"DEBUG: {len(json_files)} fichiers JSON créés pour {file.filename}")
                
                # Charger uniquement les fichiers générés pour CE bon de commande
                nb_files_loaded = 0
                for json_file in json_files:  # Tous les nouveaux fichiers pour ce BC
                    try:
                        print(f"DEBUG: Chargement de {json_file.name}")
                        with open(json_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            commandes = data.get('commandes', [])
                            for cmd_data in commandes:
                                # Ajouter l'info du fichier source
                                if 'entete' not in cmd_data:
                                    cmd_data['entete'] = {}
                                cmd_data['entete']['_source_file'] = file.filename
                                all_commandes.append(cmd_data)
                                nb_files_loaded += 1
                    except Exception as e:
                        print(f"⚠️  Erreur lecture JSON {json_file}: {e}")
                        pass
                
                if nb_files_loaded > 0:
                    processed_files.append(file.filename)
                else:
                    print(f"WARNING: Aucun fichier JSON créé pour {file.filename}")
                    flash(f'Aucun JSON généré pour {file.filename}', 'warning')
            else:
                error_msg = result.stderr if result.stderr else "Erreur inconnue"
                flash(f'Erreur lors du traitement de {file.filename}: {error_msg[:100]}', 'warning')
            
            # Nettoyer le fichier temporaire
            try:
                temp_path.unlink()
            except:
                pass
        
        if not all_commandes:
            flash('Aucune commande valide extraite des fichiers', 'warning')
            return redirect(url_for('index'))
        
        print(f"DEBUG: {len(all_commandes)} commandes chargées")
        print(f"DEBUG: {len(processed_files)} fichiers traités")
        
        flash(f'{len(processed_files)} fichier(s) traité(s) avec succès', 'success')
        
        # Préparer les données pour le nouveau template results.html
        results = []
        total_products = 0
        
        for i, cmd_data in enumerate(all_commandes):
            entete = cmd_data.get('entete', {})
            detail = cmd_data.get('detailCommande', {})
            products = detail.get('produits', [])
            total_products += len(products)
            
            # Construire le nom du fichier
            num_commande = entete.get('numCommande', entete.get('idCommande', f'commande_{i+1}'))
            filename = f"{num_commande}.json"
            
            results.append({
                'filename': filename,
                'data': {
                    'numeroBon': entete.get('numCommande', entete.get('idCommande', '')),
                    'numeroClient': entete.get('codeEtablissement', ''),
                    'dateCommande': str(entete.get('dateCommande', '')),
                    'dateLivraison': str(entete.get('dateLivraison', '')),
                    'agence': entete.get('codeFournisseur', ''),
                    'entite': entete.get('origine', ''),
                    'produitsCommandes': products
                }
            })
        
        try:
            return render_template('results.html', 
                                 results=results, 
                                 total_products=total_products,
                                 client_id=client_id)
        except Exception as e:
            print(f"ERROR render_template: {e}")
            import traceback
            traceback.print_exc()
            flash(f'Erreur affichage résultats: {str(e)}', 'error')
            return redirect(url_for('index'))
    
    except Exception as e:
        flash(f'Erreur lors du traitement: {str(e)}', 'error')
        return redirect(url_for('index'))

if __name__ == '__main__':
    # Créer les dossiers nécessaires
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    app.config['UPLOAD_FOLDER'].mkdir(parents=True, exist_ok=True)
    
    # Vérifier que les fichiers de référence existent
    if not AGENCES_FILE.exists():
        print(f"⚠️  ATTENTION: {AGENCES_FILE} introuvable")
    if not CLIENTS_FILE.exists():
        print(f"⚠️  ATTENTION: {CLIENTS_FILE} introuvable")
    
    print("\n" + "="*60)
    print("🚀 Interface OCR PRO A PRO - Version 2.0")
    print("="*60)
    print("📁 Ouvrez votre navigateur à: http://localhost:5001")
    print("📊 Pages disponibles:")
    print("   - http://localhost:5001/         (Extraction)")
    print("   - http://localhost:5001/training (Entraînement)")
    print("="*60 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5001)
