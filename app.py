from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_socketio import SocketIO, emit
import os
from pathlib import Path
import json
import tempfile
import subprocess
import sys
import hmac
from functools import wraps

# Import job management
from job_manager import JobManager, JobStatus
from job_processor import JobProcessor

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'
app.config['UPLOAD_FOLDER'] = Path(tempfile.gettempdir()) / 'ocr_uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max
app.config['UPLOAD_FOLDER'].mkdir(exist_ok=True)

# Initialiser SocketIO pour le temps réel
socketio = SocketIO(app, cors_allowed_origins="*")

# Configurations par défaut
AGENCES_FILE = Path("Données/refs/agencesPAP.txt")
CLIENTS_FILE = Path("Données/refs/clients.txt")
OUT_DIR = Path("Données/resultats")
PATTERNS_DIR = Path("patterns")
METRICS_FILE = Path("Données/metrics.json")

# Initialiser le système de jobs
job_manager = JobManager(db_path="jobs.db")

# Clé API pour sécuriser les routes REST (n8n / intégrations externes)
API_KEY = os.environ.get("OCR_API_KEY")
if not API_KEY:
    API_KEY = "dev-only-insecure-key"
    print("⚠️  OCR_API_KEY non défini : utilisation d'une clé de développement. "
          "Définissez la variable d'environnement OCR_API_KEY en production.")


def require_api_key(f):
    """Exige un header X-API-KEY valide (401 sinon) sur les routes de l'API REST."""
    @wraps(f)
    def decorated(*args, **kwargs):
        provided_key = request.headers.get("X-API-KEY", "")
        if not provided_key or not hmac.compare_digest(provided_key, API_KEY):
            return jsonify({"success": False, "error": "Unauthorized: clé API manquante ou invalide"}), 401
        return f(*args, **kwargs)
    return decorated

def notify_job_update(job_id: str):
    """Callback pour notifier les clients WebSocket"""
    try:
        job = job_manager.get_job(job_id)
        if job:
            socketio.emit('job_update', job, namespace='/')
    except Exception as e:
        print(f"⚠️ Erreur notification WebSocket: {e}")

job_processor = JobProcessor(
    job_manager=job_manager,
    patterns_dir=PATTERNS_DIR,
    agences_file=AGENCES_FILE,
    clients_file=CLIENTS_FILE,
    out_dir=OUT_DIR,
    on_job_update=notify_job_update
)

