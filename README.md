# Helios

A personal interview workbench that runs at **http://localhost:8765**. Your job descriptions, rounds, preparation plans, audio, transcripts and feedback stay in the local `data` directory. No account is needed for local use.

## Start on Windows

1. Install Node.js 22+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).
2. Run `powershell -ExecutionPolicy Bypass -File .\Setup-Helios.ps1`. This installs an isolated Python 3.11 environment, speech libraries and frontend dependencies, and builds the app. Model weights are not downloaded.
3. Double-click **Start-Helios.cmd**. Use `Stop-Helios.ps1` to stop the background service.

The launcher binds only to 127.0.0.1. Keep the local server running while using Helios. Closing the browser preserves saved data. The optional `-WithoutSpeakerSeparation` setup flag skips the larger speaker libraries while keeping transcript labeling available.

## First offline interview

Open **Settings**. Choose a provider and check each readiness card:

- **Ollama:** Install [Ollama](https://ollama.com/download), keep it running, and select a local model. The preset is `qwen3:8b` (approximately 5.2 GB). Helios's Download button requests the model from your local Ollama server. LM Studio and other local OpenAI-compatible servers also work.
- **Transcription:** Download the English `small.en` model, or enter a complete local faster-whisper model directory.
- **Voice:** Download Piper `en_US-lessac-medium`, or enter the local `.onnx` path with its matching `.onnx.json` file.
- **Speaker separation:** Accept the [Community-1 model conditions](https://huggingface.co/pyannote/speaker-diarization-community-1), then provide a temporary Hugging Face download token in Settings. Helios does not save that token. Alternatively, select an already downloaded model directory. The extra model is only required to automatically separate speakers in uploads.

Downloads are explicit setup actions and use the internet even when the app is set to offline operation. Interview processing itself does not download missing files. Offline mode blocks non-loopback AI endpoints and cloud-backed Ollama models; there is no automatic cloud fallback. All browser voice detection assets are bundled locally. Headphones help prevent the interviewer voice from triggering the microphone.

Create a job, paste its description, optionally extract a resume, then review the requirements. Generate preparation material and start a Learning or Mock session. Voice practice supports automatic turn detection, interruptions, and typed answers. Final reports use a five-point practice rubric with verified candidate transcript evidence. They are not predictions of hiring decisions.

## Recordings and uploads

Microphone and played interviewer audio are mixed into independent PCM WAV chunks. Pending chunks remain in browser IndexedDB until acknowledged by the backend. Reopen the same session in the same browser to recover interrupted uploads. Keep the browser open until End finishes saving. Changing browsers or clearing site storage can remove chunks that have not yet reached the server.

Upload audio or video files up to 1 GB. Helios preserves the original, transcribes locally, and attempts local speaker separation. Confirm which speaker is you before requesting feedback. If separation is unavailable, label transcript segments manually and confirm. Transcript edits mark older reports as outdated; regenerate to assess corrections. Audio playback supports byte ranges and transcript timestamps.

## Optional online providers

Disable Offline mode explicitly before selecting an online endpoint. API keys use the operating system credential store and are not included in backups. OpenAI API usage is billed separately from ChatGPT subscriptions.

The **ChatGPT via Codex** connection currently reports unavailable: the installed Codex protocol cannot yet be verified to disable every execution tool for this text-only coach. Helios deliberately does not launch that provider, reuse Codex credentials, or offer a misleading login. Local providers and API-key connections remain available. See [Codex app-server documentation](https://learn.chatgpt.com/docs/app-server).

## Data and backups

Settings provides backup/restore for SQLite data and recordings. Backups exclude models, credentials, caches, and browser-pending audio. Restore replaces current records, preserves a recovery copy under `data/tmp`, and enables offline mode. Review/delete local recovery copies when no longer needed. Use the same Windows account to access its saved API credentials.

## Development and verification

```powershell
uv sync --extra dev --extra speakers
npm ci
npm run build
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.cache/pytest
.\.venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8765 --ws-max-size 33554432
```

Use `npm run dev` for the frontend at port 5173, with the API running on port 8765. SQLite storage can be redirected with `HELIOS_DATA_DIR`. Production uses the compiled `dist` directory and no frontend development server. The application contains no fabricated AI reports or seeded interview history.

## Current boundaries

English audio and transcripts; no webcam recording, direct Zoom/Teams capture, coding execution, or calendar integration. Transcription, speech and speaker models require setup before offline use. CPU processing can take time; GPU acceleration and model quality depend on the chosen runtime. Resume extraction supports text PDFs and DOCX, not scanned-image OCR. Keep model and package license notices when redistributing; Piper's runtime is GPL-3.0 and model licenses vary.
