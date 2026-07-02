"""
Transcription Pipeline API

Endpoints:
  GET  /health                        - liveness check
  POST /upload                        - stage an audio file, returns file_id
  POST /transcribe                    - upload + normalize + transcribe in one call
  GET  /download/{file_id}_transcript.json - fetch a previously generated transcript
"""

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
import json
import logging

from app.storage import save_upload, UPLOAD_DIR
from app.audio_utils import normalize_audio, cleanup
from app.transcriber import transcribe_audio
from app.models import TranscriptionResponse, UploadResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("transcription-pipeline")

app = FastAPI(title="Transcription Pipeline", version="1.0.0")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/upload", response_model=UploadResponse)
async def upload_audio(file: UploadFile):
    return await save_upload(file)


@app.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(file: UploadFile):
    upload_result = await save_upload(file)
    raw_path = upload_result["path"]
    normalized_path = None

    try:
        normalized_path = normalize_audio(raw_path)
        result = transcribe_audio(normalized_path)
    except RuntimeError as e:
        raise HTTPException(422, str(e))
    except Exception:
        logger.exception("Transcription failed for file_id=%s", upload_result["file_id"])
        raise HTTPException(500, "Transcription failed")
    finally:
        cleanup(normalized_path)  # keep raw upload for audit/re-processing; drop the temp normalized copy

    result_path = UPLOAD_DIR / f"{upload_result['file_id']}_transcript.json"
    result_path.write_text(json.dumps(result, indent=2))

    return {
        "file_id": upload_result["file_id"],
        "full_text": result["text"],
        "segments": result["segments"],
        "metadata": {
            "language": result["language"],
            "language_probability": result["language_probability"],
            "duration": result["duration"],
            "transcript_url": f"/download/{upload_result['file_id']}_transcript.json",
        },
    }


@app.get("/download/{filename}")
async def download_transcript(filename: str):
    # Path(filename).name neutralizes traversal on the read path too
    safe_name = Path(filename).name
    path = UPLOAD_DIR / safe_name
    if not path.exists() or not safe_name.endswith("_transcript.json"):
        raise HTTPException(404, "Transcript not found")
    return FileResponse(path, media_type="application/json")