def load_metrics():
    """Charge les métriques depuis le fichier JSON"""
    if METRICS_FILE.exists():
        try:
            with open(METRICS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {
        "extractions": [],
        "clients": {},
        "global_stats": {
            "total_extractions": 0,
            "total_products": 0,
            "total_validated": 0,
            "total_corrected": 0
        }
    }

def save_metrics(metrics):
    """Sauvegarde les métriques dans le fichier JSON"""
    try:
        METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(METRICS_FILE, 'w', encoding='utf-8') as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️  Erreur sauvegarde métriques: {e}")

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
                        json.load(f)
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
    
    # Stats RAG
    rag_stats = {'documents': 0, 'clients': 0}
    try:
        from training.rag_system import DocumentStore
        persist_dir = Path('training/faiss_index')
        if persist_dir.exists():
            store = DocumentStore(persist_dir=persist_dir)
            stats = store.get_stats()
            rag_stats['documents'] = stats.get('total_documents', 0)
            # Compter les clients uniques
            clients_set = set()
            for meta in store.metadatas:
                if 'client' in meta:
                    clients_set.add(meta['client'])
            rag_stats['clients'] = len(clients_set)
    except Exception as e:
        print(f"⚠️  Erreur chargement stats RAG: {e}")
    
    return render_template('training.html', clients=sorted(clients, key=lambda x: x['name']), rag_stats=rag_stats)

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
    
    # Vérifier le format du BC
    bc_ext = Path(bc_file.filename).suffix.lower()
    if bc_ext not in ['.pdf', '.html', '.htm', '.txt']:
        flash(f'Format BC non supporté: {bc_ext}. Formats acceptés: PDF, HTML, TXT', 'error')
        return redirect(url_for('training'))
    
    # Vérifier le format JSON
    json_ext = Path(json_file.filename).suffix.lower()
    if json_ext != '.json':
        flash('Le fichier attendu doit être au format JSON', 'error')
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

@app.route('/results')
def results():
    """Affiche les résultats stockés en session"""
    results_data = session.get('results', [])
    total_products = session.get('total_products', 0)
    client_id = session.get('client_id', None)
    file_formats = session.get('file_formats', 'PDF')
    detected_clients = session.get('detected_clients', 'Auto-détecté')
    
    if not results_data:
        flash('Aucun résultat disponible. Veuillez d\'abord traiter des fichiers.', 'warning')
        return redirect(url_for('index'))
    
    # Charger les métriques pour récupérer le statut de chaque résultat
    metrics = load_metrics()
    
    # Associer le statut à chaque résultat
    for result in results_data:
        result['status'] = 'pending'  # Par défaut
        for extraction in metrics.get('extractions', []):
            if extraction['filename'] == result['filename']:
                result['status'] = extraction.get('status', 'pending')
                break
    
    return render_template('results.html',
                         results=results_data,
                         total_products=total_products,
                         client_id=client_id,
                         file_formats=file_formats,
                         detected_clients=detected_clients)

@app.route('/stats')
def stats():
    """Page de statistiques en temps réel"""
    metrics = load_metrics()
    
    # Formater les timestamps pour l'affichage
    from datetime import datetime
    for extraction in metrics.get('extractions', []):
        if 'timestamp' in extraction and isinstance(extraction['timestamp'], (int, float)):
            extraction['timestamp'] = datetime.fromtimestamp(extraction['timestamp']).strftime('%d/%m/%Y %H:%M')
    
    return render_template('stats.html', stats=metrics)


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'files' not in request.files:
        flash('Aucun fichier sélectionné', 'error')
        return redirect(url_for('index'))
    
    files = request.files.getlist('files')
    # Pas de client_id = détection automatique
    client_id = request.form.get('client_id', None)
    
    if not files or files[0].filename == '':
        flash('Aucun fichier sélectionné', 'error')
        return redirect(url_for('index'))
    
    # Vérifier que tous les fichiers sont dans les formats acceptés
    allowed_extensions = {'.pdf', '.html', '.htm', '.txt'}
    for file in files:
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in allowed_extensions:
            flash(f'Fichier {file.filename}: formats acceptés: PDF, HTML, TXT', 'error')
            return redirect(url_for('index'))
    
    try:
        all_commandes = []
        processed_files = []
        file_formats = []  # Pour tracker les formats
        detected_clients = []  # Pour tracker les clients détectés
        
        # Traiter chaque fichier
        for file in files:
            # Récupérer le format
            file_ext = Path(file.filename).suffix.lower().replace('.', '').upper()
            if file_ext == 'HTM':
                file_ext = 'HTML'
            
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
                                # Ajouter l'info du fichier source et format
                                if 'entete' not in cmd_data:
                                    cmd_data['entete'] = {}
                                cmd_data['entete']['_source_file'] = file.filename
                                cmd_data['entete']['_file_format'] = file_ext
                                all_commandes.append(cmd_data)
                                nb_files_loaded += 1
                                
                                # Tracker le client détecté
                                origine = cmd_data.get('entete', {}).get('origine', 'Inconnu')
                                if origine not in detected_clients:
                                    detected_clients.append(origine)
                    except Exception as e:
                        print(f"⚠️  Erreur lecture JSON {json_file}: {e}")
                        pass
                
                if nb_files_loaded > 0:
                    processed_files.append(file.filename)
                    if file_ext not in file_formats:
                        file_formats.append(file_ext)
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
            
            # Réorganiser pour avoir entete avant detailCommande
            ordered_data = {
                'entete': cmd_data.get('entete', {}),
                'detailCommande': cmd_data.get('detailCommande', {})
            }
            
            results.append({
                'filename': filename,
                'data': ordered_data
            })
        
        # Stocker les résultats en session pour la page /results
        session['results'] = results
        session['total_products'] = total_products
        session['client_id'] = client_id
        session['file_formats'] = ', '.join(file_formats) if file_formats else 'PDF'
        session['detected_clients'] = ', '.join(detected_clients) if detected_clients else 'Auto-détecté'
        
        # Enregistrer les métriques
        import time
        metrics = load_metrics()
        
        # Mise à jour des stats globales
        metrics['global_stats']['total_extractions'] += len(results)
        metrics['global_stats']['total_products'] += total_products
        
        # Ajouter à l'historique - utiliser le nom du fichier JSON, pas le PDF
        for result in results:
            json_filename = result['filename']  # ex: "02323-1631-1.json"
            client_name = detected_clients[0] if detected_clients else 'Inconnu'
            products_count = len(result['data'].get('detailCommande', {}).get('produits', []))
            
            metrics['extractions'].append({
                'filename': json_filename,  # Utiliser le nom JSON pour la correspondance
                'client': client_name,
                'products': products_count,
                'timestamp': time.time(),
                'status': 'pending'
            })
            
            # Stats par client
            if client_name not in metrics['clients']:
                metrics['clients'][client_name] = {
                    'extractions': 0,
                    'products': 0,
                    'validated': 0,
                    'corrected': 0
                }
            metrics['clients'][client_name]['extractions'] += 1
            metrics['clients'][client_name]['products'] += products_count
        
        save_metrics(metrics)
        print(f"📊 Métriques sauvegardées pour {len(results)} extraction(s)")
        
        # Retourner une réponse JSON simple (succès)
        return jsonify({'success': True, 'message': 'Extraction terminée'}), 200
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Erreur: {str(e)}', 'error')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/validate', methods=['POST'])
def validate_extraction():
    """Valide, annule la validation ou corrige une extraction"""
    try:
        data = request.json
        action = data.get('action')
        filename = data.get('filename')
        
        metrics = load_metrics()
        
        if action == 'validate':
            # Marquer comme validé
            for extraction in metrics['extractions']:
                if extraction['filename'] == filename and extraction['status'] == 'pending':
                    extraction['status'] = 'validated'
                    
                    # Mettre à jour les stats client
                    client = extraction['client']
                    if client in metrics['clients']:
                        metrics['clients'][client]['validated'] += 1
                    
                    metrics['global_stats']['total_validated'] += 1
                    break
            
            save_metrics(metrics)

            # Apprentissage: Sauvegarder aussi comme exemple si validé
            try:
                import glob
                import os
                base_name = os.path.splitext(filename)[0]
                search_pattern = OUT_DIR / f"{base_name}*.json"
                candidates = glob.glob(str(search_pattern))
                
                if candidates:
                    target_file = sorted(candidates)[-1]
                    with open(target_file, 'r', encoding='utf-8') as f:
                        validated_data = json.load(f)
                    
                    # Identifier le client
                    client_origin = validated_data.get('entete', {}).get('origine', '')
                    client_id = None
                    for c_dir in PATTERNS_DIR.glob("CLIENT_*"):
                        meta = c_dir / "metadata.json"
                        if meta.exists():
                            try:
                                with open(meta, 'r', encoding='utf-8') as f:
                                    if client_origin in json.load(f).get('entreprises', []):
                                        client_id = c_dir.name.replace("CLIENT_", "")
                                        break
                            except: pass
                    
                    if not client_id:
                        client_id = client_origin.replace(' ', '_').upper()[:20]
                    
                    c_dir = PATTERNS_DIR / f"CLIENT_{client_id}"
                    c_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Sauvegarder
                    next_n = len(list(c_dir.glob("training_json_*.json"))) + 1
                    p_file = c_dir / f"training_json_{next_n}.json"
                    with open(p_file, 'w', encoding='utf-8') as f:
                        json.dump(validated_data, f, indent=2, ensure_ascii=False)
                        
                    # Invalider cache
                    cache = PATTERNS_DIR / "patterns_cache.json"
                    if cache.exists(): cache.unlink()
            except Exception as e:
                print(f"Warning: Could not save validated example: {e}")

            return jsonify({'success': True, 'message': 'Extraction validée et apprise'})
        
        elif action == 'unvalidate':
            # Annuler la validation
            for extraction in metrics['extractions']:
                if extraction['filename'] == filename and extraction['status'] == 'validated':
                    extraction['status'] = 'pending'
                    
                    # Mettre à jour les stats client
                    client = extraction['client']
                    if client in metrics['clients']:
                        metrics['clients'][client]['validated'] = max(0, metrics['clients'][client]['validated'] - 1)
                    
                    metrics['global_stats']['total_validated'] = max(0, metrics['global_stats']['total_validated'] - 1)
                    break
            
            save_metrics(metrics)
            return jsonify({'success': True, 'message': 'Validation annulée'})
            
        elif action == 'correct':
            # Sauvegarder la correction comme nouvel exemple d'entraînement
            corrected_data = data.get('corrected_data')
            multi_commandes = data.get('multi_commandes', False)
            
            if not corrected_data:
                return jsonify({'success': False, 'error': 'Données corrigées manquantes'}), 400
            
            # Gérer le cas multi-commandes
            if multi_commandes and 'commandes' in corrected_data:
                commandes = corrected_data['commandes']
            elif 'commandes' in corrected_data:
                commandes = corrected_data['commandes']
            else:
                # Format à plat: une seule commande
                commandes = [corrected_data]
            
            # Détecter le client depuis l'origine (première commande)
            first_cmd = commandes[0] if commandes else {}
            client_origin = first_cmd.get('entete', {}).get('origine', '')
            client_id = None
            
            # Chercher le client correspondant
            for client_dir in PATTERNS_DIR.glob("CLIENT_*"):
                metadata_file = client_dir / "metadata.json"
                if metadata_file.exists():
                    try:
                        with open(metadata_file, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                            if client_origin in metadata.get('entreprises', []):
                                client_id = client_dir.name.replace("CLIENT_", "")
                                break
                    except:
                        pass
            
            if not client_id:
                # Créer un nouveau client si nécessaire
                client_id = client_origin.replace(' ', '_').upper()[:20]
            
            client_dir = PATTERNS_DIR / f"CLIENT_{client_id}"
            client_dir.mkdir(parents=True, exist_ok=True)
            
            # Sauvegarder chaque commande comme exemple d'entraînement
            import glob
            import os
            
            for idx, cmd in enumerate(commandes):
                # Compter les exemples existants
                existing_jsons = list(client_dir.glob("training_json_*.json"))
                next_num = len(existing_jsons) + 1
                
                # Sauvegarder le JSON corrigé
                json_file = client_dir / f"training_json_{next_num}.json"
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(cmd, f, indent=2, ensure_ascii=False)
                
                print(f"✅ Commande {idx + 1}/{len(commandes)} sauvegardée: {json_file}")
            
            # Mettre à jour le fichier résultat original (pour l'affichage UI)
            base_name = os.path.splitext(filename)[0]
            
            # Si plusieurs commandes, créer plusieurs fichiers de sortie
            if len(commandes) > 1:
                for idx, cmd in enumerate(commandes):
                    # Construire le nom du fichier avec suffixe si nécessaire
                    num_cmd = cmd.get('entete', {}).get('numCommande', '') or cmd.get('entete', {}).get('idCommande', '')
                    if num_cmd:
                        out_filename = f"{num_cmd}.json"
                    else:
                        out_filename = f"{base_name}-{idx + 1}.json"
                    
                    out_file = OUT_DIR / out_filename
                    with open(out_file, 'w', encoding='utf-8') as f:
                        json.dump(cmd, f, indent=2, ensure_ascii=False)
                    print(f"📄 Fichier résultat mis à jour: {out_file}")
            else:
                # Une seule commande: mettre à jour le fichier existant
                # Chercher par le nom de base (sans extension)
                search_pattern = str(OUT_DIR / f"{base_name}*.json")
                print(f"🔍 Recherche du fichier à mettre à jour: {search_pattern}")
                candidates = glob.glob(search_pattern)
                print(f"📂 Fichiers trouvés: {candidates}")
                if candidates:
                    target_file = sorted(candidates)[-1]
                    print(f"✏️ Mise à jour du fichier: {target_file}")
                    with open(target_file, 'w', encoding='utf-8') as f:
                        json.dump(commandes[0], f, indent=2, ensure_ascii=False)
                    print(f"✅ Fichier sauvegardé avec succès")
                else:
                    # Créer un nouveau fichier si aucun n'existe
                    out_file = OUT_DIR / f"{base_name}.json"
                    print(f"📝 Création d'un nouveau fichier: {out_file}")
                    with open(out_file, 'w', encoding='utf-8') as f:
                        json.dump(commandes[0], f, indent=2, ensure_ascii=False)
            
            # Mettre à jour les métriques
            for extraction in metrics['extractions']:
                if extraction['filename'] == filename:
                    # Si déjà validé/corrigé, ne rien changer
                    if extraction['status'] == 'pending':
                        # Marquer comme corrigé
                        extraction['status'] = 'corrected'
                        
                        # Mettre à jour les stats client
                        client = extraction['client']
                        if client in metrics['clients']:
                            metrics['clients'][client]['corrected'] += 1
                        
                        metrics['global_stats']['total_corrected'] += 1
                        print(f"📊 Métriques mises à jour: {filename} -> corrected")
                    break
            
            save_metrics(metrics)
            
            # Invalider le cache des patterns
            cache_file = PATTERNS_DIR / "patterns_cache.json"
            if cache_file.exists():
                cache_file.unlink()
            
            return jsonify({
                'success': True, 
                'message': f'{len(commandes)} commande(s) corrigée(s) et sauvegardée(s) pour {client_id}'
            })
        
        else:
            return jsonify({'success': False, 'error': 'Action inconnue'}), 400
            
    except Exception as e:
        print(f"ERROR validation: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# API REST pour n8n
# ============================================================

@app.route('/api/extract', methods=['POST'])
@require_api_key
def api_extract():
    """
    API d'extraction pour n8n
    Upload un BC et retourne un job_id pour suivi
    """
    if not request.files:
        return jsonify({'success': False, 'error': 'Aucun fichier reçu'}), 400
    
    # Prendre le premier fichier trouvé, peu importe la clé (file, attachment_0, etc.)
    file = next(iter(request.files.values()))
    
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Nom de fichier vide'}), 400
    
    # Vérifier le format
    allowed_extensions = {'.pdf', '.html', '.htm', '.txt'}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        return jsonify({
            'success': False,
            'error': f'Format non supporté: {file_ext}. Formats: PDF, HTML, TXT'
        }), 400
    
    try:
        # Créer un dossier pour les uploads API
        api_upload_dir = app.config['UPLOAD_FOLDER'] / 'api_uploads'
        api_upload_dir.mkdir(parents=True, exist_ok=True)
        
        # Sauvegarder le fichier
        file_path = api_upload_dir / file.filename
        file.save(str(file_path))
        
        # Récupérer metadata optionnelle
        metadata = {}
        if request.form.get('metadata'):
            try:
                metadata = json.loads(request.form.get('metadata'))
            except:
                pass
        
        # Créer un job
        job_id = job_manager.create_job(
            filename=file.filename,
            input_path=str(file_path),
            metadata=metadata
        )
        
        # Soumettre pour traitement
        job_processor.submit_job(job_id)
        
        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'Job créé avec succès'
        }), 201
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/result/<job_id>', methods=['GET'])
@require_api_key
def api_get_result(job_id):
    """
    API: Renvoie TOUS les JSONs correspondant au job_id.
    Renvoie une liste : { "success": true, "results": [ {...}, {...} ] }
    """
    import glob
    import os
    import time
    import re
    
    # On cherche tous les fichiers qui contiennent le job_id
    # (Assure-toi que ton OCR met bien l'ID dans le nom des fichiers générés)
    # Si ton OCR renomme totalement le fichier sans garder l'ID, 
    # on utilise la méthode temporelle (les fichiers récents).
    
    # Méthode "Fichiers Récents" (plus robuste pour ton cas actuel)
    # On prend tous les JSONs du dossier modifiés dans les dernières 2 minutes
    search_pattern = str(OUT_DIR / "*.json")
    all_files = glob.glob(search_pattern)
    
    if not all_files:
        return jsonify({'success': False, 'error': 'Aucun fichier trouvé'}), 404

    current_time = time.time()
    recent_files = []
    
    for f in all_files:
        # On garde les fichiers modifiés il y a moins de 3600 secondes (1 heure)
        if current_time - os.path.getmtime(f) < 3600:
            recent_files.append(f)
            
    if not recent_files:
        return jsonify({'success': False, 'error': 'Traitement en cours (pas de fichiers récents)'}), 404

    # On lit TOUS les fichiers récents
    results_data = []
    for file_path in recent_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # On ajoute le nom du fichier pour s'y retrouver plus tard
                data['_original_filename'] = os.path.basename(file_path)
                results_data.append(data)
        except:
            continue # Si un fichier est illisible, on l'ignore

    # --- LOGIQUE DE NOMMAGE GÉNÉRALISÉE ---
    # On calcule un nom de dossier "propre" pour regrouper les fichiers
    suggested_folder_name = "Dossier_Inconnu"
    
    if results_data:
        # On regarde le premier fichier trouvé
        first_entete = results_data[0].get('entete', {})
        raw_num = first_entete.get('numCommande') or first_entete.get('idCommande') or "Inconnu"
        
        # Regex magique : enlève les suffixes type -1, -2, _1, _2 à la fin
        # Ex: "CMD-2024-001-1" devient "CMD-2024-001"
        clean_num = re.sub(r'[-_]\d+$', '', str(raw_num))
        
        suggested_folder_name = f"Commande_{clean_num}"

    return jsonify({
        "success": True, 
        "count": len(results_data),
        "results": results_data,
        "group_name": suggested_folder_name  # <--- Utilise ce champ dans n8n pour le nom du dossier !
    })


