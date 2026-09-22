"""Local API integration and durability tests (no model downloads or cloud calls)."""
import asyncio
import contextlib
import io
import json
import math
import sqlite3
import struct
import time
import wave
import zipfile

import pytest
from fastapi.testclient import TestClient

from server import app as backend
from server.store import Store


@pytest.fixture
def api(tmp_path, monkeypatch):
    repository = Store(tmp_path / "data")
    monkeypatch.setattr(backend, "store", repository)
    monkeypatch.setattr(backend, "live_sessions", set())
    monkeypatch.setattr(backend, "active_tasks", set())
    monkeypatch.setattr(backend, "task_tokens", {})
    monkeypatch.setattr(backend, "readiness_cache", (0, {}))
    monkeypatch.setattr(backend, "private_settings", lambda: {**repository.settings(), "api_key": ""})

    async def no_model(_settings):
        return {"ok": False, "models": [], "message": "No model configured for test"}

    monkeypatch.setattr(backend.ai, "test_provider", no_model)
    # Requests run without lifespan unless a test explicitly starts the worker.
    with contextlib.closing(TestClient(backend.app, base_url="http://localhost:8765")) as client:
        response = client.get("/api/bootstrap")
        assert response.status_code == 200
        yield client, repository


def job(client, title="Data engineer"):
    response = client.post("/api/jobs", json={"title": title, "company": "Example", "description": "SQL and pipelines"})
    assert response.status_code == 200, response.text
    return response.json()


def session(client, selected_job=None, **fields):
    selected_job = selected_job or job(client)
    response = client.post("/api/sessions", json={"job_id": selected_job["id"], **fields})
    assert response.status_code == 200, response.text
    return response.json()


def wav_bytes(frames=1600, rate=16000, amplitude=500):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"".join(struct.pack("<h", int(amplitude * math.sin(index * .12))) for index in range(frames)))
    return buffer.getvalue()


def candidate(repository, selected_session, speaker="SPEAKER_00"):
    return repository.put("segments", {"session_id": selected_session["id"], "role": "candidate", "speaker": speaker,
                                      "text": "I measured the slow query before optimizing it.", "start": 1.0, "end": 4.0})


def fake_report():
    return {"summary": "A test-only assessment", "overall_score": 3, "dimensions": [], "strengths": [],
            "improvements": [], "drills": [{"title": "Retry", "instruction": "Describe the result", "skill": "Depth"}], "limitations": []}


def wait_task(client, identifier, terminal=("completed", "failed", "cancelled")):
    for _ in range(100):
        record = next(t for t in client.get("/api/bootstrap").json()["tasks"] if t["id"] == identifier)
        if record["status"] in terminal:
            return record
        time.sleep(.03)
    pytest.fail("Worker did not finish task")


def test_job_round_session_crud_and_cascade(api):
    client, repository = api
    selected_job = job(client)
    updated = client.patch(f"/api/jobs/{selected_job['id']}", json={"requirements": ["SQL", "ETL"]})
    assert updated.json()["requirements"] == ["SQL", "ETL"]
    round_record = client.post("/api/rounds", json={"job_id": selected_job["id"], "title": "Technical round"}).json()
    assert client.patch(f"/api/rounds/{round_record['id']}", json={"outcome": "Practice scheduled"}).status_code == 200
    selected_session = session(client, selected_job, round_id=round_record["id"])
    segment = candidate(repository, selected_session)
    assert client.get(f"/api/sessions/{selected_session['id']}").json()["segments"][0]["id"] == segment["id"]
    assert client.delete(f"/api/rounds/{round_record['id']}").status_code == 200
    assert client.get(f"/api/sessions/{selected_session['id']}").json()["session"]["round_id"] is None
    assert client.delete(f"/api/jobs/{selected_job['id']}").status_code == 200
    for collection in ("jobs", "rounds", "sessions", "segments"):
        assert not repository.list(collection)


def test_round_cannot_be_used_for_another_job(api):
    client, _repository = api
    first, second = job(client, "First"), job(client, "Second")
    record = client.post("/api/rounds", json={"job_id": first["id"], "title": "Screening"}).json()
    response = client.post("/api/sessions", json={"job_id": second["id"], "round_id": record["id"]})
    assert response.status_code == 400


