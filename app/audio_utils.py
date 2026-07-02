"""
Format normalization via ffmpeg.

Every supported input format (WAV/MP3/M4A/OGG/FLAC/WebM) is converted
to 16kHz mono PCM16 WAV before hitting the model — this gives a single
tested code path regardless of input codec/container, and matches the
sample rate faster-whisper's encoder expects internally.
"""

import subprocess
import tempfile
import os


def normalize_audio(input_path: str) -> str:
    output_path = tempfile.mktemp(suffix=".wav")
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-ar", "16000",       # 16kHz sample rate
        "-ac", "1",            # mono
        "-c:a", "pcm_s16le",   # uncompressed PCM — avoids re-encode artifacts
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg normalization failed: {result.stderr[-500:]}")
    return output_path


def cleanup(*paths: str) -> None:
    for p in paths:
        if p and os.path.exists(p):
            os.remove(p)
