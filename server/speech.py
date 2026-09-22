"""Local speech services. Runtime never fetches models; downloads are explicit jobs."""
from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from functools import lru_cache
from typing import Callable
import wave

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["HF_HUB_DISABLE_UPDATE_CHECK"] = "1"
os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
os.environ["DO_NOT_TRACK"] = "1"
if "--download" not in sys.argv:
    os.environ["HF_HUB_OFFLINE"] = "1"

STT_REPO = "Systran/faster-whisper-small.en"
DIARIZATION_REPO = "pyannote/speaker-diarization-community-1"
PIPER_REPO = "rhasspy/piper-voices"
PIPER_VOICE = "en_US-lessac-medium"
Progress = Callable[[float, str], None]
_stt_lock = threading.RLock()
_tts_lock = threading.RLock()
_diarization_lock = threading.RLock()


def _paths(settings: dict) -> dict[str, Path]:
    root = Path(os.environ.get("HELIOS_MODELS_DIR", str(Path(__file__).resolve().parent.parent / "data" / "models")))
    speech = settings.get("speech", {}) or {}
    return {
        "stt": Path(speech.get("stt_path") or root / "faster-whisper-small.en"),
        "tts": Path(speech.get("tts_path") or root / "piper" / f"{PIPER_VOICE}.onnx"),
        "diarization": Path(speech.get("diarization_path") or root / "speaker-diarization-community-1"),
    }


def _has_package(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def _model_problem(component: str, path: Path) -> str | None:
    if component == "stt":
        missing = [name for name in ("model.bin", "config.json", "tokenizer.json") if not (path / name).is_file()]
        if missing:
            return "Speech recognition model is missing or incomplete. Download small.en in Settings or select a complete local model directory."
    elif component == "tts":
        if not path.is_file() or not Path(str(path) + ".json").is_file():
            return "Interviewer voice is missing. Download the Piper voice in Settings, or select an ONNX file with its matching .onnx.json file."
    elif component == "diarization":
        if not (path / "config.yaml").is_file() or not any(p.is_file() for pattern in ("*.bin", "*.safetensors", "*.ckpt") for p in path.rglob(pattern)):
            return "Speaker separation model is missing or incomplete. Finish the Community-1 download in Settings."
    return None


def readiness(settings: dict) -> dict:
    packages = {"stt": ["faster_whisper", "av"], "tts": ["piper"], "diarization": ["pyannote.audio", "torch", "av"]}
    result = {}
    for component, path in _paths(settings).items():
        missing = [package for package in packages[component] if not _has_package(package)]
        problem = "Install the optional speech dependencies using the setup script (missing: " + ", ".join(missing) + ")." if missing else _model_problem(component, path)
        result[component] = {"ready": problem is None, "message": problem or "Local model files and dependencies available. CPU inference; model loading is checked when first used."}
    return result


def _require(component: str, settings: dict) -> Path:
    status = readiness(settings)[component]
    if not status["ready"]:
        raise RuntimeError(status["message"])
    return _paths(settings)[component].resolve()


def _decode_audio(source):
    """Decode with PyAV (bundled FFmpeg), bypassing TorchCodec audio loading."""
    import av
    import numpy as np
    try:
        chunks = []
        with av.open(io.BytesIO(source) if isinstance(source, bytes) else str(source)) as container:
            if not container.streams.audio:
                raise ValueError("This recording contains no audio track.")
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)
            for frame in container.decode(audio=0):
                for output in resampler.resample(frame):
                    chunks.append(output.to_ndarray().reshape(-1))
            for output in resampler.resample(None):
                chunks.append(output.to_ndarray().reshape(-1))
        if not chunks:
            raise ValueError("This recording contains no decodable audio.")
        return np.concatenate(chunks).astype(np.float32, copy=False)
    except ValueError as exc:
        # PyAV's InvalidDataError also subclasses ValueError.
        if str(exc).startswith("This recording contains"):
            raise
        raise ValueError("Cannot decode this recording. Try a WAV, MP3, M4A, WebM, or MP4 file with an audio track.") from exc
    except Exception as exc:
        raise ValueError("Cannot decode this recording. Try a WAV, MP3, M4A, WebM, or MP4 file with an audio track.") from exc


@lru_cache(maxsize=1)
def _whisper(path: str):
    try:
        from faster_whisper import WhisperModel
        return WhisperModel(path, device="cpu", compute_type="int8", local_files_only=True)
    except Exception as exc:
        raise RuntimeError("Cannot load the local speech recognition model. Rerun Setup-Helios.ps1 to repair speech dependencies, or select/download a complete faster-whisper model in Settings.") from exc


@lru_cache(maxsize=1)
def _piper(path: str):
    try:
        from piper import PiperVoice
        return PiperVoice.load(path, use_cuda=False)
    except Exception as exc:
        raise RuntimeError("Cannot load the local Piper voice. Rerun Setup-Helios.ps1 to repair speech dependencies, and check that the ONNX voice and matching .onnx.json are together.") from exc


