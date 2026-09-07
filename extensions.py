# Objets partagés par toute l'application: app Flask, socketio, config, jobs.
#
# Tous les autres fichiers (routes_pages, routes_api, routes_rag, sockets, helpers)
# importent depuis ce module plutôt que depuis app.py, pour éviter les imports
# circulaires.
from flask import Flask, request, jsonify
from flask_socketio import SocketIO
import os
import hmac
import secrets
import tempfile
from pathlib import Path
from functools import wraps

from job_manager import JobManager
from job_processor import JobProcessor

app = Flask(__name__)
app.secret_key = os.environ.get("OCR_SECRET_KEY") or secrets.token_hex(32)
app.config['UPLOAD_FOLDER'] = Path(tempfile.gettempdir()) / 'ocr_uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max
app.config['UPLOAD_FOLDER'].mkdir(exist_ok=True)

socketio = SocketIO(app, cors_allowed_origins="*")

# Configurations par défaut
AGENCES_FILE = Path("Données/refs/agencesPAP.txt")
CLIENTS_FILE = Path("Données/refs/clients.txt")
OUT_DIR = Path("Données/resultats")
PATTERNS_DIR = Path("patterns")
METRICS_FILE = Path("Données/metrics.json")

job_manager = JobManager(db_path="jobs.db")

# Clé API pour sécuriser les routes REST (n8n / intégrations externes)
API_KEY = os.environ.get("OCR_API_KEY")
if not API_KEY:
    API_KEY = "dev-only-insecure-key"
    print("OCR_API_KEY non défini : utilisation d'une clé de développement. "
          "Définissez la variable d'environnement OCR_API_KEY en production.")


# Exige un header X-API-KEY valide (401 sinon) sur les routes de l'API REST.
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        provided_key = request.headers.get("X-API-KEY", "")
        if not provided_key or not hmac.compare_digest(provided_key, API_KEY):
            return jsonify({"success": False, "error": "Unauthorized: clé API manquante ou invalide"}), 401
        return f(*args, **kwargs)
    return decorated


# En-têtes de sécurité de base (recommandations OWASP).
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    return response


@app.context_processor
def inject_api_key():
    """Expose la clé API aux templates, pour les appels fetch() internes vers /api/*."""
    return {'api_key': API_KEY}


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
