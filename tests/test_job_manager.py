"""
Tests unitaires pour JobManager (job_manager.py).

Ces tests valident la persistance SQLite des jobs d'extraction (creation,
changement de statut/etape, recuperation, retry) sur une base de donnees
temporaire dediee a chaque test.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from job_manager import JobManager, JobStatus, JobStep


@pytest.fixture
def manager(tmp_path):
    db_path = tmp_path / "jobs_test.db"
    return JobManager(db_path=str(db_path))


def test_create_job_returns_id_and_pending_status(manager):
    job_id = manager.create_job(filename="bon_de_commande.pdf", input_path="/tmp/bon_de_commande.pdf")

    job = manager.get_job(job_id)

    assert job is not None
    assert job["filename"] == "bon_de_commande.pdf"
    assert job["status"] == JobStatus.PENDING.value
    assert job["current_step"] == JobStep.FILE_RECEIVED.value
    assert len(job["logs"]) == 1


def test_update_job_step_changes_current_step_and_logs(manager):
    job_id = manager.create_job(filename="bc.pdf", input_path="/tmp/bc.pdf")

    manager.update_job_step(job_id, JobStep.LLM_PROCESSING, message="Appel LLaVA en cours")
    job = manager.get_job(job_id)

    assert job["current_step"] == JobStep.LLM_PROCESSING.value
    assert any(log["message"] == "Appel LLaVA en cours" for log in job["logs"])


def test_update_job_status_to_completed_sets_completed_at(manager):
    job_id = manager.create_job(filename="bc.pdf", input_path="/tmp/bc.pdf")

    manager.update_job_status(job_id, JobStatus.COMPLETED, output_path="/tmp/out.json", client_id="NEWREST")
    job = manager.get_job(job_id)

    assert job["status"] == JobStatus.COMPLETED.value
    assert job["output_path"] == "/tmp/out.json"
    assert job["client_id"] == "NEWREST"
    assert job["completed_at"] is not None


def test_update_job_status_to_failed_records_error_message(manager):
    job_id = manager.create_job(filename="bc.pdf", input_path="/tmp/bc.pdf")

    manager.update_job_status(job_id, JobStatus.FAILED, error_message="Extraction incomplete: 2eme commande manquante")
    job = manager.get_job(job_id)

    assert job["status"] == JobStatus.FAILED.value
    assert job["error_message"] == "Extraction incomplete: 2eme commande manquante"
    # Note : get_job() ne restitue que timestamp/step/message pour les logs
    # (le niveau ERROR est bien stocke en base mais pas expose par cette methode).
    assert any(log["message"] == "Extraction incomplete: 2eme commande manquante" for log in job["logs"])


def test_get_all_jobs_filters_by_status(manager):
    ok_id = manager.create_job(filename="ok.pdf", input_path="/tmp/ok.pdf")
    failed_id = manager.create_job(filename="ko.pdf", input_path="/tmp/ko.pdf")
    manager.update_job_status(ok_id, JobStatus.COMPLETED)
    manager.update_job_status(failed_id, JobStatus.FAILED, error_message="erreur")

    failed_jobs = manager.get_failed_jobs()

    assert len(failed_jobs) == 1
    assert failed_jobs[0]["id"] == failed_id


def test_retry_job_resets_status_and_clears_error(manager):
    job_id = manager.create_job(filename="bc.pdf", input_path="/tmp/bc.pdf")
    manager.update_job_status(job_id, JobStatus.FAILED, error_message="timeout LLaVA")

    success = manager.retry_job(job_id)
    job = manager.get_job(job_id)

    assert success is True
    assert job["status"] == JobStatus.PENDING.value
    assert job["error_message"] is None
    assert job["completed_at"] is None


def test_get_job_returns_none_for_unknown_id(manager):
    assert manager.get_job("id-inexistant") is None
