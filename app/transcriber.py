"""
Core transcription logic using faster-whisper (CTranslate2 backend).

Model is loaded once as a module-level singleton — avoids reloading
weights (~1-3s+ depending on model size) on every request.
"""

from faster_whisper import WhisperModel
import torch
import os

_MODEL = None


def get_model() -> WhisperModel:
    global _MODEL
    if _MODEL is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        _MODEL = WhisperModel(
            model_size_or_path=os.getenv("WHISPER_MODEL", "base"),
            device=device,
            compute_type=compute_type,
            cpu_threads=int(os.getenv("WHISPER_CPU_THREADS", "8")),
        )
    return _MODEL


def transcribe_audio(file_path: str) -> dict:
    model = get_model()

    segments_gen, info = model.transcribe(
        file_path,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,  # strips silence before decoding — cuts compute on real-world audio
        vad_parameters=dict(min_silence_duration_ms=500),
        condition_on_previous_text=True,  # improves coherence across long-form segments
    )

    segments = []
    for seg in segments_gen:
        segments.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
            "words": [
                {"word": w.word, "start": round(w.start, 2), "end": round(w.end, 2)}
                for w in (seg.words or [])
            ],
        })

    return {
        "text": " ".join(s["text"] for s in segments),
        "segments": segments,
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "duration": round(info.duration, 2),
    }
