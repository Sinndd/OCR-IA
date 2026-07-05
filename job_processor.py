#!/usr/bin/env python3
"""
JobProcessor - Traitement asynchrone des jobs
Gère la queue et exécute les extractions en background
"""

import threading
import queue
import time
from pathlib import Path
from typing import Callable, Optional, Dict, Any
from job_manager import JobManager, JobStatus, JobStep
from Production.ocr_smart import SmartExtractor


class JobProcessor:
    """Processeur asynchrone de jobs avec queue"""
    
    def __init__(
        self,
        job_manager: JobManager,
        patterns_dir: Path,
        agences_file: Path,
        clients_file: Path,
        out_dir: Path,
        on_job_update: Optional[Callable[[str], None]] = None
    ):
        """
        Args:
            job_manager: Gestionnaire de jobs
            patterns_dir: Dossier des patterns clients
            agences_file: Fichier des agences
            clients_file: Fichier des clients
            out_dir: Dossier de sortie des JSON
            on_job_update: Callback appelé à chaque mise à jour (pour WebSocket)
        """
        self.job_manager = job_manager
        self.patterns_dir = patterns_dir
        self.agences_file = agences_file
        self.clients_file = clients_file
        self.out_dir = out_dir
        self.on_job_update = on_job_update
        
        self.job_queue = queue.Queue()
        self.worker_thread = None
        self.running = False
    
    def start(self):
        """Démarre le worker en arrière-plan"""
        if self.running:
            return
        
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        print("✅ Job processor started")
    
    def stop(self):
        """Arrête le worker"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
    
    def submit_job(self, job_id: str):
        """Ajoute un job à la queue"""
        self.job_queue.put(job_id)
    
    def _worker(self):
        """Thread worker qui traite la queue"""
        while self.running:
            try:
                # Récupérer un job (timeout pour vérifier self.running)
                job_id = self.job_queue.get(timeout=1)
                
                # Traiter le job
                self._process_job(job_id)
                
                self.job_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ Erreur worker: {e}")
    
    def _notify_update(self, job_id: str):
        """Notifie une mise à jour de job (pour WebSocket)"""
        if self.on_job_update:
            try:
                self.on_job_update(job_id)
            except Exception as e:
                print(f"⚠️ Erreur callback: {e}")
    
    def _process_job(self, job_id: str):
        """
        Traite un job complet : extraction texte → détection client → LLM → JSON
        """
        try:
            # Récupérer le job
            job = self.job_manager.get_job(job_id)
            if not job:
                print(f"❌ Job {job_id} introuvable")
                return
            
            print(f"\n🔄 Traitement job {job_id}: {job['filename']}")
            
            # Marquer comme en cours
            self.job_manager.update_job_status(job_id, JobStatus.PROCESSING)
            self._notify_update(job_id)
            
            # Créer l'extracteur
            extractor = SmartExtractor(
                patterns_dir=self.patterns_dir,
                agences_file=self.agences_file,
                clients_file=self.clients_file,
                debug=False
            )
            
            input_path = Path(job['input_path'])
            
            # Étape 1: Extraction texte
            self.job_manager.update_job_step(
                job_id,
                JobStep.TEXT_EXTRACTION,
                "Extraction du texte du BC..."
            )
            self._notify_update(job_id)
            
            bc_text = extractor.extract_text(input_path)
            if not bc_text:
                raise RuntimeError("Impossible d'extraire le texte du BC")
            
            # Étape 2: Détection client
            self.job_manager.update_job_step(
                job_id,
                JobStep.CLIENT_DETECTION,
                "Détection du client..."
            )
            self._notify_update(job_id)
            
            client_id = extractor.detect_client(bc_text)
            
            # Étape 3: Traitement LLM
            self.job_manager.update_job_step(
                job_id,
                JobStep.LLM_PROCESSING,
                f"Extraction avec LLM (client: {client_id or 'auto'})..."
            )
            self._notify_update(job_id)
            
            result, detected_client, filename_convention = extractor.process_bc(
                input_path,
                client_id_hint=client_id
            )
            
            # Étape 4: Génération JSON
            self.job_manager.update_job_step(
                job_id,
                JobStep.JSON_GENERATION,
                "Sauvegarde des résultats JSON..."
            )
            self._notify_update(job_id)
            
            # Sauvegarder les résultats
            from Production.ocr_smart import save_results
            save_results(
                result,
                self.out_dir,
                filename_convention,
                detected_client,
                debug=False
            )
            
            # Trouver les fichiers générés
            output_files = list(self.out_dir.glob(f"*{job['filename'].replace('.pdf', '').replace('.html', '').replace('.txt', '')}*.json"))
            output_path = str(output_files[0]) if output_files else None
            
            # Étape 5: Terminé
            self.job_manager.update_job_step(
                job_id,
                JobStep.COMPLETED,
                f"✅ Extraction terminée ({len(result.get('commandes', []))} commande(s))"
            )
            
            self.job_manager.update_job_status(
                job_id,
                JobStatus.COMPLETED,
                output_path=output_path,
                client_id=detected_client
            )
            
            self._notify_update(job_id)
            
            print(f"✅ Job {job_id} terminé avec succès")
            
        except Exception as e:
            # En cas d'erreur
            error_msg = str(e)
            print(f"❌ Job {job_id} échoué: {error_msg}")
            
            self.job_manager.update_job_status(
                job_id,
                JobStatus.FAILED,
                error_message=error_msg
            )
            
            self._notify_update(job_id)
