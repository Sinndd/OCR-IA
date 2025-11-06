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
                        clients.append({
                            'id': metadata.get('client_id', ''),
                            'nb_exemples': metadata.get('patterns_detectes', {}).get('nb_exemples', 0)
                        })
                except:
                    pass
    return render_template('index.html', clients=clients)

@app.route('/training')
def training():
    """Page d'entraînement"""
    # Charger les statistiques des clients
    clients_stats = []
    if PATTERNS_DIR.exists():
        for client_dir in PATTERNS_DIR.glob("CLIENT_*"):
            metadata_file = client_dir / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                        patterns = metadata.get('patterns_detectes', {})
                        stats = metadata.get('statistiques', {})
                        
                        # Gérer le cas où taux_reussite peut être None
                        taux = stats.get('taux_reussite', 1.0)
                        if taux is None:
                            taux = 1.0
                        
                        # Gérer le cas où filename_convention peut être None
                        convention = patterns.get('filename_convention', 'Non définie')
                        if convention is None:
                            convention = 'Non définie'
                        
                        clients_stats.append({
                            'id': metadata.get('client_id', 'UNKNOWN'),
                            'nb_exemples': patterns.get('nb_exemples', 0) or 0,
                            'nb_bc_traites': stats.get('nb_bc_traites', 0) or 0,
                            'taux_reussite': float(taux) * 100,
                            'derniere_utilisation': stats.get('derniere_utilisation', 'Jamais') or 'Jamais',
                            'convention': str(convention)
                        })
                except Exception as e:
                    print(f"⚠️  Erreur lecture metadata {client_dir}: {e}")
                    pass
    
    return render_template('training.html', clients=clients_stats)

@app.route('/train', methods=['POST'])
def train():
    """Endpoint pour entraîner un nouveau client"""
    client_id = request.form.get('client_id', '').strip()
    bc_files = request.files.getlist('bc_files')
    json_files = request.files.getlist('json_files')
    
    if not client_id:
        return jsonify({'success': False, 'error': 'ID client requis'}), 400
    
    if not bc_files or not json_files:
        return jsonify({'success': False, 'error': 'Fichiers BC et JSON requis'}), 400
    
    if len(bc_files) != len(json_files):
        return jsonify({'success': False, 'error': 'Nombre de BC et JSON doit correspondre'}), 400
    
    try:
        # Sauvegarder les fichiers temporairement
        temp_dir = Path(tempfile.mkdtemp())
        bc_paths = []
        json_paths = []
        
        for bc_file in bc_files:
            bc_path = temp_dir / bc_file.filename
            bc_file.save(str(bc_path))
            bc_paths.append(str(bc_path))
        
        for json_file in json_files:
            json_path = temp_dir / json_file.filename
            json_file.save(str(json_path))
            json_paths.append(str(json_path))
        
        # Exécuter l'entraînement
        cmd = [
            sys.executable,
            'Administration/ocr_train.py',
            '--client-id', client_id,
            '--bc-samples'] + bc_paths + [
            '--expected-json'] + json_paths
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path.cwd())
        
        # Nettoyer
        for path in bc_paths + json_paths:
            try:
                Path(path).unlink()
            except:
                pass
        try:
            temp_dir.rmdir()
        except:
            pass
        
        if result.returncode == 0:
            return jsonify({'success': True, 'message': f'Client {client_id} entraîné avec succès'})
        else:
            return jsonify({'success': False, 'error': result.stderr}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

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
                
                # Trier par date de modification (plus récent en premier)
                json_files = sorted(json_files, key=lambda p: p.stat().st_mtime, reverse=True)
                
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
        
        try:
            return render_template('results.html', commandes=all_commandes, filenames=processed_files)
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
