# API du système RAG (recherche de documents similaires): réindexation,
# vidage de l'index, extraction assistée par RAG, statistiques.
import tempfile
import time as time_module
from pathlib import Path

from flask import request, jsonify

from extensions import app, PATTERNS_DIR


# Réindexer tous les patterns dans le système RAG
@app.route('/api/rag/reindex', methods=['POST'])
def api_rag_reindex():
    try:
        from training.rag_system import DocumentStore, RAGIndexer

        persist_dir = Path('training/faiss_index')
        store = DocumentStore(persist_dir=persist_dir)
        indexer = RAGIndexer(patterns_dir=PATTERNS_DIR, document_store=store)
        indexer.index_all()

        stats = store.get_stats()
        return jsonify({
            'success': True,
            'message': f"Indexation terminée: {stats.get('total_documents', 0)} documents",
            'documents': stats.get('total_documents', 0)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# Vider l'index RAG
@app.route('/api/rag/clear', methods=['POST'])
def api_rag_clear():
    try:
        import shutil
        persist_dir = Path('training/faiss_index')
        if persist_dir.exists():
            shutil.rmtree(persist_dir)
        return jsonify({
            'success': True,
            'message': 'Index RAG supprimé'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# Extraire un BC avec le système RAG
@app.route('/api/rag/extract', methods=['POST'])
def api_rag_extract():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Fichier requis'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Fichier vide'}), 400

        # Sauvegarder temporairement
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


# Statistiques du système RAG
@app.route('/api/rag/stats', methods=['GET'])
def api_rag_stats():
    try:
        from training.rag_system import DocumentStore

        persist_dir = Path('training/faiss_index')
        if not persist_dir.exists():
            return jsonify({'documents': 0, 'clients': 0})

        store = DocumentStore(persist_dir=persist_dir)
        stats = store.get_stats()

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
