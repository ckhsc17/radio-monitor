"""Shared radio-monitor preprocessing: matches packages/radio-monitor/src/lib/ffmpeg.ts and 16 kHz mono (whisper.cpp)."""

from __future__ import annotations

import math
import shutil
import struct
import sys
from pathlib import Path

SAMPLE_RATE = 16_000

AF_PREPROCESS = ",".join(
    [
        "highpass=f=300",
        "equalizer=f=630:width_type=h:w=15:g=-80",
        "equalizer=f=950:width_type=h:w=15:g=-80",
        "dynaudnorm=p=0.95:m=100:s=5",
    ]
)

METER_CHUNK_BYTES = 3200


def calculate_rms(chunk: bytes) -> float:
    n = len(chunk) // 2
    if n == 0:
        return 0.0
    sum_squares = 0.0
    for i in range(n):
        sample = struct.unpack_from("<h", chunk, i * 2)[0] / 32768.0
        sum_squares += sample * sample
    return math.sqrt(sum_squares / n)


def build_bridge_command(in_audio_index: int, out_audio_index: int) -> list[str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        sys.exit("ffmpeg not found in PATH. Install: brew install ffmpeg")

    return [
        ffmpeg,
        "-nostdin",
        "-loglevel",
        "error",
        "-f",
        "avfoundation",
        "-i",
        f":{in_audio_index}",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-af",
        AF_PREPROCESS,
        "-f",
        "audiotoolbox",
        "-audio_device_index",
        str(out_audio_index),
        "-y",
        "-",
    ]


def build_capture_to_stdout_command(in_audio_index: int) -> list[str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        sys.exit("ffmpeg not found in PATH. Install: brew install ffmpeg")

    return [
        ffmpeg,
        "-nostdin",
        "-loglevel",
        "error",
        "-f",
        "avfoundation",
        "-i",
        f":{in_audio_index}",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-af",
        AF_PREPROCESS,
        "-f",
        "s16le",
        "-",
    ]


def build_playback_from_stdin_command(out_audio_index: int) -> list[str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        sys.exit("ffmpeg not found in PATH. Install: brew install ffmpeg")

    return [
        ffmpeg,
        "-loglevel",
        "error",
        "-f",
        "s16le",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        "-i",
        "-",
        "-f",
        "audiotoolbox",
        "-audio_device_index",
        str(out_audio_index),
        "-y",
        "-",
    ]


def build_audio_file_to_stdout_command(audio_path: Path) -> list[str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        sys.exit("ffmpeg not found in PATH. Install: brew install ffmpeg")

    return [
        ffmpeg,
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(audio_path.resolve()),
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-af",
        AF_PREPROCESS,
        "-f",
        "s16le",
        "-",
    ]
