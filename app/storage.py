"""
Upload handling: validation, path-traversal safe naming, streamed
disk writes. Kept isolated from transcription logic so storage can
be swapped for S3/MinIO later without touching the model code.
"""

from fastapi import UploadFile, HTTPException
from pathlib import Path
import uuid

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}
CHUNK_SIZE = 1 << 20  # 1MB
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB — tune to your infra / adjust via env if needed


async def save_upload(file: UploadFile) -> dict:
    if not file.filename:
        raise HTTPException(400, "Missing filename")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported format: {ext}. Allowed: {sorted(ALLOWED_EXTENSIONS)}")

    file_id = str(uuid.uuid4())
    # Path(file.filename).name strips any directory components the client
    # may have injected (path traversal, e.g. "../../etc/passwd.wav")
    safe_filename = Path(file.filename).name
    path = UPLOAD_DIR / f"{file_id}_{safe_filename}"

    size = 0
    try:
        with open(path, "wb") as f:
            while chunk := await file.read(CHUNK_SIZE):
                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    raise HTTPException(413, f"File exceeds {MAX_FILE_SIZE // (1024*1024)}MB limit")
                f.write(chunk)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise

    return {
        "file_id": file_id,
        "filename": file.filename,
        "path": str(path),
        "size_bytes": size,
        "status": "uploaded",
    }
