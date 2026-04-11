"""Shared constants and configuration."""

import os
from pathlib import Path

# BLE UUIDs (Limitless pendant custom service)
AUDIO_SERVICE_UUID = "632de001-604c-446b-a80f-7963e950f3fb"
CONTROL_UUID = "632de002-604c-446b-a80f-7963e950f3fb"
DATA_UUID = "632de003-604c-446b-a80f-7963e950f3fb"

# Standard BLE services
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

# Audio specs (fixed by pendant firmware)
SAMPLE_RATE = 16000
CHANNELS = 1
OPUS_FRAME_SIZE = 960  # 60ms at 16kHz (max decode buffer)
OPUS_FRAME_DURATION_MS = 20  # typical frame duration
OPUS_FRAME_SAMPLES = 320  # 20ms at 16kHz

# Data paths
DATA_DIR = Path(os.environ.get("MAG_DATA_DIR", Path.home() / ".mag-pendant"))
DOWNLOADS_DIR = DATA_DIR / "downloads"
WAV_DIR = DATA_DIR / "wav"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
KEYS_DIR = DATA_DIR / "keys"

# Pendant address (set via env or auto-discovered)
PENDANT_ADDRESS = os.environ.get("PENDANT_ADDRESS")

# Timestamp validation
MIN_VALID_TIMESTAMP_MS = 1_700_000_000_000  # Nov 2023

# Download limits
SAFE_PAGE_LIMIT = 2000
SECONDS_PER_FLASH_PAGE = 1.4
GAP_THRESHOLD_MS = 60_000  # 60s silence = new conversation