@app.route('/api/status/<job_id>', methods=['GET'])
@app.route('/api/result/<job_id>', methods=['GET'])  # Alias pour n8n
@require_api_key
def api_job_status(job_id):
    """Récupère le statut d'un job OU le contenu d'un fichier résultat par son nom"""
    print(f"🔍 Recherche du fichier: {job_id}")
    
    # Essayer d'abord de trouver le fichier directement par son nom
    import glob

    # Chercher le fichier dans le dossier de sortie
    search_pattern = str(OUT_DIR / f"{job_id}*.json")
    print(f"🔎 Pattern de recherche: {search_pattern}")
    candidates = glob.glob(search_pattern)
    print(f"📂 Fichiers trouvés: {candidates}")
    
    if candidates:
        # Fichier trouvé, le retourner
        target_file = sorted(candidates)[-1]
        print(f"✅ Fichier sélectionné: {target_file}")
        try:
            with open(target_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f"📦 Données chargées depuis {target_file}")
                return jsonify({
                    'success': True,
                    'json': json.dumps(data, ensure_ascii=False)
                })
        except Exception as e:
            return jsonify({'success': False, 'error': f'Erreur de lecture: {str(e)}'}), 500
    
    # Sinon, chercher le job par son ID
    job = job_manager.get_job(job_id)
    
    if not job:
        return jsonify({'success': False, 'error': 'Job ou fichier introuvable'}), 404
    
    return jsonify({
        'success': True,
        'job': job
    })


