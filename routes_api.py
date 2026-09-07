# API REST utilisée par n8n / intégrations externes: soumettre un BC,
# suivre un job, récupérer un résultat.
import glob
import json
import os
import re
import time
from pathlib import Path

from flask import request, jsonify
from werkzeug.utils import secure_filename

from extensions import app, job_manager, job_processor, require_api_key, OUT_DIR
from job_manager import JobStatus


# API d'extraction pour n8n
# Upload un BC et retourne un job_id pour suivi
@app.route('/api/extract', methods=['POST'])
@require_api_key
def api_extract():
    if not request.files:
        return jsonify({'success': False, 'error': 'Aucun fichier reçu'}), 400

    # Prendre le premier fichier trouvé, peu importe la clé (file, attachment_0, etc.)
    file = next(iter(request.files.values()))

    if file.filename == '':
        return jsonify({'success': False, 'error': 'Nom de fichier vide'}), 400

    allowed_extensions = {'.pdf', '.html', '.htm', '.txt'}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        return jsonify({
            'success': False,
            'error': f'Format non supporté: {file_ext}. Formats: PDF, HTML, TXT'
        }), 400

    try:
        api_upload_dir = app.config['UPLOAD_FOLDER'] / 'api_uploads'
        api_upload_dir.mkdir(parents=True, exist_ok=True)

        safe_filename = secure_filename(file.filename)
        file_path = api_upload_dir / safe_filename
        file.save(str(file_path))

        metadata = {}
        if request.form.get('metadata'):
            try:
                metadata = json.loads(request.form.get('metadata'))
            except Exception:
                pass

        job_id = job_manager.create_job(
            filename=file.filename,
            input_path=str(file_path),
            metadata=metadata
        )

        job_processor.submit_job(job_id)

        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'Job créé avec succès'
        }), 201

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# API: Renvoie TOUS les JSONs correspondant au job_id.
# Renvoie une liste : { "success": true, "results": [ {...}, {...} ] }
@app.route('/api/result/<job_id>', methods=['GET'])
@require_api_key
def api_get_result(job_id):
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
        except Exception:
            continue  # Si un fichier est illisible, on l'ignore

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


# Récupère le statut d'un job OU le contenu d'un fichier résultat par son nom
@app.route('/api/status/<job_id>', methods=['GET'])
@app.route('/api/result/<job_id>', methods=['GET'])  # Alias pour n8n
@require_api_key
def api_job_status(job_id):
    print(f"🔍 Recherche du fichier: {job_id}")

    # Essayer d'abord de trouver le fichier directement par son nom
    search_pattern = str(OUT_DIR / f"{job_id}*.json")
    print(f"🔎 Pattern de recherche: {search_pattern}")
    candidates = glob.glob(search_pattern)
    print(f"📂 Fichiers trouvés: {candidates}")

    if candidates:
        target_file = sorted(candidates)[-1]
        print(f"Fichier sélectionné: {target_file}")
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


# Liste tous les jobs (avec filtres optionnels)
@app.route('/api/jobs', methods=['GET'])
def api_list_jobs():
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


# Relance un job échoué
@app.route('/api/retry/<job_id>', methods=['POST'])
def api_retry_job(job_id):
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
        job_processor.submit_job(job_id)

        return jsonify({
            'success': True,
            'message': 'Job relancé avec succès'
        })
    else:
        return jsonify({'success': False, 'error': 'Erreur lors du retry'}), 500
