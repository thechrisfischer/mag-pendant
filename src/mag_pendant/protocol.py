"""BLE protocol layer: protobuf encoding/decoding and fragment reassembly."""

from datetime import datetime
from typing import Optional

from . import pendant_pb2 as pb


class PendantProtocol:
    """Encodes commands and decodes responses using the Limitless protobuf protocol."""

    def __init__(self):
        self.message_index = 0
        self.pending_fragments: dict[int, list[Optional[bytes]]] = {}

    # -- Outgoing: create BLE-wrapped commands --

    def create_command(self, cmd_type: str, **kwargs) -> bytes:
        """Create a BLE-wrapped ServerCommandMsg."""
        cmd = pb.ServerCommandMsg()

        request_data = pb.RequestData()
        request_data.request_id = self.message_index + 1
        cmd.request_data.CopyFrom(request_data)

        match cmd_type:
            case "set_current_time":
                msg = pb.SetCurrentTime()
                msg.timestamp_ms = kwargs.get("timestamp_ms", int(datetime.now().timestamp() * 1000))
                cmd.set_current_time.CopyFrom(msg)

            case "get_device_info":
                cmd.get_device_info.CopyFrom(pb.GetDeviceInfo())

            case "get_device_status":
                cmd.get_device_status.CopyFrom(pb.GetDeviceStatus())

            case "download_flash_pages":
                dl = pb.DownloadFlashPages()
                dl.batch_mode_enabled = kwargs.get("batch", True)
                dl.real_time_mode_enabled = kwargs.get("realtime", False)
                cmd.download_flash_pages.CopyFrom(dl)

            case "start_recording":
                cmd.start_recording.CopyFrom(pb.StartRecording())

            case "stop_recording":
                cmd.stop_recording.CopyFrom(pb.StopRecording())

            case "set_server_public_key":
                key_msg = pb.SetServerPublicKey()
                key_msg.public_key = kwargs["public_key"]
                cmd.set_audio_encryption_server_public_key.CopyFrom(key_msg)

            case "set_led_brightness":
                msg = pb.SetLEDBrightness()
                msg.brightness = kwargs.get("brightness", 100)
                cmd.set_led_brightness.CopyFrom(msg)

            case "clear_storage":
                cmd.clear_pendant_storage.CopyFrom(pb.ClearPendantStorage())

            case _:
                raise ValueError(f"Unknown command: {cmd_type}")

        return self._wrap_ble(cmd.SerializeToString())

    def _wrap_ble(self, payload: bytes) -> bytes:
        """Wrap payload in BLE message envelope."""
        msg = pb.BLEMessageFromNativeToPendant()
        msg.index = self.message_index
        msg.ble_fragment_seq = 0
        msg.num_fragments = 1
        msg.payload = payload
        self.message_index += 1
        return msg.SerializeToString()

    # -- Incoming: parse BLE notifications --

    def parse_notification(self, data: bytes) -> Optional[bytes]:
        """Parse BLE notification, handle fragmentation. Returns complete payload or None."""
        try:
            msg = pb.BLEMessageFromPendantToNative()
            msg.ParseFromString(bytes(data))

            if msg.num_fragments == 1:
                return msg.payload

            # Fragment reassembly
            idx = msg.index
            if idx not in self.pending_fragments:
                self.pending_fragments[idx] = [None] * msg.num_fragments

            self.pending_fragments[idx][msg.ble_fragment_seq] = msg.payload

            if all(f is not None for f in self.pending_fragments[idx]):
                complete = b"".join(self.pending_fragments[idx])
                del self.pending_fragments[idx]
                return complete

            return None
        except Exception:
            return None

    def parse_response(self, payload: bytes) -> Optional[dict]:
        """Parse a PendantAllMsg response into a dict."""
        try:
            msg = pb.PendantAllMsg()
            msg.ParseFromString(payload)

            content_type = msg.WhichOneof("content")
            result = {"type": content_type}

            if content_type == "device_info":
                info = msg.device_info
                result.update({
                    "firmware_version": info.firmware_version,
                    "hardware_version": info.hardware_version,
                    "serial_number": info.serial_number,
                    "device_name": info.device_name,
                })

            elif content_type == "device_status":
                status = msg.device_status
                is_recording = False
                if status.HasField("recording_status"):
                    is_recording = status.recording_status.recording_state == 1

                storage_percent = 0
                storage_state = None
                if status.HasField("storage_state"):
                    ss = status.storage_state
                    total = ss.total_capture_pages
                    free = ss.free_capture_pages
                    if total > 0:
                        storage_percent = int((total - free) / total * 100)
                    storage_state = {
                        "oldest_page": ss.oldest_flash_page,
                        "newest_page": ss.newest_flash_page,
                        "session": ss.current_storage_session,
                        "free_pages": ss.free_capture_pages,
                        "total_pages": ss.total_capture_pages,
                    }

                result.update({
                    "is_recording": is_recording,
                    "storage_percent": storage_percent,
                    "storage_state": storage_state,
                })

            elif content_type == "storage_buffer":
                buf = msg.storage_buffer
                result.update({
                    "session": buf.session,
                    "run": buf.run,
                    "seq": buf.seq,
                    "index": buf.index,
                    "flash_page": buf.flash_page,
                    "error": buf.flash_page_error,
                })

            elif content_type == "battery_status":
                bat = msg.battery_status
                result.update({
                    "level": bat.soc,
                    "charging": bat.state in (1, 4),
                    "voltage": bat.voltage,
                })

            elif content_type == "set_current_time_response":
                result["success"] = msg.set_current_time_response.success

            elif content_type == "button_status":
                result["pressed"] = msg.button_status.pressed

            return result
        except Exception as e:
            return {"type": "parse_error", "error": str(e)}

    def extract_audio_from_flash_page(self, data: bytes) -> dict:
        """Extract audio data and metadata from a FlashPage protobuf.

        Returns dict with keys: opus_data, pcm_data, timestamp_ms, boot_uptime_ms
        """
        result = {
            "opus_data": bytearray(),
            "pcm_data": bytearray(),
            "encrypted_data": bytearray(),
            "timestamp_ms": 0,
            "boot_uptime_ms": 0,
            "num_chunks": 0,
        }

        try:
            page = pb.FlashPage()
            page.ParseFromString(data)

            result["timestamp_ms"] = page.absolute_timestamp_ms
            result["boot_uptime_ms"] = page.boot_uptime_ms
            result["num_chunks"] = len(page.chunks)

            for chunk in page.chunks:
                has_audio = chunk.HasField("audio_data") if hasattr(chunk, "HasField") else bool(chunk.audio_data.ByteSize())
                if not has_audio:
                    continue

                audio = chunk.audio_data

                # Primary: Opus-encoded beamformed audio
                if audio.codec_beamforming_data:
                    result["opus_data"].extend(audio.codec_beamforming_data)
                if audio.codec_manual_beamforming_data:
                    result["opus_data"].extend(audio.codec_manual_beamforming_data)

                # Fallback: raw PCM
                for field in ("pcm_omni_mic_data", "pcm_directional_mic_data",
                              "pcm_beamforming_data", "pcm_manual_beamforming_data"):
                    pcm = getattr(audio, field, b"")
                    if pcm:
                        result["pcm_data"].extend(pcm)

                # Encrypted audio
                if audio.HasField("encrypted_codec_beamforming_data"):
                    enc = audio.encrypted_codec_beamforming_data
                    result["encrypted_data"].extend(enc.ciphertext)

        except Exception as e:
            result["error"] = str(e)

        return result
