"""
Pydantic schemas for the transcription pipeline API.
Kept separate from route/business logic so they can be reused by
OpenAPI docs generation and by any future async worker/consumer.
"""

from pydantic import BaseModel
from typing import List, Optional


class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float


class Segment(BaseModel):
    start: float
    end: float
    text: str
    words: List[WordTimestamp] = []


class UploadResponse(BaseModel):
    file_id: str
    filename: str
    path: str
    size_bytes: int
    status: str = "uploaded"


class TranscriptionMetadata(BaseModel):
    language: str
    language_probability: Optional[float] = None
    duration: float
    transcript_url: str


class TranscriptionResponse(BaseModel):
    file_id: str
    full_text: str
    segments: List[Segment]
    metadata: TranscriptionMetadata
