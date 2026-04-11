"""Opus decoding and WAV conversion for pendant audio."""

import struct
import wave
from pathlib import Path

from .config import SAMPLE_RATE, CHANNELS, OPUS_FRAME_SIZE, OPUS_FRAME_SAMPLES


def decode_bin_to_wav(bin_path: Path, wav_path: Path) -> int:
    """Decode a .bin file (length-prefixed Opus chunks) to WAV.

    Each chunk in the .bin is a length-prefixed blob of raw concatenated Opus
    frames from one flash page. We decode by parsing TOC bytes to find frame
    boundaries within each chunk.

    Returns number of individual Opus frames decoded.
    """
    # Read all chunks and concatenate the raw Opus data
    all_opus = bytearray()
    with open(bin_path, "rb") as f:
        while True:
            length_bytes = f.read(4)
            if not length_bytes or len(length_bytes) < 4:
                break
            chunk_len = struct.unpack("<I", length_bytes)[0]
            if chunk_len <= 0 or chunk_len > 50000:
                break
            chunk = f.read(chunk_len)
            if len(chunk) != chunk_len:
                break
            all_opus.extend(chunk)

    if not all_opus:
        # Write empty WAV
        with wave.open(str(wav_path), "wb") as w:
            w.setnchannels(CHANNELS)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
        return 0

    return decode_raw_opus_to_wav(bytes(all_opus), wav_path)


def decode_raw_opus_to_wav(opus_data: bytes, wav_path: Path, verbose: bool = False) -> int:
    """Decode raw concatenated Opus frames (no length prefix) to WAV.

    Uses TOC byte parsing to find frame boundaries.
    Returns number of frames decoded.
    """
    import opuslib

    decoder = opuslib.Decoder(SAMPLE_RATE, CHANNELS)

    # Duration to samples mapping at 16kHz
    DURATION_SAMPLES = {
        2.5: 40, 5: 80, 10: 160, 20: 320, 40: 640, 60: 960,
    }

    DOMINANT_TOC = 0xB8  # CELT 20ms - what the pendant typically uses

    pcm_chunks = []
    offset = 0
    frame_count = 0
    errors = 0

    while offset < len(opus_data):
        toc_byte = opus_data[offset]
        duration_ms = _toc_to_duration_ms(toc_byte)
        expected_samples = DURATION_SAMPLES.get(duration_ms, 320)

        # Look for next dominant TOC byte as boundary hint
        next_toc = None
        for i in range(30, min(100, len(opus_data) - offset)):
            if opus_data[offset + i] == DOMINANT_TOC:
                next_toc = i
                break

        sizes = list(range(30, min(80, len(opus_data) - offset + 1)))
        if next_toc and next_toc in sizes:
            sizes.remove(next_toc)
            sizes.insert(0, next_toc)

        decoded = None
        for sz in sizes:
            try:
                frame = opus_data[offset:offset + sz]
                pcm = decoder.decode(frame, max(expected_samples, OPUS_FRAME_SIZE))
                if pcm and (len(pcm) // 2 == expected_samples or sz == next_toc):
                    decoded = (pcm, sz)
                    break
            except Exception:
                continue

        if decoded:
            pcm_chunks.append(decoded[0])
            offset += decoded[1]
            frame_count += 1
        else:
            offset += 1
            errors += 1
            if errors > 100000:
                break

    if not pcm_chunks:
        return 0

    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        for chunk in pcm_chunks:
            wav.writeframes(chunk)

    return frame_count


def _toc_to_duration_ms(toc_byte: int) -> int:
    """Parse Opus TOC byte to get frame duration in ms."""
    config = (toc_byte >> 3) & 0x1F
    if config <= 11:  # SILK
        return [10, 20, 40, 60][config % 4]
    elif config <= 15:  # Hybrid
        return [10, 20][(config - 12) % 2]
    else:  # CELT
        return [2.5, 5, 10, 20][(config - 16) % 4]
