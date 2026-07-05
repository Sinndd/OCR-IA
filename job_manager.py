#!/usr/bin/env python3
"""
JobManager - Gestion persistante des jobs d'extraction
Suivi des statuts, étapes et historique des traitements
"""

import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from enum import Enum


class JobStatus(Enum):
    """Statuts possibles d'un job"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStep(Enum):
    """Étapes de traitement d'un job"""
    FILE_RECEIVED = "file_received"
    TEXT_EXTRACTION = "text_extraction"
    CLIENT_DETECTION = "client_detection"
    LLM_PROCESSING = "llm_processing"
    JSON_GENERATION = "json_generation"
    COMPLETED = "completed"


class JobManager:
    """Gestionnaire de jobs avec persistence SQLite"""
    
    def __init__(self, db_path: str = "jobs.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialise la base de données"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Table des jobs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                status TEXT NOT NULL,
                current_step TEXT,
                client_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL,
                error_message TEXT,
                input_path TEXT,
                output_path TEXT,
                metadata TEXT
            )
        """)
        
        # Table des logs de jobs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                step TEXT NOT NULL,
                message TEXT,
                level TEXT DEFAULT 'INFO',
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            )
        """)
        
        conn.commit()
        conn.close()
    
    def create_job(
        self,
        filename: str,
        input_path: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Crée un nouveau job
        
        Args:
            filename: Nom du fichier BC
            input_path: Chemin du fichier uploadé
            metadata: Métadonnées additionnelles (email source, etc.)
        
        Returns:
            ID du job créé
        """
        job_id = str(uuid.uuid4())
        now = datetime.now().timestamp()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO jobs (
                id, filename, status, current_step,
                created_at, updated_at, input_path, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_id,
            filename,
            JobStatus.PENDING.value,
            JobStep.FILE_RECEIVED.value,
            now,
            now,
            input_path,
            json.dumps(metadata or {})
        ))
        
        # Log initial
        cursor.execute("""
            INSERT INTO job_logs (job_id, timestamp, step, message, level)
            VALUES (?, ?, ?, ?, ?)
        """, (job_id, now, JobStep.FILE_RECEIVED.value, f"Fichier reçu: {filename}", "INFO"))
        
        conn.commit()
        conn.close()
        
        return job_id
    
    def update_job_step(
        self,
        job_id: str,
        step: JobStep,
        message: Optional[str] = None
    ):
        """Met à jour l'étape courante d'un job"""
        now = datetime.now().timestamp()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE jobs
            SET current_step = ?, updated_at = ?
            WHERE id = ?
        """, (step.value, now, job_id))
        
        # Log
        cursor.execute("""
            INSERT INTO job_logs (job_id, timestamp, step, message, level)
            VALUES (?, ?, ?, ?, ?)
        """, (job_id, now, step.value, message or f"Étape: {step.value}", "INFO"))
        
        conn.commit()
        conn.close()
    
    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: Optional[str] = None,
        output_path: Optional[str] = None,
        client_id: Optional[str] = None
    ):
        """Met à jour le statut d'un job"""
        now = datetime.now().timestamp()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        completed_at = now if status == JobStatus.COMPLETED else None
        
        cursor.execute("""
            UPDATE jobs
            SET status = ?, updated_at = ?, completed_at = ?,
                error_message = ?, output_path = ?, client_id = ?
            WHERE id = ?
        """, (
            status.value,
            now,
            completed_at,
            error_message,
            output_path,
            client_id,
            job_id
        ))
        
        # Log
        log_message = error_message if status == JobStatus.FAILED else f"Statut: {status.value}"
        log_level = "ERROR" if status == JobStatus.FAILED else "INFO"
        cursor.execute("""
            INSERT INTO job_logs (job_id, timestamp, step, message, level)
            VALUES (?, ?, ?, ?, ?)
        """, (job_id, now, "status_change", log_message, log_level))
        
        conn.commit()
        conn.close()
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Récupère un job par son ID"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return None
        
        job = dict(row)
        
        # Charger les logs
        cursor.execute("""
            SELECT timestamp, step, message
            FROM job_logs
            WHERE job_id = ?
            ORDER BY timestamp ASC
        """, (job_id,))
        
        job['logs'] = [
            {
                'timestamp': log[0],
                'step': log[1],
                'message': log[2]
            }
            for log in cursor.fetchall()
        ]
        
        # Parser metadata
        if job['metadata']:
            job['metadata'] = json.loads(job['metadata'])
        
        conn.close()
        return job
    
    def get_all_jobs(
        self,
        status: Optional[JobStatus] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Récupère tous les jobs (avec filtre optionnel)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM jobs"
        params = []
        
        if status:
            query += " WHERE status = ?"
            params.append(status.value)
        
        query += " ORDER BY created_at DESC"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        jobs = []
        for row in rows:
            job = dict(row)
            
            # Parser metadata
            if job['metadata']:
                job['metadata'] = json.loads(job['metadata'])
            
            jobs.append(job)
        
        conn.close()
        return jobs
    
    def get_failed_jobs(self) -> List[Dict[str, Any]]:
        """Récupère tous les jobs en échec"""
        return self.get_all_jobs(status=JobStatus.FAILED)
    
    def retry_job(self, job_id: str) -> bool:
        """Réinitialise un job pour retry"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        now = datetime.now().timestamp()
        
        cursor.execute("""
            UPDATE jobs
            SET status = ?, current_step = ?, updated_at = ?,
                error_message = NULL, completed_at = NULL
            WHERE id = ?
        """, (
            JobStatus.PENDING.value,
            JobStep.FILE_RECEIVED.value,
            now,
            job_id
        ))
        
        # Log
        cursor.execute("""
            INSERT INTO job_logs (job_id, timestamp, step, message, level)
            VALUES (?, ?, ?, ?, ?)
        """, (job_id, now, "retry", "Job réinitialisé pour retry", "INFO"))
        
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        
        return success
