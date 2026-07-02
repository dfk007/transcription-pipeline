# Transcription Pipeline

A minimal, production-informed audio transcription service built with **FastAPI** and **faster-whisper**. Accepts an audio file, normalizes it, transcribes it with per-segment (and per-word) timestamps, and returns/persists the result as JSON.

## Quick start

```bash
docker compose up --build -d
curl -s http://localhost:8000/health

curl -X POST http://localhost:8000/transcribe \
  -F "file=@test_audio/sample.mp3" | python3 -m json.tool
```

First run will download the Whisper model weights (~150MB for `base`) into a cached volume; subsequent runs are fast.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| POST | `/upload` | Stage a file, returns `file_id` — no transcription |
| POST | `/transcribe` | Upload + normalize + transcribe in one call |
| GET | `/download/{file_id}_transcript.json` | Fetch a previously generated transcript |

## Design decisions

**Model: faster-whisper over vanilla openai-whisper.**
CTranslate2 backend gives roughly 4x the throughput on CPU with `int8` quantization, at negligible WER cost. Since the brief explicitly says "the focus is on engineering decisions, not training a model from scratch," I optimized for a self-hosted, no-API-key, CPU-viable path rather than a cloud STT API (Deepgram/AssemblyAI/Google) — no external cost, no rate limits, no vendor lock-in, and it's the same class of tooling I run in production for LLM serving infra.

**Format handling: normalize everything to one canonical format.**
Every input (WAV/MP3/M4A/OGG/FLAC/WebM) is piped through `ffmpeg` to 16kHz mono PCM16 WAV before it reaches the model:
```bash
ffmpeg -i input.mp3 -ar 16000 -ac 1 -c:a pcm_s16le normalized.wav
```
This gives one tested code path instead of N format-specific branches, and matches the sample rate Whisper's encoder expects internally, avoiding silent resampling quality loss.

**Timestamps: segment-level and word-level.**
faster-whisper produces both natively via `word_timestamps=True` — no separate forced-alignment step (e.g. `whisperx`) is needed, which keeps the pipeline to one dependency instead of two.

**Upload handling: streamed, chunked, path-safe.**
Files are read in 1MB chunks (`await file.read(...)`) and written straight to disk rather than buffered fully in memory, so multi-GB uploads don't spike service memory under concurrent load. Filenames are sanitized with `Path(filename).name` to strip any injected path segments (`../../etc/passwd.wav`) before being used to construct a disk path — this closes a real path-traversal vector (CWE-22), not a theoretical one.

**Silence handling: VAD filtering.**
faster-whisper's built-in VAD strips non-speech segments before decoding. Real-world audio (calls, meetings) is often 20-40% dead air; stripping it cuts compute proportionally with no accuracy trade-off.

**What's deliberately out of scope for this submission (see System Design answers below for how I'd extend it):**
- Async job queue (Redis/Celery) — the brief's Part 1 scope is a synchronous script/service; I've noted the async design in Part 2.
- Object storage (S3/MinIO) — local disk is used for this submission; swapping `app/storage.py` to write to MinIO is a contained change since storage is already isolated from transcription logic.
- Multi-tenant auth/RBAC — omitted for scope; would add API-key or JWT middleware in front of all routes for a real deployment.

## System design answers (Part 2)

**Concurrent uploads.** Each upload gets a UUID and writes to a unique path, so there's no collision risk under concurrency. FastAPI would run behind multiple Uvicorn/Gunicorn workers so uploads aren't serialized on one process. For real scale, I'd decouple upload from transcription entirely: `/upload` just stages the file and enqueues a job (Redis/Celery), so concurrent uploads don't compete with concurrent (CPU-bound) transcriptions. Transcription worker concurrency would be capped to available CPU cores — Whisper is compute-bound, and oversubscribing causes thrashing rather than more throughput.

**Storage.** Object storage (S3 or self-hosted MinIO) for both raw audio and transcript JSON, keyed by the same `file_id` so they're trivially correlated. Local disk is only a transient staging area during upload/processing before the push to object storage. Job/transcript metadata (status, duration, language, timestamps) would live in Postgres for querying and filtering — object storage for the payload, DB for anything that needs to be searched or joined on.

**Retry / recovery.** Job status (`queued` / `processing` / `failed` / `done`) tracked in Postgres so nothing depends on in-memory state. Failures retry with exponential backoff (3 attempts is usually sufficient — Whisper failures are almost always transient: OOM, corrupt chunk, worker crash, not deterministic). After max retries, the job is marked `failed` and surfaced via the status endpoint rather than silently dropped. If a worker crashes mid-job, the queue's visibility timeout redelivers the message so a dead worker doesn't lose the job.

**API exposure.** REST, async-first for anything beyond a quick synchronous test: `POST /upload` → `POST /transcribe/{file_id}` (enqueues) → `GET /jobs/{job_id}` (poll) → `GET /transcripts/{file_id}` (fetch result). An optional webhook callback for clients who don't want to poll. Behind API-key or JWT auth given this processes potentially sensitive audio content.

## Project structure

```
transcription-pipeline/
├── app/
│   ├── main.py          # FastAPI routes
│   ├── storage.py        # upload validation, path-safe streamed writes
│   ├── audio_utils.py    # ffmpeg format normalization
│   ├── transcriber.py    # faster-whisper model + transcription logic
│   └── models.py          # Pydantic response schemas
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── test_audio/
```

## Local development (without Docker)

```bash
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# ffmpeg must be installed on the host: apt install ffmpeg / brew install ffmpeg
uvicorn app.main:app --reload --port 8000
```

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `WHISPER_MODEL` | `base` | Model size: `tiny`, `base`, `small`, `medium`, `large-v3` — trade-off between speed and accuracy |
| `WHISPER_CPU_THREADS` | `8` | CPU threads for CTranslate2 inference |

## Known limitations / next steps

- No async job queue yet — long files (>10 min) will hold the HTTP connection open for the duration of transcription. See System Design answers above for the planned fix.
- No auth on endpoints — add before any non-local deployment.
- `base` model favors speed; swap `WHISPER_MODEL=small` or `medium` for better accuracy at the cost of ~2-3x latency.
