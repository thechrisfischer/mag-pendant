"""BLE connection management: scanning, connecting, and communicating with the pendant."""

import asyncio
import struct
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from bleak import BleakClient, BleakScanner

from .config import (
    AUDIO_SERVICE_UUID, CONTROL_UUID, DATA_UUID,
    BATTERY_LEVEL_UUID, PENDANT_ADDRESS,
    DOWNLOADS_DIR, GAP_THRESHOLD_MS, MIN_VALID_TIMESTAMP_MS,
    SAFE_PAGE_LIMIT, SECONDS_PER_FLASH_PAGE,
)
from .protocol import PendantProtocol


async def scan_for_pendant(timeout: float = 10.0) -> Optional[dict]:
    """Scan for Limitless pendant. Returns {address, name, rssi} or None."""
    print(f"Scanning for pendant ({timeout}s)...")
    best = None

    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for addr, (device, adv) in devices.items():
        name = adv.local_name or device.name or ""
        services = set(str(s) for s in (adv.service_uuids or []))

        score = 0
        if AUDIO_SERVICE_UUID in services:
            score = 100
        elif "limitless" in name.lower():
            score = 80
        elif "pendant" in name.lower():
            score = 60

        if score > 0 and (best is None or score > best["score"]):
            best = {
                "address": addr,
                "name": name,
                "rssi": adv.rssi,
                "score": score,
                "services": services,
            }

    if best:
        print(f"Found: {best['name']} ({best['address']}) RSSI={best['rssi']}dBm")
    else:
        print("No pendant found. Make sure it's powered on and not connected elsewhere.")

    return best