@app.route('/api/jobs', methods=['GET'])
@require_api_key
def api_list_jobs():
    """Liste tous les jobs (avec filtres optionnels)"""
    status_filter = request.args.get('status')
    limit = request.args.get('limit', type=int)
    
    status = None
    if status_filter:
        try:
            status = JobStatus(status_filter)
        except ValueError:
            pass
    
    jobs = job_manager.get_all_jobs(status=status, limit=limit)
    
    return jsonify({
        'success': True,
        'jobs': jobs,
        'count': len(jobs)
    })


@app.route('/api/retry/<job_id>', methods=['POST'])
@require_api_key
def api_retry_job(job_id):
    """Relance un job échoué"""
    job = job_manager.get_job(job_id)
    
    if not job:
        return jsonify({'success': False, 'error': 'Job introuvable'}), 404
    
    if job['status'] != JobStatus.FAILED.value:
        return jsonify({
            'success': False,
            'error': 'Seuls les jobs échoués peuvent être relancés'
        }), 400
    
    success = job_manager.retry_job(job_id)
    
    if success:
        # Resoumettre le job
        job_processor.submit_job(job_id)
        
        return jsonify({
            'success': True,
            'message': 'Job relancé avec succès'
        })
    else:
        return jsonify({'success': False, 'error': 'Erreur lors du retry'}), 500


