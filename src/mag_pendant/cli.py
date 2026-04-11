"""CLI interface for mag-pendant."""

import asyncio
import sys
from pathlib import Path

import click

from .config import (
    PENDANT_ADDRESS, DOWNLOADS_DIR, WAV_DIR, TRANSCRIPTS_DIR, DATA_DIR,
)


@click.group()
def cli():
    """mag-pendant: Sync audio and transcripts from your Limitless pendant."""
    pass


@cli.command()
@click.option("--timeout", default=10.0, help="Scan timeout in seconds")
def scan(timeout):
    """Scan for nearby Limitless pendants."""
    from .connection import scan_for_pendant

    result = asyncio.run(scan_for_pendant(timeout=timeout))
    if result:
        click.echo(f"\nTo use this device, run:")
        click.echo(f"  export PENDANT_ADDRESS={result['address']}")


@cli.command()
def status():
    """Show pendant status (battery, storage, recording state)."""
    _require_address()
    from .connection import PendantConnection

    async def _status():
        conn = PendantConnection(PENDANT_ADDRESS)
        try:
            if not await conn.connect():
                return

            info = await conn.get_info()
            status = await conn.get_status()
            battery = await conn.get_battery()

            click.echo(f"\n  Device:    {info.get('device_name', '?')}")
            click.echo(f"  Firmware:  {info.get('firmware_version', '?')}")
            click.echo(f"  Serial:    {info.get('serial_number', '?')}")
            click.echo(f"  Battery:   {battery or '?'}%")
            click.echo(f"  Recording: {'Yes' if status.get('is_recording') else 'No'}")
            click.echo(f"  Storage:   {status.get('storage_percent', '?')}% used")

            ss = status.get("storage_state")
            if ss:
                pages = ss["newest_page"] - ss["oldest_page"] + 1
                click.echo(f"  Pages:     {pages} ({ss['oldest_page']} -> {ss['newest_page']})")
                click.echo(f"  Free:      {ss['free_pages']}/{ss['total_pages']} pages")
        finally:
            await conn.disconnect()

    asyncio.run(_status())


@cli.command()
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output directory for .bin files")
def download(output):
    """Download recorded audio from pendant flash memory."""
    _require_address()
    from .connection import PendantConnection

    output_dir = Path(output) if output else DOWNLOADS_DIR

    async def _download():
        conn = PendantConnection(PENDANT_ADDRESS)
        try:
            if not await conn.connect():
                return

            files = await conn.download_audio(output_dir=output_dir)
            if files:
                click.echo(f"\nFiles saved to: {output_dir}")
                for f in files:
                    click.echo(f"  {f.name}")
        finally:
            await conn.disconnect()

    asyncio.run(_download())


@cli.command()
@click.argument("input_path", type=click.Path(exists=True), required=False)
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output directory for .wav files")
def convert(input_path, output):
    """Convert downloaded .bin files to .wav audio."""
    from .audio import decode_bin_to_wav

    input_dir = Path(input_path) if input_path else DOWNLOADS_DIR
    output_dir = Path(output) if output else WAV_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    if input_dir.is_file():
        bin_files = [input_dir]
    else:
        bin_files = sorted(input_dir.glob("*.bin"))

    if not bin_files:
        click.echo(f"No .bin files found in {input_dir}")
        return

    click.echo(f"Converting {len(bin_files)} file(s)...")

    for bf in bin_files:
        wav_path = output_dir / (bf.stem + ".wav")
        frames = decode_bin_to_wav(bf, wav_path)
        duration = frames * 0.02  # ~20ms per frame
        click.echo(f"  {bf.name} -> {wav_path.name} ({duration:.0f}s, {frames} frames)")

    click.echo(f"\nWAV files saved to: {output_dir}")


@cli.command()
@click.argument("input_path", type=click.Path(exists=True), required=False)
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output directory for transcripts")
@click.option("--model", "-m", default="base",
              type=click.Choice(["tiny", "base", "small", "medium", "large-v3"]),
              help="Whisper model size")
@click.option("--language", "-l", default="en", help="Language code")
def transcribe(input_path, output, model, language):
    """Transcribe .wav files to text using Whisper."""
    from .transcribe import transcribe_wav

    input_dir = Path(input_path) if input_path else WAV_DIR
    output_dir = Path(output) if output else TRANSCRIPTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    if input_dir.is_file():
        wav_files = [input_dir]
    else:
        wav_files = sorted(input_dir.glob("*.wav"))

    if not wav_files:
        click.echo(f"No .wav files found in {input_dir}")
        return

    click.echo(f"Transcribing {len(wav_files)} file(s) with model '{model}'...")

    for wf in wav_files:
        txt_path = output_dir / (wf.stem + ".txt")
        text = transcribe_wav(wf, txt_path, model_size=model, language=language)
        word_count = len(text.split())
        click.echo(f"  {wf.name} -> {txt_path.name} ({word_count} words)")

    click.echo(f"\nTranscripts saved to: {output_dir}")


@cli.command()
@click.option("--model", "-m", default="base",
              type=click.Choice(["tiny", "base", "small", "medium", "large-v3"]),
              help="Whisper model size")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Base output directory")
def sync(model, output):
    """Full pipeline: download -> convert -> transcribe."""
    _require_address()
    from .connection import PendantConnection
    from .audio import decode_bin_to_wav
    from .transcribe import transcribe_wav

    base_dir = Path(output) if output else DATA_DIR
    dl_dir = base_dir / "downloads"
    wav_dir = base_dir / "wav"
    txt_dir = base_dir / "transcripts"

    async def _sync():
        # Phase 1: Download
        click.echo("=== Phase 1: Download ===")
        conn = PendantConnection(PENDANT_ADDRESS)
        bin_files = []
        try:
            if not await conn.connect():
                return
            bin_files = await conn.download_audio(output_dir=dl_dir)
        finally:
            await conn.disconnect()

        if not bin_files:
            click.echo("No new audio to process.")
            return

        # Phase 2: Convert
        click.echo("\n=== Phase 2: Convert to WAV ===")
        wav_dir.mkdir(parents=True, exist_ok=True)
        wav_files = []
        for bf in bin_files:
            wav_path = wav_dir / (bf.stem + ".wav")
            frames = decode_bin_to_wav(bf, wav_path)
            duration = frames * 0.02
            click.echo(f"  {bf.name} -> {wav_path.name} ({duration:.0f}s)")
            wav_files.append(wav_path)

        # Phase 3: Transcribe
        click.echo(f"\n=== Phase 3: Transcribe (model={model}) ===")
        txt_dir.mkdir(parents=True, exist_ok=True)
        for wf in wav_files:
            txt_path = txt_dir / (wf.stem + ".txt")
            transcribe_wav(wf, txt_path, model_size=model)

        click.echo(f"\n=== Done! ===")
        click.echo(f"  Audio:       {dl_dir}")
        click.echo(f"  WAV:         {wav_dir}")
        click.echo(f"  Transcripts: {txt_dir}")

    asyncio.run(_sync())


def _require_address():
    """Exit if PENDANT_ADDRESS is not set."""
    if not PENDANT_ADDRESS:
        click.echo("Error: PENDANT_ADDRESS not set.")
        click.echo("Run 'mag scan' to find your pendant, then:")
        click.echo("  export PENDANT_ADDRESS=<address>")
        sys.exit(1)


if __name__ == "__main__":
    cli()