class PendantConnection:
    """Manages BLE connection to the Limitless pendant."""

    def __init__(self, address: str):
        self.address = address
        self.protocol = PendantProtocol()
        self.client: Optional[BleakClient] = None
        self._response_handlers: list[Callable] = []

        # Download state
        self._pages: list[dict] = []
        self._device_info: Optional[dict] = None
        self._device_status: Optional[dict] = None
        self._battery: Optional[dict] = None
        self._status_event = asyncio.Event()

    async def connect(self) -> bool:
        """Connect to the pendant via BLE."""
        print(f"Connecting to {self.address}...")
        # pair=True triggers macOS system pairing dialog (required for encrypted GATT)
        self.client = BleakClient(self.address, timeout=20.0, pair=True)
        await self.client.connect()

        if not self.client.is_connected:
            print("Connection failed!")
            return False

        mtu = self.client.mtu_size
        print(f"Connected (MTU: {mtu})")

        # Subscribe to notifications
        await self.client.start_notify(DATA_UUID, self._on_notification)
        await asyncio.sleep(1.0)

        # Initialize: sync time, then enable data stream
        await self._send("set_current_time")
        await asyncio.sleep(1.0)

        # Enable real-time data stream (required before status/batch commands work)
        await self._send("download_flash_pages", batch=False, realtime=True)
        await asyncio.sleep(1.0)

        return True

    async def disconnect(self):
        """Clean disconnect."""
        if self.client and self.client.is_connected:
            try:
                await self.client.stop_notify(DATA_UUID)
            except Exception:
                pass
            await self.client.disconnect()
            print("Disconnected.")

    async def _send(self, cmd_type: str, **kwargs):
        """Send a command to the pendant."""
        data = self.protocol.create_command(cmd_type, **kwargs)
        await self.client.write_gatt_char(CONTROL_UUID, data, response=True)

    def _on_notification(self, sender, data: bytes):
        """Handle incoming BLE notification."""
        payload = self.protocol.parse_notification(data)
        if not payload:
            return

        response = self.protocol.parse_response(payload)
        if not response:
            return

        rtype = response.get("type")

        if rtype == "device_info":
            self._device_info = response
        elif rtype == "device_status":
            self._device_status = response
            self._status_event.set()
        elif rtype == "battery_status":
            self._battery = response
        elif rtype == "storage_buffer":
            self._pages.append(response)

        for handler in self._response_handlers:
            handler(response)

    # -- High-level commands --

    async def get_info(self) -> dict:
        """Get device info (firmware, serial, etc.)."""
        self._device_info = None
        await self._send("get_device_info")
        await asyncio.sleep(1.0)
        return self._device_info or {}

    async def get_status(self) -> dict:
        """Get device status (recording state, storage)."""
        self._status_event.clear()
        self._device_status = None
        await self._send("get_device_status")
        try:
            await asyncio.wait_for(self._status_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pass
        return self._device_status or {}

    async def get_battery(self) -> Optional[int]:
        """Read battery level from standard BLE Battery Service."""
        try:
            data = await self.client.read_gatt_char(BATTERY_LEVEL_UUID)
            if data and len(data) > 0:
                return int(data[0])
        except Exception:
            pass
        # Fall back to protocol battery status
        if self._battery:
            return self._battery.get("level")
        return None

    async def download_audio(self, output_dir: Optional[Path] = None,
                             on_progress: Optional[Callable] = None) -> list[Path]:
        """Download all stored audio from pendant flash memory.

        Returns list of saved .bin file paths (length-prefixed Opus frames).
        """
        output_dir = output_dir or DOWNLOADS_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get storage status first
        status = await self.get_status()
        storage = status.get("storage_state")
        if not storage:
            print("Could not get storage status.")
            return []

        oldest = storage["oldest_page"]
        newest = storage["newest_page"]
        total_pages = newest - oldest + 1

        if total_pages <= 0:
            print("No audio data on pendant.")
            return []

        pages_to_download = min(total_pages, SAFE_PAGE_LIMIT)
        est_duration = pages_to_download * SECONDS_PER_FLASH_PAGE
        print(f"Downloading {pages_to_download} pages (~{est_duration/60:.1f} min of audio)...")

        # Enable batch mode
        self._pages.clear()
        await self._send("download_flash_pages", batch=True, realtime=False)

        # Collect pages with timeout
        started = time.monotonic()
        last_page_time = started
        saved_files: list[Path] = []

        # Conversation segmentation state
        current_file: Optional[Path] = None
        current_handle = None
        last_timestamp_ms = 0
        page_count = 0

        try:
            while True:
                await asyncio.sleep(0.1)

                while self._pages:
                    page_data = self._pages.pop(0)
                    last_page_time = time.monotonic()

                    flash_page = page_data.get("flash_page", b"")
                    if not flash_page:
                        continue

                    audio = self.protocol.extract_audio_from_flash_page(flash_page)
                    opus_data = bytes(audio["opus_data"])
                    timestamp_ms = audio["timestamp_ms"]

                    if not opus_data:
                        continue

                    page_count += 1

                    # Detect conversation gap -> start new file
                    if (last_timestamp_ms > 0 and timestamp_ms > MIN_VALID_TIMESTAMP_MS
                            and abs(timestamp_ms - last_timestamp_ms) > GAP_THRESHOLD_MS):
                        if current_handle:
                            current_handle.close()
                            saved_files.append(current_file)
                            print(f"\n  Saved: {current_file.name}")
                            current_handle = None
                            current_file = None

                    # Start new file if needed
                    if current_handle is None:
                        if timestamp_ms > MIN_VALID_TIMESTAMP_MS:
                            ts = datetime.fromtimestamp(timestamp_ms / 1000)
                            fname = ts.strftime("%Y-%m-%d_%H%M") + ".bin"
                        else:
                            fname = f"recording_{int(time.time())}.bin"
                        current_file = output_dir / fname
                        current_handle = open(current_file, "wb")

                    if timestamp_ms > MIN_VALID_TIMESTAMP_MS:
                        last_timestamp_ms = timestamp_ms

                    # Write length-prefixed Opus frames
                    # The opus data from the pendant is raw concatenated frames,
                    # we write the whole chunk with a length prefix for easy decoding
                    current_handle.write(struct.pack("<I", len(opus_data)))
                    current_handle.write(opus_data)
                    current_handle.flush()

                    if on_progress:
                        on_progress(page_count, pages_to_download, len(saved_files))
                    else:
                        pct = page_count / pages_to_download * 100
                        print(f"\r  Progress: {page_count}/{pages_to_download} pages ({pct:.0f}%)", end="", flush=True)

                # Check if done
                if page_count >= pages_to_download:
                    break

                # Timeout: no new pages for 10s
                if time.monotonic() - last_page_time > 10.0:
                    print(f"\n  Timeout after {page_count} pages.")
                    break

                # Hard timeout: 10 minutes
                if time.monotonic() - started > 600:
                    print(f"\n  Hard timeout reached.")
                    break

        finally:
            # Close current file
            if current_handle:
                current_handle.close()
                if current_file:
                    saved_files.append(current_file)
                    print(f"\n  Saved: {current_file.name}")

            # Switch back to real-time mode
            await self._send("download_flash_pages", batch=False, realtime=True)

        print(f"\nDownload complete: {page_count} pages -> {len(saved_files)} file(s)")
        return saved_files
