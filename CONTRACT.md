# Helios implementation contract

Local React/TypeScript + FastAPI application. No invented AI output. Persistent state in SQLite and local media. API returns JSON objects; collection lists are plain arrays. All API errors use `{detail: string}`. `GET /api/bootstrap` returns `{jobs, rounds, sessions, preparations, assessments, drills, tasks, settings, readiness}`. Each record has `id`, `created_at`, `updated_at`.

## Records
- Job: `title, company, description, resume_text, requirements: string[], seniority, status`.
- Round: `job_id, title, kind, scheduled_at, status, outcome, notes`.
- Session: `job_id, round_id?, kind, mode: learning|mock, difficulty, duration_minutes, status, source: practice|upload, title, recording_url?, candidate_speaker?, duration_seconds`.
- Transcript segment: `id, session_id, role: candidate|interviewer|unknown|other, speaker?, text, start, end` (seconds).
- Preparation: `job_id, plan` (AI service owns validated plan schema).
- Assessment: `session_id, report` (AI service owns validated report schema).
- Drill: `job_id, session_id, title, instruction, skill, completed`.
- Task: `kind, target_id, status: queued|running|completed|failed|cancelled, progress, message, error?`.
- Settings: `offline: true`, `provider: {kind: ollama|lmstudio|openai_compatible|openai|codex, base_url, model}`, `pause_ms:1800`, `ignore_mic_while_speaking:false`, `speech: {stt_path, tts_path, diarization_path}`. Secrets submitted as `api_key` are server-side only; responses omit secrets.

## HTTP
- GET `/api/bootstrap`, GET/PATCH `/api/settings`.
- GET/POST `/api/jobs`; PATCH/DELETE `/api/jobs/{id}`.
- POST `/api/documents/extract` multipart `file` => `{text}`.
- POST `/api/jobs/{id}/extract` => background Task, updates requirements.
- POST `/api/jobs/{id}/prepare` => background Task, creates Preparation.
- GET/POST `/api/rounds`; PATCH/DELETE `/api/rounds/{id}`.
- GET/POST `/api/sessions`; GET `/api/sessions/{id}` => `{session,segments,assessments}`; DELETE `/api/sessions/{id}`.
- POST `/api/sessions/{id}/end` => Task (assessment, skip if no candidate text).
- POST `/api/sessions/{id}/assess` => Task. POST `/api/sessions/{id}/hint` => `{text}` (learning only).
- PATCH `/api/segments/{id}` editable text/role/start/end. POST `/api/sessions/{id}/speakers` body `{mapping:{SPEAKER_00:'candidate',SPEAKER_01:'interviewer'}}`.
- POST `/api/sessions/{id}/chunks?seq=N` raw media body + Content-Type => `{ok:true}`. POST `/api/sessions/{id}/finalize` body `{duration_seconds,mime_type}` => Session. GET `/api/sessions/{id}/recording` audio stream with Range support.
- POST `/api/imports` multipart `file,job_id,title` => `{session,task}`.
- PATCH `/api/drills/{id}`. POST `/api/tasks/{id}/retry`; POST `/api/tasks/{id}/cancel`.
- POST `/api/providers/test` body provider config + optional api_key => `{ok,models:[string],message}`. GET `/api/readiness` => `{llm:{ready,message},stt:{ready,message},tts:{ready,message},diarization:{ready,message},vad:{ready,message}}`.
- POST `/api/models/download` body `{component:stt|tts|diarization|llm,token?}` => Task. Explicit user action only.
- GET `/api/codex/status`; POST `/api/codex/login`; POST `/api/codex/logout` => safe availability/status fields.
- GET `/api/backup` zip download; POST `/api/restore` multipart file. Excludes secrets/models; validates archive.

## Live WebSocket `/api/sessions/{id}/live`
Same-origin cookie authenticated. JSON browser -> server:
- `{type:'start',request_id}` starts first question (or resumes existing transcript).
- `{type:'answer',text,request_id,start,end}` typed answer.
- `{type:'audio',audio:<base64 WAV>,request_id,start,end}` transcribe answer.
- `{type:'interrupt',request_id}`, `{type:'pause'}`, `{type:'end'}`.
Server -> browser:
- `{type:'state',value:'listening'|'transcribing'|'thinking'|'speaking',request_id}`
- `{type:'segment',segment,request_id}` candidate/interviewer persisted transcript.
- `{type:'question',text,audio:<base64 WAV or null>,segment,request_id}`
- `{type:'error',message,request_id}`
- `{type:'cancelled',request_id}`.
Each generation can be cancelled; ignore events for obsolete request_id. Audio may be absent if TTS not set up: text still works. Audio failures do not erase text/recordings.

## Backend module ownership
Root: `server/app.py`, `server/store.py`, tests, launch/setup scripts, dependency manifests, final integration.
AI agent: `server/ai.py`, `server/codex_provider.py`, AI schema files/tests only. Async `test_provider(settings)->dict`, `requirements(job,settings)->list[str]`, `prepare(job,settings)->dict`, `next_turn(job,session,segments,settings)->dict {question,topic,difficulty}`, `assess(job,session,segments,settings)->dict`, `hint(job,session,segments,settings)->str`. Settings include server-only api_key. Raise actionable exceptions.
Speech agent: `server/speech.py`, `frontend/src/useInterviewAudio.ts`, `scripts/copy-vad.mjs`, own speech/audio tests. `readiness(settings)->dict`, `transcribe(wav_bytes,settings)->list[dict{text,start,end}]`, `synthesize(text,settings)->bytes`, `process_upload(path,settings,progress_callback)->list[segments with speaker role unknown]`, `download_model(component,token,settings,models_dir,progress_callback)->dict of updated paths`. Blocking funcs called in threads. Hook contract coordinate with frontend agent.
Frontend agent: frontend UI files except audio hook and copy-vad. Root creates package.json. Agent can request dependencies. Use lucide-react icons; hand-built accessible UI, responsive charcoal/amber work surface.

Security: loopback only; enforce allowed Host and same-origin browser requests; HttpOnly session token cookie created by same-origin bootstrap. No secrets to browser/local storage/logs. Offline blocks non-loopback provider hosts and redirects; disables runtime downloads/telemetry. Uploads treated as data. All generated outputs validated. Do not implement fake successes.
