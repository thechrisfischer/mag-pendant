"""Local transcription using faster-whisper."""

from pathlib import Path
from typing import Optional


def transcribe_wav(wav_path: Path, output_path: Optional[Path] = None,
                   model_size: str = "base", language: str = "en") -> str:
    """Transcribe a WAV file using faster-whisper.

    Args:
        wav_path: Path to input WAV file
        output_path: Optional path to save transcript (default: same name + .txt)
        model_size: Whisper model size (tiny, base, small, medium, large-v3)
        language: Language code

    Returns:
        Transcribed text
    """
    from faster_whisper import WhisperModel

    if output_path is None:
        output_path = wav_path.with_suffix(".txt")

    print(f"Transcribing: {wav_path.name} (model={model_size})...")

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        str(wav_path), language=language,
        vad_filter=True,
        vad_parameters={
            "min_silence_duration_ms": 300,
            "speech_pad_ms": 200,
            "threshold": 0.3,
        },
    )

    lines = []
    for segment in segments:
        start = _format_time(segment.start)
        end = _format_time(segment.end)
        lines.append(f"[{start} -> {end}] {segment.text.strip()}")

    transcript = "\n".join(lines)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(transcript, encoding="utf-8")
    print(f"  Saved: {output_path.name} ({len(lines)} segments)")

    return transcript


def _format_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
