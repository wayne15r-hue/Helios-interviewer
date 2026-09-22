"""Exercise the real session protocol with deterministic provider doubles."""
import asyncio
import io
import wave

import pytest
from fastapi.testclient import TestClient

from server import app as backend
from server.store import Store


def wav():
    out = io.BytesIO()
    with wave.open(out, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 1600)
    return out.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "store", Store(tmp_path))
    monkeypatch.setattr(backend, "readiness_cache", (0, {}))
    monkeypatch.setattr(backend, "private_settings", lambda: backend.store.settings())
    async def ready():
        return {name: {"ready": False, "message": "Test environment"} for name in ("llm", "stt", "tts", "diarization", "vad")}
    monkeypatch.setattr(backend, "get_readiness", ready)
    monkeypatch.setattr(backend.speech, "synthesize", lambda text, settings: wav())
    with TestClient(backend.app, base_url="http://localhost:8765") as value:
        assert value.get("/api/bootstrap").status_code == 200
        yield value


def new_session(client):
    job = client.post("/api/jobs", json={"title": "Analyst", "description": "Explain analytical decisions"}).json()
    return client.post("/api/sessions", json={"job_id": job["id"]}).json()


def receive_until(socket, event):
    for _ in range(12):
        message = socket.receive_json()
        if message["type"] == event:
            return message
    raise AssertionError(f"Did not receive {event}")


def test_live_turn_audio_timestamps_and_resume(client, monkeypatch):
    async def question(job, session, segments, settings):
        return {"question": "How did you measure the outcome?", "topic": "impact", "difficulty": "basics"}
    monkeypatch.setattr(backend.ai, "next_turn", question)
    session = new_session(client)
    sid = session["id"]
    with client.websocket_connect(f"ws://localhost:8765/api/sessions/{sid}/live", headers={"origin": "http://localhost:8765"}) as ws:
        ws.send_json({"type": "start", "request_id": "first"})
        first = receive_until(ws, "question")
        assert first["audio"] and first["segment"]["role"] == "interviewer"
        ws.send_json({"type": "playback", "segment_id": first["segment"]["id"], "start": 2, "end": 3})
        ws.send_json({"type": "answer", "request_id": "answer-one", "text": "I compared a control group.", "start": 4, "end": 8})
        next_question = receive_until(ws, "question")
        assert next_question["request_id"] == "answer-one"
    detail = client.get(f"/api/sessions/{sid}").json()
    assert detail["segments"][0]["start"] == 2
    assert len([s for s in detail["segments"] if s["role"] == "candidate"]) == 1
    assert detail["session"]["status"] == "paused"
    with client.websocket_connect(f"ws://localhost:8765/api/sessions/{sid}/live", headers={"origin": "http://localhost:8765"}) as ws:
        ws.send_json({"type": "start", "request_id": "resume"})
        question = receive_until(ws, "question")
        assert question["segment"]["id"] == next_question["segment"]["id"]
    assert len(client.get(f"/api/sessions/{sid}").json()["segments"]) == 3


def test_provider_failure_preserves_candidate_answer(client, monkeypatch):
    async def failure(*args):
        raise RuntimeError("Local model is unavailable")
    monkeypatch.setattr(backend.ai, "next_turn", failure)
    sid = new_session(client)["id"]
    with client.websocket_connect(f"ws://localhost:8765/api/sessions/{sid}/live", headers={"origin": "http://localhost:8765"}) as ws:
        ws.send_json({"type": "answer", "request_id": "answer", "text": "My saved answer", "start": 0, "end": 4})
        error = receive_until(ws, "error")
        assert "unavailable" in error["message"]
    assert client.get(f"/api/sessions/{sid}").json()["segments"][0]["text"] == "My saved answer"


def test_interrupt_cancels_pending_generation(client, monkeypatch):
    async def slow(*args):
        await asyncio.sleep(60)
        return {"question": "Should never arrive"}
    monkeypatch.setattr(backend.ai, "next_turn", slow)
    sid = new_session(client)["id"]
    with client.websocket_connect(f"ws://localhost:8765/api/sessions/{sid}/live", headers={"origin": "http://localhost:8765"}) as ws:
        ws.send_json({"type": "start", "request_id": "slow"})
        assert receive_until(ws, "state")["value"] == "thinking"
        ws.send_json({"type": "interrupt", "request_id": "slow"})
        assert receive_until(ws, "cancelled")["request_id"] == "slow"
    assert client.get(f"/api/sessions/{sid}").json()["segments"] == []
