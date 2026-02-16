from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import requests


def _apply_pronunciation_hints(text: str) -> str:
    substitutions = [
        (r"\bCENTCOM\b", "SENT-kom"),
        (r"\bNATO\b", "NAY-toh"),
        (r"\bFEMA\b", "FEE-muh"),
        (r"\bCISA\b", "SIZ-uh"),
        (r"\bDHS\b", "D H S"),
        (r"\bTSA\b", "T S A"),
        (r"\bFAA\b", "F A A"),
        (r"\bEPA\b", "E P A"),
        (r"\bDOJ\b", "D O J"),
        (r"\bFBI\b", "F B I"),
        (r"\bNTSB\b", "N T S B"),
        (r"\bCBP\b", "C B P"),
        (r"\bICE\b", "I C E"),
    ]
    updated = text
    for pattern, replacement in substitutions:
        updated = re.sub(pattern, replacement, updated)
    return " ".join(updated.split())


def synthesize_cartesia_tts(
    *,
    cartesia_api_key: str,
    transcript: str,
    volume: float = 0.8,
    model_id: str = "sonic-3",
    voice_id: str = "79f8b5fb-2cc8-479a-80df-29f7a7cf1a3e",
    api_version: str = "2025-04-16",
) -> bytes:
    prepared_transcript = _apply_pronunciation_hints(transcript)
    headers = {
        "Cartesia-Version": api_version,
        "X-API-Key": cartesia_api_key,
        "Authorization": f"Bearer {cartesia_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model_id": model_id,
        "transcript": prepared_transcript,
        "voice": {
            "mode": "id",
            "id": voice_id,
        },
        "output_format": {
            "container": "wav",
            "encoding": "pcm_f32le",
            "sample_rate": 44100,
        },
        "speed": "normal",
        "generation_config": {
            "speed": 0.85,
            "volume": volume,
            "emotion": "excited",
        },
    }

    response = requests.post(
        "https://api.cartesia.ai/tts/bytes",
        headers=headers,
        json=payload,
        timeout=90,
    )
    response.raise_for_status()
    return response.content


def synthesize_silence_segment(*, duration_seconds: float, sample_rate: int = 44100) -> bytes:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be greater than zero")

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "silence.wav"
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={sample_rate}:cl=mono",
            "-t",
            str(duration_seconds),
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return output_path.read_bytes()


def _normalize_bunny_storage_host(region: str) -> str:
    cleaned = region.strip()
    if cleaned.startswith("https://"):
        cleaned = cleaned.removeprefix("https://")
    elif cleaned.startswith("http://"):
        cleaned = cleaned.removeprefix("http://")

    cleaned = cleaned.strip("/")
    if not cleaned:
        return "storage.bunnycdn.com"

    if cleaned.endswith(".bunnycdn.com"):
        return cleaned

    return f"{cleaned}.storage.bunnycdn.com"


def upload_bytes_to_bunny_storage(
    *,
    file_bytes: bytes,
    object_path: str,
    storage_zone: str,
    access_key: str,
    region: str,
    content_type: str = "audio/wav",
) -> str:
    normalized_path = "/".join(segment for segment in object_path.split("/") if segment)
    if not normalized_path:
        raise ValueError("object_path must not be empty")

    host = _normalize_bunny_storage_host(region=region)
    url = f"https://{host}/{storage_zone}/{normalized_path}"
    response = requests.put(
        url,
        headers={
            "AccessKey": access_key,
            "Content-Type": content_type,
        },
        data=file_bytes,
        timeout=120,
    )
    response.raise_for_status()
    return url


def concatenate_audio_segments(
    *,
    audio_segments: list[bytes],
    output_format: str = "wav",
) -> bytes:
    if len(audio_segments) < 2:
        raise ValueError("Need at least two audio segments to concatenate")

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        segment_paths: list[Path] = []
        for idx, segment in enumerate(audio_segments):
            segment_path = base / f"segment_{idx}.wav"
            segment_path.write_bytes(segment)
            segment_paths.append(segment_path)

        output_path = base / f"concatenated.{output_format}"
        filter_inputs = "".join([f"[{idx}:a]" for idx in range(len(segment_paths))])
        filter_complex = (
            f"{filter_inputs}concat=n={len(segment_paths)}:v=0:a=1,"
            "loudnorm=I=-16:TP=-1.5:LRA=11"
        )
        cmd = ["ffmpeg", "-y"]
        for segment_path in segment_paths:
            cmd.extend(["-i", str(segment_path)])
        cmd.extend(
            [
                "-filter_complex",
                filter_complex,
                "-ar",
                "44100",
                "-ac",
                "1",
                str(output_path),
            ]
        )
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return output_path.read_bytes()