@lru_cache(maxsize=1)
def _diarizer(path: str):
    try:
        from pyannote.audio import Pipeline
        import torch
        # A local path is deliberate: a Hub identifier may make network calls.
        pipeline = Pipeline.from_pretrained(path)
        pipeline.to(torch.device("cpu"))
        return pipeline
    except Exception as exc:
        raise RuntimeError("Cannot load the local Community-1 pipeline. Install the optional speaker dependencies with Setup-Helios.ps1, or finish its model download in Settings. You can still label speakers manually.") from exc


def transcribe(wav_bytes: bytes, settings: dict) -> list[dict]:
    path = _require("stt", settings)
    if not wav_bytes:
        return []
    audio = _decode_audio(wav_bytes)
    with _stt_lock:
        segments, _ = _whisper(str(path)).transcribe(audio, language="en", vad_filter=True, condition_on_previous_text=False)
        return [{"text": segment.text.strip(), "start": float(segment.start), "end": float(segment.end)} for segment in segments if segment.text.strip()]


def synthesize(text: str, settings: dict) -> bytes:
    path = _require("tts", settings)
    if not text.strip():
        raise ValueError("There is no text to speak.")
    buffer = io.BytesIO()
    with _tts_lock:
        with wave.open(buffer, "wb") as wav_file:
            _piper(str(path)).synthesize_wav(text, wav_file)
    return buffer.getvalue()


def _speaker_for_interval(start: float, end: float, turns: list[tuple[float, float, str]]) -> str | None:
    scores: dict[str, float] = {}
    for turn_start, turn_end, speaker in turns:
        overlap = max(0.0, min(end, turn_end) - max(start, turn_start))
        if overlap:
            scores[speaker] = scores.get(speaker, 0.0) + overlap
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked or (len(ranked) > 1 and abs(ranked[0][1] - ranked[1][1]) < 0.001):
        return None
    return ranked[0][0]


def _align_words(segments: list, turns: list[tuple[float, float, str]]) -> list[dict]:
    result: list[dict] = []
    for segment in segments:
        words = getattr(segment, "words", None)
        pieces = [(float(word.start), float(word.end), word.word) for word in words] if words else [(float(segment.start), float(segment.end), segment.text)]
        for start, end, text in pieces:
            if not text.strip():
                continue
            speaker = _speaker_for_interval(start, end, turns)
            if result and result[-1]["speaker"] == speaker and start - result[-1]["end"] < 1.5:
                result[-1]["text"] += text if text.startswith(" ") else " " + text
                result[-1]["end"] = end
            else:
                result.append({"text": text.strip(), "start": start, "end": end, "speaker": speaker, "role": "unknown"})
    return result


def process_upload(path, settings: dict, progress_callback: Progress) -> list[dict]:
    stt_path = _require("stt", settings)
    progress_callback(0.05, "Decoding recording locally")
    waveform = _decode_audio(path)
    progress_callback(0.15, "Transcribing recording on CPU")
    with _stt_lock:
        generated, _ = _whisper(str(stt_path)).transcribe(waveform, language="en", word_timestamps=True, vad_filter=True, condition_on_previous_text=False)
        segments = []
        duration = len(waveform) / 16000
        for segment in generated:
            segments.append(segment)
            progress_callback(0.15 + 0.40 * min(segment.end / max(duration, 1), 1), "Transcribing recording on CPU")
    if not segments:
        progress_callback(1.0, "No speech detected")
        return []
    # A speaker model is optional for imports: keep the actual transcription and
    # expose short editable segments instead of inventing a speaker assignment.
    def manual_transcript():
        return [{"text": segment.text.strip(), "start": float(segment.start), "end": float(segment.end), "speaker": None, "role": "unknown"}
                for segment in segments if segment.text.strip()]
    status = readiness(settings)["diarization"]
    if not status["ready"]:
        progress_callback(1.0, "Transcript ready; label speakers manually. " + status["message"])
        return manual_transcript()
    diarization_path = _paths(settings)["diarization"].resolve()
    progress_callback(0.58, "Separating speakers locally on CPU")
    callback_failure: list[Exception] = []
    def hook(step_name, *args, **kwargs):
        # Checking the callback at each hook also lets the task runner cancel.
        completed, total = kwargs.get("completed"), kwargs.get("total")
        fraction = (completed / total) if completed is not None and total else 0
        try:
            progress_callback(0.60 + 0.30 * min(fraction, 1), "Separating speakers: " + str(step_name).replace("_", " "))
        except Exception as exc:
            callback_failure.append(exc)
            raise
    try:
        import torch
        with _diarization_lock:
            pipeline = _diarizer(str(diarization_path))
            output = pipeline({"waveform": torch.from_numpy(waveform).unsqueeze(0), "sample_rate": 16000}, hook=hook)
        annotation = output.exclusive_speaker_diarization
        turns = [(float(turn.start), float(turn.end), str(speaker)) for turn, _, speaker in annotation.itertracks(yield_label=True)]
    except Exception:
        # Cancellation is a control signal, never a successful fallback.
        if callback_failure:
            raise callback_failure[0]
        progress_callback(1.0, "Transcript ready; automatic speaker separation failed. Label speakers manually or check the local Community-1 model and speech dependencies, then retry.")
        return manual_transcript()
    progress_callback(0.95, "Matching speakers to transcript; identify your voice before assessment")
    result = _align_words(segments, turns)
    progress_callback(1.0, "Transcript and speakers ready for review")
    return result


