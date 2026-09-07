# Pages web principales: accueil, entraînement, résultats, statistiques,
# upload et validation des extractions.
#
# Chaque fonction est enregistrée directement sur `app` (importé depuis
# extensions.py) via @app.route, exactement comme avant — seul l'emplacement
# du code a changé, pas le comportement.
import json
import glob
import os
import re
import time
import traceback
import tempfile
from datetime import datetime
from pathlib import Path

from flask import render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.utils import secure_filename

from extensions import (
    app, job_manager, job_processor, notify_job_update,
    AGENCES_FILE, CLIENTS_FILE, OUT_DIR, PATTERNS_DIR,
)
from job_manager import JobStatus
from helpers import (
    load_metrics, save_metrics, is_allowed_file, run_script,
    iter_trained_clients, find_client_id_by_origine, save_training_example,
    invalidate_patterns_cache,
)


@app.route('/')
def index():
    clients = [client_dir.name for client_dir, _ in iter_trained_clients()]
    return render_template('index.html', clients=sorted(clients))


# Page d'entraînement
@app.route('/training')
def training():
    clients = []
    for client_dir, metadata in iter_trained_clients():
        try:
            patterns = metadata.get('patterns_detectes', {})
            examples_count = patterns.get('nb_exemples', 0) or 0
            patterns_count = len(list(client_dir.glob("training_*.txt")))

            training_date = "Récemment"
            metadata_file = client_dir / "metadata.json"
            if metadata_file.stat().st_mtime:
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
            clients_set = set()
            for meta in store.metadatas:
                if 'client' in meta:
                    clients_set.add(meta['client'])
            rag_stats['clients'] = len(clients_set)
    except Exception as e:
        print(f"⚠️  Erreur chargement stats RAG: {e}")

    return render_template('training.html', clients=sorted(clients, key=lambda x: x['name']), rag_stats=rag_stats)


# Endpoint pour entraîner un nouveau client
@app.route('/train', methods=['POST'])
def train():
    client_id = request.form.get('client_id', '').strip()

    if 'bc_file' not in request.files or 'json_file' not in request.files:
        flash('Fichiers BC et JSON requis', 'error')
        return redirect(url_for('training'))

    bc_file = request.files['bc_file']
    json_file = request.files['json_file']
    prompt_file = request.files.get('prompt_file')

    if not client_id:
        flash('ID client requis', 'error')
        return redirect(url_for('training'))

    if bc_file.filename == '' or json_file.filename == '':
        flash('Fichiers BC et JSON requis', 'error')
        return redirect(url_for('training'))

    if not is_allowed_file(bc_file.filename, {'.pdf', '.html', '.htm', '.txt'}):
        bc_ext = Path(bc_file.filename).suffix.lower()
        flash(f'Format BC non supporté: {bc_ext}. Formats acceptés: PDF, HTML, TXT', 'error')
        return redirect(url_for('training'))

    if not is_allowed_file(json_file.filename, {'.json'}):
        flash('Le fichier attendu doit être au format JSON', 'error')
        return redirect(url_for('training'))

    if prompt_file and prompt_file.filename and not is_allowed_file(prompt_file.filename, {'.md', '.txt'}):
        prompt_ext = Path(prompt_file.filename).suffix.lower()
        flash(f'Format prompt non supporté: {prompt_ext}. Formats acceptés: MD, TXT', 'error')
        return redirect(url_for('training'))

    try:
        temp_dir = Path(tempfile.mkdtemp())
        bc_path = temp_dir / secure_filename(bc_file.filename)
        json_path = temp_dir / secure_filename(json_file.filename)

        bc_file.save(str(bc_path))
        json_file.save(str(json_path))

        prompt_path = None
        if prompt_file and prompt_file.filename:
            prompt_path = temp_dir / secure_filename(prompt_file.filename)
            prompt_file.save(str(prompt_path))

        args = ['--client-id', client_id, '--bc-samples', str(bc_path), '--expected-json', str(json_path)]
        if prompt_path:
            args += ['--prompt', str(prompt_path)]

        result = run_script('Administration/ocr_train.py', *args)

        try:
            bc_path.unlink()
            json_path.unlink()
            if prompt_path:
                prompt_path.unlink()
            temp_dir.rmdir()
        except Exception:
            pass

        if result.returncode == 0:
            flash(f'Client {client_id} entraîné avec succès !', 'success')
            return redirect(url_for('training'))
        else:
            error_msg = result.stderr if result.stderr else "Erreur inconnue"
            flash(f'Erreur lors de l\'entraînement: {error_msg[:200]}', 'error')
            return redirect(url_for('training'))

    except Exception as e:
        flash(f'Erreur: {str(e)}', 'error')
        return redirect(url_for('training'))