def test_local_auth_and_cross_origin_guards(api):
    client, _repository = api
    with TestClient(backend.app, base_url="http://localhost:8765") as unauthenticated:
        assert unauthenticated.get("/api/jobs").status_code == 401
        assert unauthenticated.get("/api/bootstrap", headers={"origin": "https://evil.example"}).status_code == 403
        assert unauthenticated.get("/api/bootstrap", headers={"host": "evil.example"}).status_code == 403
        assert unauthenticated.get("/api/bootstrap", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    cookie = client.get("/api/bootstrap").headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.post("/api/jobs", json={"title": "Forged"}, headers={"origin": "https://evil.example"}).status_code == 403


def test_settings_do_not_persist_nested_credentials(api):
    client, repository = api
    response = client.patch("/api/settings", json={"provider": {"kind": "lmstudio", "api_key": "do-not-store", "model": "local"}})
    assert response.status_code == 200
    assert "do-not-store" not in json.dumps(repository.settings())
    assert "do-not-store" not in client.get("/api/bootstrap").text


def test_chunks_idempotent_durable_and_playable_with_range(api):
    client, repository = api
    selected_session = session(client)
    prefix = f"/api/sessions/{selected_session['id']}"
    first = wav_bytes()
    second = wav_bytes(frames=800, rate=8000)
    assert client.post(prefix + "/chunks?seq=0", content=first, headers={"content-type": "audio/wav"}).status_code == 200
    assert client.post(prefix + "/chunks?seq=0", content=first).status_code == 200
    assert client.post(prefix + "/chunks?seq=0", content=second).status_code == 409
    assert client.post(prefix + "/chunks?seq=1", content=second).status_code == 200
    # SQLite reopen and files preserve chunks independently of final assembly.
    reopened = Store(repository.directory)
    assert reopened.get("sessions", selected_session["id"])["next_seq"] == 2
    response = client.post(prefix + "/finalize", json={"duration_seconds": 999, "mime_type": "audio/wav"})
    assert response.status_code == 200, response.text
    assert response.json()["duration_seconds"] == pytest.approx(.2, abs=.005)
    recording = client.get(prefix + "/recording")
    assert recording.status_code == 200
    with wave.open(io.BytesIO(recording.content), "rb") as audio:
        assert audio.getframerate() == 16000 and audio.getnchannels() == 1
        assert audio.getnframes() == pytest.approx(3200, abs=50)
    assert client.get(prefix + "/recording", headers={"Range": "bytes=0-43"}).status_code == 206


def test_finalize_refuses_missing_chunks_and_invalid_audio(api):
    client, repository = api
    selected_session = session(client)
    prefix = f"/api/sessions/{selected_session['id']}"
    assert client.post(prefix + "/chunks?seq=0", content=b"not audio").status_code == 400
    assert client.post(prefix + "/chunks?seq=1", content=wav_bytes()).status_code == 200
    assert client.post(prefix + "/finalize", json={}).status_code == 409
    assert (repository.directory / "media" / selected_session["id"] / "chunks" / "00000001.wav").exists()


def test_import_requires_speaker_confirmation_before_assessment(api, monkeypatch):
    client, repository = api
    selected_session = session(client)
    repository.update("sessions", selected_session["id"], {"source": "upload", "speakers_confirmed": False})
    segment = candidate(repository, selected_session)
    calls = []
    async def assess(*args):
        calls.append(args)
        return fake_report()
    monkeypatch.setattr(backend.ai, "assess", assess)
    with client:
        identifier = client.post(f"/api/sessions/{selected_session['id']}/assess").json()["id"]
        first = wait_task(client, identifier)
        assert first["status"] == "failed" and "speaker" in first["error"].lower() and not calls
        assert client.post(f"/api/sessions/{selected_session['id']}/speakers", json={"mapping": {segment["speaker"]: "candidate"}}).status_code == 200
        assert client.post(f"/api/tasks/{identifier}/retry").status_code == 200
        assert wait_task(client, identifier)["status"] == "completed"
    assert len(calls) == 1 and len(repository.list("assessments")) == 1 and len(repository.list("drills")) == 1


def test_cancelled_queued_task_keeps_recording_and_can_retry(api, monkeypatch):
    client, repository = api
    selected_session = session(client)
    candidate(repository, selected_session)
    prefix = f"/api/sessions/{selected_session['id']}"
    client.post(prefix + "/chunks?seq=0", content=wav_bytes())
    record = client.post(prefix + "/assess").json()
    duplicate = client.post(prefix + "/assess").json()
    assert duplicate["id"] == record["id"]
    assert client.post(f"/api/tasks/{record['id']}/cancel").json()["status"] == "cancelled"
    assert (repository.directory / "media" / selected_session["id"] / "chunks" / "00000000.wav").exists()
    assert "settings_snapshot" not in json.dumps(client.get("/api/bootstrap").json()["tasks"])
    async def assess(*args):
        return fake_report()
    monkeypatch.setattr(backend.ai, "assess", assess)
    with client:
        assert client.post(f"/api/tasks/{record['id']}/retry").status_code == 200
        assert wait_task(client, record["id"])["status"] == "completed"
    assert client.post(f"/api/tasks/{record['id']}/retry").status_code == 409


def test_bootstrap_keeps_historical_report_but_marks_it_stale_after_edit(api):
    client, repository = api
    selected_session = session(client)
    segment = candidate(repository, selected_session)
    report = repository.put("assessments", {"session_id": selected_session["id"], "report": fake_report(), "stale": False})
    response = client.patch(f"/api/segments/{segment['id']}", json={"text": "The corrected answer."})
    assert response.status_code == 200
    assert repository.get("assessments", report["id"])["stale"]
    assert repository.get("sessions", selected_session["id"])["transcript_revision"] == 1


@pytest.mark.parametrize("timestamp", ["2.5", "Infinity"])
def test_segment_timestamps_are_normalized_or_rejected_without_corrupting_records(api, timestamp):
    client, repository = api
    selected_session = session(client)
    first = candidate(repository, selected_session)
    candidate(repository, selected_session)
    response = client.patch(f"/api/segments/{first['id']}", json={"start": timestamp, "end": timestamp})
    if response.status_code == 200:
        assert isinstance(response.json()["start"], (int, float))
        assert math.isfinite(response.json()["start"])
    else:
        assert response.status_code in (400, 422)
        assert repository.get("segments", first["id"])["start"] == 1.0
    assert client.get(f"/api/sessions/{selected_session['id']}").status_code == 200


def test_speaker_mapping_increments_transcript_revision(api):
    client, repository = api
    selected_session = session(client)
    candidate(repository, selected_session)
    response = client.post(f"/api/sessions/{selected_session['id']}/speakers", json={"mapping": {"SPEAKER_00": "candidate"}})
    assert response.status_code == 200
    assert response.json()["transcript_revision"] == 1


def test_rejected_speaker_mapping_does_not_partially_modify_transcript(api):
    client, repository = api
    selected_session = session(client)
    segment = candidate(repository, selected_session)
    response = client.post(f"/api/sessions/{selected_session['id']}/speakers", json={"mapping": {"SPEAKER_00": "interviewer"}})
    assert response.status_code == 400
    assert repository.get("segments", segment["id"])["role"] == "candidate"


def test_cancelled_inflight_task_cannot_be_retried_or_deleted_until_worker_stops(api):
    client, repository = api
    selected_session = session(client)
    candidate(repository, selected_session)
    record = client.post(f"/api/sessions/{selected_session['id']}/assess").json()
    repository.update("tasks", record["id"], {"status": "running"})
    backend.active_tasks.add(record["id"])
    assert client.post(f"/api/tasks/{record['id']}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/tasks/{record['id']}/retry").status_code == 409
    assert client.delete(f"/api/sessions/{selected_session['id']}").status_code == 409
    backend.active_tasks.discard(record["id"])
    assert client.post(f"/api/tasks/{record['id']}/retry").status_code == 200


def test_assessment_does_not_mark_changed_transcript_as_current(api, monkeypatch):
    client, repository = api
    selected_session = session(client)
    segment = candidate(repository, selected_session)
    async def assess(*args):
        # Reproduce a user correction while model inference is in progress.
        backend.edit_segment(segment["id"], {"text": "A different answer."})
        return fake_report()
    monkeypatch.setattr(backend.ai, "assess", assess)
    with client:
        identifier = client.post(f"/api/sessions/{selected_session['id']}/assess").json()["id"]
        wait_task(client, identifier)
    reports = repository.list("assessments", session_id=selected_session["id"])
    assert not reports or all(r.get("stale") for r in reports)


def test_backup_restore_preserves_audio_and_records(api):
    client, repository = api
    selected_job = job(client)
    selected_session = session(client, selected_job)
    prefix = f"/api/sessions/{selected_session['id']}"
    client.post(prefix + "/chunks?seq=0", content=wav_bytes())
    client.post(prefix + "/finalize", json={})
    original_audio = client.get(prefix + "/recording").content
    backup = client.get("/api/backup")
    assert backup.status_code == 200
    with zipfile.ZipFile(io.BytesIO(backup.content)) as archive:
        assert "helios.sqlite3" in archive.namelist()
        assert all("models/" not in name for name in archive.namelist())
    assert client.delete(f"/api/jobs/{selected_job['id']}").status_code == 200
    response = client.post("/api/restore", files={"file": ("backup.zip", backup.content, "application/zip")})
    assert response.status_code == 200, response.text
    assert repository.get("jobs", selected_job["id"])["title"] == selected_job["title"]
    assert repository.settings()["offline"] is True
    assert client.get(prefix + "/recording").content == original_audio


@pytest.mark.parametrize("path", ["../escape.txt", "media/../../escape.txt", "C:/escape.txt", "media/..\\..\\escape.txt"])
def test_restore_rejects_path_traversal_without_altering_database(api, path):
    client, repository = api
    selected_job = job(client)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("manifest.json", '{"format":"helios-backup","version":1}')
        archive.writestr(path, "escape")
    response = client.post("/api/restore", files={"file": ("backup.zip", stream.getvalue())})
    assert response.status_code == 400
    assert repository.get("jobs", selected_job["id"])["title"] == selected_job["title"]
    assert not (repository.directory.parent / "escape.txt").exists()


def test_restore_rejects_semantically_invalid_database_before_replacing_state(api, tmp_path):
    client, repository = api
    selected_job = job(client)
    database = tmp_path / "invalid.sqlite3"
    repository.snapshot(database)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("UPDATE records SET data='not-json'")
    connection.close()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("manifest.json", '{"format":"helios-backup","version":1}')
        archive.write(database, "helios.sqlite3")
    response = client.post("/api/restore", files={"file": ("backup.zip", stream.getvalue())})
    assert response.status_code == 400
    assert repository.get("jobs", selected_job["id"])["title"] == selected_job["title"]