def download_model(component: str, token: str | None, settings: dict, models_dir, progress_callback: Progress) -> dict:
    """An explicit setup action. Use a child to isolate online Hub configuration."""
    if component not in {"stt", "tts", "diarization"}:
        raise ValueError("Choose speech recognition, interviewer voice, or speaker separation.")
    if component == "diarization" and not token:
        raise ValueError("Accept Community-1 conditions on Hugging Face, then provide a read token for this download only.")
    progress_callback(0.02, "Downloading local model; this may take several minutes")
    environment = dict(os.environ)
    environment.pop("HF_HUB_OFFLINE", None)
    # Never borrow or persist an existing Hugging Face account credential.
    environment.pop("HF_TOKEN", None)
    environment.pop("HUGGING_FACE_HUB_TOKEN", None)
    request = json.dumps({"component": component, "token": token, "models_dir": str(Path(models_dir).resolve())})
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--download"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        first = True
        while True:
            try:
                stdout, _ = process.communicate(request if first else None, timeout=1)
                break
            except subprocess.TimeoutExpired:
                first = False
                request = ""
                progress_callback(0.10, "Downloading model files; no interview data is being uploaded")
        if process.returncode:
            try:
                detail = json.loads(stdout).get("error", "Model download failed.")
            except (ValueError, TypeError):
                detail = "Model download failed. Check internet access, available disk space, and model access permissions."
            raise RuntimeError(detail)
        result = json.loads(stdout)
        progress_callback(0.90, "Checking downloaded local model")
        updated = {**settings, "speech": {**settings.get("speech", {}), **result}}
        local_path = _require(component, updated)
        # Loading from disk verifies the inference dependency chain too.
        if component == "stt":
            with _stt_lock:
                _whisper(str(local_path))
        elif component == "tts":
            synthesize("Helios is ready.", updated)
        else:
            with _diarization_lock:
                _diarizer(str(local_path))
        progress_callback(1.0, "Local model ready")
        return result
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
        token = None
        request = ""


def _download_entry() -> None:
    """Token arrives on stdin and is not written to configuration or logs."""
    try:
        from huggingface_hub import HfApi, hf_hub_download, snapshot_download
        request = json.loads(sys.stdin.read())
        component = request["component"]
        root = Path(request["models_dir"])
        root.mkdir(parents=True, exist_ok=True)
        token = request.pop("token", None)
        if component in {"stt", "diarization"}:
            repository = STT_REPO if component == "stt" else DIARIZATION_REPO
            target = root / ("faster-whisper-small.en" if component == "stt" else "speaker-diarization-community-1")
            revision = HfApi().model_info(repository, token=token or False).sha
            snapshot_download(repo_id=repository, revision=revision, local_dir=str(target), token=token or False)
            result = {component + "_path": str(target.resolve())}
        elif component == "tts":
            target = root / "piper"
            target.mkdir(parents=True, exist_ok=True)
            revision = HfApi().model_info(PIPER_REPO, token=False).sha
            import shutil
            for suffix in (".onnx", ".onnx.json"):
                filename = "en/en_US/lessac/medium/" + PIPER_VOICE + suffix
                downloaded = hf_hub_download(repo_id=PIPER_REPO, filename=filename, revision=revision, token=False)
                shutil.copyfile(downloaded, target / (PIPER_VOICE + suffix))
            result = {"tts_path": str((target / (PIPER_VOICE + ".onnx")).resolve())}
        else:
            raise ValueError("Unknown component")
        (target / "helios-model.json").write_text(json.dumps({"component": component, "revision": revision}), encoding="utf-8")
        token = None
        print(json.dumps(result))
    except Exception as exc:
        # Exception strings can contain request headers/URLs: do not echo them.
        print(json.dumps({"error": "Model download failed (" + type(exc).__name__ + "). Check internet access, disk space and, for speaker separation, accepted model conditions and token permissions."}))
        raise SystemExit(1)


if __name__ == "__main__" and "--download" in sys.argv:
    _download_entry()
