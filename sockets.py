# Événements WebSocket (mises à jour temps réel de la page /monitoring).
from flask_socketio import emit

from extensions import socketio, job_manager
from job_manager import JobStatus


# Client connecté
@socketio.on('connect')
def handle_connect():
    print('Client WebSocket connecté')
    emit('connected', {'message': 'Connecté au serveur'})


# Client déconnecté
@socketio.on('disconnect')
def handle_disconnect():
    print('Client WebSocket déconnecté')


# Demande la liste des jobs
@socketio.on('request_jobs')
def handle_request_jobs(data):
    status_filter = data.get('status') if data else None

    status = None
    if status_filter:
        try:
            status = JobStatus(status_filter)
        except ValueError:
            pass

    jobs = job_manager.get_all_jobs(status=status, limit=50)
    emit('jobs_list', {'jobs': jobs})