# ============================================================
# Pages Web
# ============================================================

@app.route('/monitoring')
def monitoring():
    """Page de monitoring temps réel"""
    return render_template('monitoring.html')


@app.route('/failed-jobs')
def failed_jobs():
    """Page de gestion des jobs échoués"""
    return render_template('failed_jobs.html')


# ============================================================
# API RAG
# ============================================================

@app.route('/api/rag/reindex', methods=['POST'])
def api_rag_reindex():
    """Réindexer tous les patterns dans le système RAG"""
    try:
        from training.rag_system import DocumentStore, RAGIndexer
        
        persist_dir = Path('training/faiss_index')
        store = DocumentStore(persist_dir=persist_dir)
        indexer = RAGIndexer(patterns_dir=PATTERNS_DIR, document_store=store)
        indexer.index_all()
        
        stats = store.get_stats()
        return jsonify({
            'success': True,
            'message': f"✅ Indexation terminée: {stats.get('total_documents', 0)} documents",
            'documents': stats.get('total_documents', 0)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/rag/clear', methods=['POST'])
def api_rag_clear():
    """Vider l'index RAG"""
    try:
        import shutil
        persist_dir = Path('training/faiss_index')
        if persist_dir.exists():
            shutil.rmtree(persist_dir)
        return jsonify({
            'success': True,
            'message': '✅ Index RAG supprimé'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/rag/extract', methods=['POST'])
def api_rag_extract():
    """Extraire un BC avec le système RAG"""
    try:
        import time as time_module
        
        if 'file' not in request.files:
            return jsonify({'error': 'Fichier requis'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Fichier vide'}), 400
        
        # Sauvegarder temporairement
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
            file.save(tmp.name)
            tmp_path = Path(tmp.name)
        
        try:
            from training.rag_system import DocumentStore, RAGExtractor
            from training.time_predictor import ExtractionTimePredictor
            import fitz
            
            # Extraire le texte
            if tmp_path.suffix.lower() == '.pdf':
                doc = fitz.open(tmp_path)
                text = ""
                for page in doc:
                    text += page.get_text()
                doc.close()
                file_type = 'pdf'
            else:
                with open(tmp_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                file_type = 'html'
            
            # Prédiction du temps avec le modèle bayésien
            predictor = ExtractionTimePredictor()
            time_prediction = predictor.predict(
                text_length=len(text),
                nb_products=0,  # Sera estimé pendant l'extraction
                nb_dates=1,
                file_type=file_type
            )
            
            # Extraction RAG avec mesure du temps
            start_time = time_module.time()
            
            persist_dir = Path('training/faiss_index')
            store = DocumentStore(persist_dir=persist_dir)
            extractor = RAGExtractor(store)
            result, examples = extractor.extract_with_rag(text)
            
            # Temps réel d'extraction
            elapsed_time = time_module.time() - start_time
            
            # Enregistrer le temps réel pour améliorer les prédictions futures
            nb_products_extracted = 0
            if isinstance(result, dict) and 'commandes' in result:
                for cmd in result['commandes']:
                    if 'detailCommande' in cmd:
                        nb_products_extracted += len(cmd['detailCommande'])
            elif isinstance(result, list):
                for cmd in result:
                    if isinstance(cmd, dict) and 'detailCommande' in cmd:
                        nb_products_extracted += len(cmd['detailCommande'])
            
            predictor.record(
                text_length=len(text),
                nb_products=nb_products_extracted,
                nb_dates=1,
                file_type=file_type,
                actual_time=elapsed_time
            )
            
            # Déterminer le client
            client = "Inconnu"
            if examples:
                client = examples[0].get('metadata', {}).get('client', 'Inconnu')
            
            # Compter les commandes
            nb_commandes = 1
            if isinstance(result, dict) and 'commandes' in result:
                nb_commandes = len(result['commandes'])
            elif isinstance(result, list):
                nb_commandes = len(result)
            
            return jsonify({
                'success': True,
                'result': result,
                'client': client,
                'nb_commandes': nb_commandes,
                'nb_products': nb_products_extracted,
                'time': {
                    'estimated': round(time_prediction['estimated_seconds'], 1),
                    'actual': round(elapsed_time, 1),
                    'interval': time_prediction['confidence_interval']
                },
                'score': 100  # TODO: Ajouter le vrai score
            })
        finally:
            tmp_path.unlink(missing_ok=True)
            
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


@app.route('/api/rag/stats', methods=['GET'])
def api_rag_stats():
    """Statistiques du système RAG"""
    try:
        from training.rag_system import DocumentStore
        
        persist_dir = Path('training/faiss_index')
        if not persist_dir.exists():
            return jsonify({'documents': 0, 'clients': 0})
        
        store = DocumentStore(persist_dir=persist_dir)
        stats = store.get_stats()
        
        # Compter les clients uniques
        clients = set()
        for meta in store.metadatas:
            if 'client' in meta:
                clients.add(meta['client'])
        
        return jsonify({
            'documents': stats.get('total_documents', 0),
            'clients': len(clients)
        })
    except Exception as e:
        return jsonify({'documents': 0, 'clients': 0, 'error': str(e)})


# ============================================================
# WebSocket Events
# ============================================================

@socketio.on('connect')
def handle_connect():
    """Client connecté"""
    print('✅ Client WebSocket connecté')
    emit('connected', {'message': 'Connecté au serveur'})


@socketio.on('disconnect')
def handle_disconnect():
    """Client déconnecté"""
    print('❌ Client WebSocket déconnecté')


@socketio.on('request_jobs')
def handle_request_jobs(data):
    """Demande la liste des jobs"""
    status_filter = data.get('status') if data else None
    
    status = None
    if status_filter:
        try:
            status = JobStatus(status_filter)
        except ValueError:
            pass
    
    jobs = job_manager.get_all_jobs(status=status, limit=50)
    emit('jobs_list', {'jobs': jobs})


if __name__ == '__main__':
    # Créer les dossiers nécessaires
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    app.config['UPLOAD_FOLDER'].mkdir(parents=True, exist_ok=True)
    
    # Vérifier que les fichiers de référence existent
    if not AGENCES_FILE.exists():
        print(f"⚠️  ATTENTION: {AGENCES_FILE} introuvable")
    if not CLIENTS_FILE.exists():
        print(f"⚠️  ATTENTION: {CLIENTS_FILE} introuvable")
    
    # Démarrer le job processor
    job_processor.start()
    
    print("\n" + "="*60)
    print("🚀 Interface OCR - Version 2.0")
    print("="*60)
    print("📁 Ouvrez votre navigateur à: http://localhost:5001")
    print("📊 Pages disponibles:")
    print("   - http://localhost:5001/         (Extraction)")
    print("   - http://localhost:5001/training (Entraînement)")
    print("   - http://localhost:5001/monitoring (Monitoring temps réel)")
    print("   - http://localhost:5001/failed-jobs (Gestion des échecs)")
    print()
    print("📡 API REST disponible:")
    print("   - POST /api/extract        (Soumettre un BC)")
    print("   - GET  /api/status/<id>    (Statut d'un job)")
    print("   - GET  /api/jobs           (Liste des jobs)")
    print("   - POST /api/retry/<id>     (Relancer un job)")
    print("   - POST /api/rag/reindex    (Réindexer RAG)")
    print("   - POST /api/rag/extract    (Extraction RAG)")
    print("   - POST /api/rag/clear      (Vider index RAG)")
    print("="*60 + "\n")
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5001)