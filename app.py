"""Point d'entrée de l'application.

Ce fichier ne fait que rassembler les morceaux définis ailleurs:
- extensions.py    -> app Flask, socketio, config, jobs
- routes_pages.py  -> pages web (accueil, entraînement, résultats...)
- routes_api.py    -> API REST pour n8n
- routes_rag.py    -> API du système RAG
- sockets.py       -> événements WebSocket

Chacun de ces fichiers enregistre ses routes/handlers sur `app`/`socketio` dès
qu'on l'importe (via les décorateurs @app.route et @socketio.on) — c'est
pourquoi les imports ci-dessous semblent "inutilisés": ils ne le sont pas,
ils déclenchent l'enregistrement des routes.
"""
from extensions import app, socketio, job_processor, AGENCES_FILE, CLIENTS_FILE, OUT_DIR

import routes_pages   # noqa: F401
import routes_api     # noqa: F401
import routes_rag     # noqa: F401
import sockets        # noqa: F401


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

    socketio.run(app, debug=True, host='0.0.0.0', port=5001, allow_unsafe_werkzeug=True)