# Évaluer la précision d'un client
@app.route('/evaluate/<client_id>')
def evaluate(client_id):
    try:
        result = run_script('Administration/ocr_evaluate.py', '--client-id', client_id)

        if result.returncode == 0:
            output = result.stdout
            precision = 0.0

            for line in output.split('\n'):
                if 'Précision globale' in line or 'précision' in line.lower():
                    try:
                        match = re.search(r'(\d+\.?\d*)%', line)
                        if match:
                            precision = float(match.group(1))
                    except Exception:
                        pass

            return jsonify({'success': True, 'precision': precision, 'output': output})
        else:
            return jsonify({'success': False, 'error': result.stderr}), 500

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# Affiche les résultats stockés en session
@app.route('/results')
def results():
    results_data = session.get('results', [])
    total_products = session.get('total_products', 0)
    client_id = session.get('client_id', None)
    file_formats = session.get('file_formats', 'PDF')
    detected_clients = session.get('detected_clients', 'Auto-détecté')

    if not results_data:
        flash('Aucun résultat disponible. Veuillez d\'abord traiter des fichiers.', 'warning')
        return redirect(url_for('index'))

    metrics = load_metrics()

    for result in results_data:
        result['status'] = 'pending'
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


# Page de statistiques en temps réel
@app.route('/stats')
def stats():
    metrics = load_metrics()

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

    allowed_extensions = {'.pdf', '.html', '.htm', '.txt'}
    for file in files:
        if not is_allowed_file(file.filename, allowed_extensions):
            flash(f'Fichier {file.filename}: formats acceptés: PDF, HTML, TXT', 'error')
            return redirect(url_for('index'))

    try:
        all_commandes = []
        processed_files = []
        file_formats = []
        detected_clients = []

        for file in files:
            file_ext = Path(file.filename).suffix.lower().replace('.', '').upper()
            if file_ext == 'HTM':
                file_ext = 'HTML'

            temp_path = app.config['UPLOAD_FOLDER'] / secure_filename(file.filename)
            file.save(str(temp_path))

            job_id = job_manager.create_job(
                filename=file.filename,
                input_path=str(temp_path),
                metadata={'source': 'upload_web'}
            )
            job_manager.update_job_status(job_id, JobStatus.PROCESSING)
            notify_job_update(job_id)

            timestamp_avant = time.time()
            result = run_script(
                'Production/ocr_smart.py',
                '--input', str(temp_path),
                '--out-dir', str(OUT_DIR),
                '--agences-file', str(AGENCES_FILE),
                '--clients-file', str(CLIENTS_FILE)
            )

            if result.returncode == 0:
                time.sleep(0.5)

                json_files = [
                    f for f in OUT_DIR.glob('*.json')
                    if f.stat().st_mtime > timestamp_avant
                ]
                json_files = sorted(json_files, key=lambda p: p.name)

                print(f"DEBUG: {len(json_files)} fichiers JSON créés pour {file.filename}")

                nb_files_loaded = 0
                file_client_id = None
                for json_file in json_files:
                    try:
                        print(f"DEBUG: Chargement de {json_file.name}")
                        with open(json_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            commandes = data.get('commandes', [])
                            for cmd_data in commandes:
                                if 'entete' not in cmd_data:
                                    cmd_data['entete'] = {}
                                cmd_data['entete']['_source_file'] = file.filename
                                cmd_data['entete']['_file_format'] = file_ext
                                all_commandes.append(cmd_data)
                                nb_files_loaded += 1

                                origine = cmd_data.get('entete', {}).get('origine', 'Inconnu')
                                file_client_id = origine
                                if origine not in detected_clients:
                                    detected_clients.append(origine)
                    except Exception as e:
                        print(f"⚠️  Erreur lecture JSON {json_file}: {e}")
                        pass

                if nb_files_loaded > 0:
                    processed_files.append(file.filename)
                    if file_ext not in file_formats:
                        file_formats.append(file_ext)

                    job_manager.update_job_status(
                        job_id,
                        JobStatus.COMPLETED,
                        output_path=str(json_files[0]) if json_files else None,
                        client_id=file_client_id
                    )
                    notify_job_update(job_id)
                else:
                    print(f"WARNING: Aucun fichier JSON créé pour {file.filename}")
                    flash(f'Aucun JSON généré pour {file.filename}', 'warning')

                    error_msg = "Aucun JSON généré"
                    job_manager.update_job_status(job_id, JobStatus.FAILED, error_message=error_msg)
                    notify_job_update(job_id)
                    job_processor.send_alert(job_id, file.filename, error_msg)
            else:
                error_msg = result.stderr if result.stderr else "Erreur inconnue"
                flash(f'Erreur lors du traitement de {file.filename}: {error_msg[:100]}', 'warning')

                job_manager.update_job_status(job_id, JobStatus.FAILED, error_message=error_msg[:500])
                notify_job_update(job_id)
                job_processor.send_alert(job_id, file.filename, error_msg[:500])

            try:
                temp_path.unlink()
            except Exception:
                pass

        if not all_commandes:
            flash('Aucune commande valide extraite des fichiers', 'warning')
            return redirect(url_for('index'))

        print(f"DEBUG: {len(all_commandes)} commandes chargées")
        print(f"DEBUG: {len(processed_files)} fichiers traités")

        flash(f'{len(processed_files)} fichier(s) traité(s) avec succès', 'success')

        results = []
        total_products = 0

        for i, cmd_data in enumerate(all_commandes):
            entete = cmd_data.get('entete', {})
            detail = cmd_data.get('detailCommande', {})
            products = detail.get('produits', [])
            total_products += len(products)

            num_commande = entete.get('numCommande', entete.get('idCommande', f'commande_{i+1}'))
            filename = f"{num_commande}.json"

            ordered_data = {
                'entete': cmd_data.get('entete', {}),
                'detailCommande': cmd_data.get('detailCommande', {})
            }

            results.append({
                'filename': filename,
                'data': ordered_data
            })

        session['results'] = results
        session['total_products'] = total_products
        session['client_id'] = client_id
        session['file_formats'] = ', '.join(file_formats) if file_formats else 'PDF'
        session['detected_clients'] = ', '.join(detected_clients) if detected_clients else 'Auto-détecté'

        metrics = load_metrics()

        metrics['global_stats']['total_extractions'] += len(results)
        metrics['global_stats']['total_products'] += total_products

        for result in results:
            json_filename = result['filename']
            client_name = detected_clients[0] if detected_clients else 'Inconnu'
            products_count = len(result['data'].get('detailCommande', {}).get('produits', []))

            metrics['extractions'].append({
                'filename': json_filename,
                'client': client_name,
                'products': products_count,
                'timestamp': time.time(),
                'status': 'pending'
            })

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

        return jsonify({'success': True, 'message': 'Extraction terminée'}), 200

    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()
        flash(f'Erreur: {str(e)}', 'error')
        return jsonify({'success': False, 'error': str(e)}), 500


# Valide, annule la validation ou corrige une extraction
@app.route('/validate', methods=['POST'])
def validate_extraction():
    try:
        data = request.json
        action = data.get('action')
        filename = data.get('filename')

        metrics = load_metrics()

        if action == 'validate':
            for extraction in metrics['extractions']:
                if extraction['filename'] == filename and extraction['status'] == 'pending':
                    extraction['status'] = 'validated'

                    client = extraction['client']
                    if client in metrics['clients']:
                        metrics['clients'][client]['validated'] += 1

                    metrics['global_stats']['total_validated'] += 1
                    break

            save_metrics(metrics)

            # Apprentissage: Sauvegarder aussi comme exemple si validé
            try:
                base_name = os.path.splitext(filename)[0]
                search_pattern = OUT_DIR / f"{base_name}*.json"
                candidates = glob.glob(str(search_pattern))

                if candidates:
                    target_file = sorted(candidates)[-1]
                    with open(target_file, 'r', encoding='utf-8') as f:
                        validated_data = json.load(f)

                    client_origin = validated_data.get('entete', {}).get('origine', '')
                    client_id = find_client_id_by_origine(client_origin)
                    save_training_example(client_id, validated_data)
                    invalidate_patterns_cache()
            except Exception as e:
                print(f"Warning: Could not save validated example: {e}")

            return jsonify({'success': True, 'message': 'Extraction validée et apprise'})

        elif action == 'unvalidate':
            for extraction in metrics['extractions']:
                if extraction['filename'] == filename and extraction['status'] == 'validated':
                    extraction['status'] = 'pending'

                    client = extraction['client']
                    if client in metrics['clients']:
                        metrics['clients'][client]['validated'] = max(0, metrics['clients'][client]['validated'] - 1)

                    metrics['global_stats']['total_validated'] = max(0, metrics['global_stats']['total_validated'] - 1)
                    break

            save_metrics(metrics)
            return jsonify({'success': True, 'message': 'Validation annulée'})

        elif action == 'correct':
            corrected_data = data.get('corrected_data')
            multi_commandes = data.get('multi_commandes', False)

            if not corrected_data:
                return jsonify({'success': False, 'error': 'Données corrigées manquantes'}), 400

            if multi_commandes and 'commandes' in corrected_data:
                commandes = corrected_data['commandes']
            elif 'commandes' in corrected_data:
                commandes = corrected_data['commandes']
            else:
                commandes = [corrected_data]

            first_cmd = commandes[0] if commandes else {}
            client_origin = first_cmd.get('entete', {}).get('origine', '')
            client_id = find_client_id_by_origine(client_origin)

            for idx, cmd in enumerate(commandes):
                saved_path = save_training_example(client_id, cmd)
                print(f"Commande {idx + 1}/{len(commandes)} sauvegardée: {saved_path}")

            base_name = os.path.splitext(filename)[0]

            if len(commandes) > 1:
                for idx, cmd in enumerate(commandes):
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
                search_pattern = str(OUT_DIR / f"{base_name}*.json")
                print(f"🔍 Recherche du fichier à mettre à jour: {search_pattern}")
                candidates = glob.glob(search_pattern)
                print(f"📂 Fichiers trouvés: {candidates}")
                if candidates:
                    target_file = sorted(candidates)[-1]
                    print(f"✏️ Mise à jour du fichier: {target_file}")
                    with open(target_file, 'w', encoding='utf-8') as f:
                        json.dump(commandes[0], f, indent=2, ensure_ascii=False)
                    print(f"Fichier sauvegardé avec succès")
                else:
                    out_file = OUT_DIR / f"{base_name}.json"
                    print(f"📝 Création d'un nouveau fichier: {out_file}")
                    with open(out_file, 'w', encoding='utf-8') as f:
                        json.dump(commandes[0], f, indent=2, ensure_ascii=False)

            for extraction in metrics['extractions']:
                if extraction['filename'] == filename:
                    if extraction['status'] == 'pending':
                        extraction['status'] = 'corrected'

                        client = extraction['client']
                        if client in metrics['clients']:
                            metrics['clients'][client]['corrected'] += 1

                        metrics['global_stats']['total_corrected'] += 1
                        print(f"📊 Métriques mises à jour: {filename} -> corrected")
                    break

            save_metrics(metrics)
            invalidate_patterns_cache()

            return jsonify({
                'success': True,
                'message': f'{len(commandes)} commande(s) corrigée(s) et sauvegardée(s) pour {client_id}'
            })

        else:
            return jsonify({'success': False, 'error': 'Action inconnue'}), 400

    except Exception as e:
        print(f"ERROR validation: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# Page de monitoring temps réel
@app.route('/monitoring')
def monitoring():
    return render_template('monitoring.html')


# Page de gestion des jobs échoués
@app.route('/failed-jobs')
def failed_jobs():
    return render_template('failed_jobs.html')
