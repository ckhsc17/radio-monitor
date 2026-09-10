#!/usr/bin/env python3
"""
Pipe radio-monitor style preprocessing (same chain as src/lib/ffmpeg.ts + 16 kHz mono
like whisper.cpp WHISPER_SAMPLE_RATE) from one BlackHole device into another, then
drive Wispr Flow and paste into the focused window.

Wispr Flow (Cmd+Shift+W): press when RMS passes squelch; release after silence
(aligned with src/transcribe.ts + preprocessorConfig). One AVFoundation capture
feeds both Wispr (via stdin→audiotoolbox) and RMS metering.

Setup (macOS):
  brew install ffmpeg blackhole-2ch
  Optional: brew install blackhole-16ch

Audio:
  - Route the source you want to BlackHole 2ch.
  - Wispr Flow microphone = BlackHole that receives ffmpeg output (--out-audio-device-index).

Automation:
  - Grant Accessibility to the terminal / Python.
  - Focus your .txt before paste, or increase --paste-delay.

List capture vs playback indices (they differ):
  python whispr.py list-devices
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import os
import shutil
import signal
import struct
import subprocess
import sys
import time

SAMPLE_RATE = 16_000

# Mirrors packages/radio-monitor/src/lib/ffmpeg.ts
AF_PREPROCESS = ",".join(
    [
        "highpass=f=300",
        "equalizer=f=630:width_type=h:w=15:g=-80",
        "equalizer=f=950:width_type=h:w=15:g=-80",
        "volume=10dB",
    ]
)

# Mirrors packages/radio-monitor/src/contstants.ts preprocessorConfig
DEFAULT_SQUELCH = 0.1
DEFAULT_SILENCE_MS = 1200
METER_CHUNK_BYTES = 3200


def calculate_rms(chunk: bytes) -> float:
    """Same normalization as packages/radio-monitor/src/utils/audio.ts calculateRMS."""
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
    """Single AVFoundation open: preprocessed s16le to stdout for tee + VAD."""
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
    """stdin s16le -> audiotoolbox (no second AVFoundation capture)."""
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


def _print_filtered_ffmpeg_output(raw: str) -> None:
    for line in raw.splitlines():
        if "Error opening" in line:
            continue
        if "Input/output error" in line:
            continue
        if "Error opening input files" in line:
            continue
        if "NSCameraUseContinuityCameraDeviceType" in line:
            continue
        print(line)


def _print_audiotoolbox_device_lines(raw: str) -> None:
    for line in raw.splitlines():
        if "[AudioToolbox" in line or "CoreAudio devices:" in line:
            print(line)


def cmd_list_devices() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        sys.exit("ffmpeg not found in PATH.")

    print("=== AVFoundation capture devices (use --in-audio-device-index) ===\n")
    r1 = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "info",
            "-f",
            "avfoundation",
            "-list_devices",
            "true",
            "-i",
            "",
        ],
        capture_output=True,
        text=True,
        errors="replace",
    )
    _print_filtered_ffmpeg_output((r1.stderr or "") + (r1.stdout or ""))

    print("\n=== AudioToolbox playback devices (use --out-audio-device-index) ===\n")
    r2 = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={SAMPLE_RATE}:cl=mono",
            "-t",
            "0.01",
            "-f",
            "audiotoolbox",
            "-list_devices",
            "true",
            "-y",
            "-",
        ],
        capture_output=True,
        text=True,
        errors="replace",
    )
    _print_audiotoolbox_device_lines((r2.stderr or "") + (r2.stdout or ""))


def run_bridge(in_idx: int, out_idx: int) -> subprocess.Popen[bytes]:
    cmd = build_bridge_command(in_idx, out_idx)
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def run_capture(in_idx: int) -> subprocess.Popen[bytes]:
    cmd = build_capture_to_stdout_command(in_idx)
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def run_playback(out_idx: int) -> subprocess.Popen[bytes]:
    cmd = build_playback_from_stdin_command(out_idx)
    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wispr_vad_tee_loop(
    cap_proc: subprocess.Popen[bytes],
    play_proc: subprocess.Popen[bytes],
    squelch: float,
    silence_ms: int,
    max_wait_s: float,
) -> None:
    import pyautogui

    pyautogui.PAUSE = 0.02
    cap_stdout = cap_proc.stdout
    play_stdin = play_proc.stdin
    assert cap_stdout is not None
    assert play_stdin is not None

    buf = b""
    wait_deadline = time.monotonic() + max_wait_s
    is_pressed = False
    silence_start: float | None = None

    def handle_chunk(chunk: bytes, now: float) -> bool:
        nonlocal is_pressed, silence_start
        rms = calculate_rms(chunk)
        if not is_pressed:
            if rms > squelch:
                pyautogui.keyDown("command")
                pyautogui.keyDown("shift")
                pyautogui.keyDown("w")
                is_pressed = True
                silence_start = None
            elif now > wait_deadline:
                raise TimeoutError(
                    "No audio above squelch before --max-wait-seconds; "
                    "lower --squelch-threshold or check routing."
                )
        else:
            if rms > squelch:
                silence_start = None
            else:
                if silence_start is None:
                    silence_start = now
                elif (now - silence_start) * 1000.0 >= silence_ms:
                    pyautogui.keyUp("w")
                    pyautogui.keyUp("shift")
                    pyautogui.keyUp("command")
                    is_pressed = False
                    cap_proc.terminate()
                    return True
        return False

    while True:
        piece = cap_stdout.read(4096)
        if not piece:
            break
        play_stdin.write(piece)
        buf += piece
        while len(buf) >= METER_CHUNK_BYTES:
            chunk = buf[:METER_CHUNK_BYTES]
            buf = buf[METER_CHUNK_BYTES:]
            now = time.monotonic()
            if handle_chunk(chunk, now):
                return

    if buf and len(buf) >= 2:
        now = time.monotonic()
        if handle_chunk(buf[: len(buf) // 2 * 2], now):
            return

    if is_pressed:
        pyautogui.keyUp("w")
        pyautogui.keyUp("shift")
        pyautogui.keyUp("command")


def paste_wispr_clipboard() -> None:
    import pyautogui

    pyautogui.hotkey("ctrl", "command", "v")


def run_flow(
    in_idx: int,
    out_idx: int,
    squelch: float,
    silence_ms: int,
    max_wait_s: float,
    after_record_delay: float,
    paste_delay: float,
    keep_bridge: bool,
) -> None:
    if importlib.util.find_spec("pyautogui") is None:
        sys.exit(
            "Missing dependency: pip install pyautogui "
            "(see scripts/whispr-requirements.txt)"
        )

    cap = run_capture(in_idx)
    play = run_playback(out_idx)
    time.sleep(0.35)

    if cap.poll() is not None:
        play.kill()
        sys.exit(
            "ffmpeg capture exited immediately. Check --in-audio-device-index "
            "(run: python whispr.py list-devices)."
        )
    if play.poll() is not None:
        cap.kill()
        sys.exit(
            "ffmpeg playback to audiotoolbox exited immediately. Check --out-audio-device-index."
        )

    run_ok = False
    try:
        assert cap.stdout is not None
        assert play.stdin is not None
        wispr_vad_tee_loop(cap, play, squelch, silence_ms, max_wait_s)
        play.stdin.close()
        time.sleep(after_record_delay)
        time.sleep(paste_delay)
        paste_wispr_clipboard()
        run_ok = True
    except TimeoutError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    except BrokenPipeError:
        sys.exit("ffmpeg pipe closed unexpectedly.")
    finally:
        cap.send_signal(signal.SIGTERM)
        try:
            cap.wait(timeout=2)
        except subprocess.TimeoutExpired:
            cap.kill()
        play.send_signal(signal.SIGTERM)
        try:
            play.wait(timeout=2)
        except subprocess.TimeoutExpired:
            play.kill()
    if run_ok and keep_bridge:
        br = run_bridge(in_idx, out_idx)
        time.sleep(0.2)
        if br.poll() is None:
            print(
                "Started background bridge (PID {}). Stop with kill or Activity Monitor.".format(
                    br.pid
                ),
                file=sys.stderr,
            )


def main() -> None:
    p = argparse.ArgumentParser(description="BlackHole → preprocess → Wispr Flow → paste")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list-devices", help="Print avfoundation inputs and audiotoolbox outputs")

    run_p = argparse.ArgumentParser(add_help=False)
    run_p.add_argument(
        "--in-audio-device-index",
        type=int,
        required=True,
        help="AVFoundation audio capture index. Run: python whispr.py list-devices",
    )
    run_p.add_argument(
        "--out-audio-device-index",
        type=int,
        required=True,
        help="AudioToolbox output index (Wispr mic). Run: python whispr.py list-devices",
    )
    run_p.add_argument(
        "--squelch-threshold",
        type=float,
        default=DEFAULT_SQUELCH,
        help="RMS above this starts Cmd+Shift+W (same scale as transcribe.ts).",
    )
    run_p.add_argument(
        "--silence-ms",
        type=int,
        default=DEFAULT_SILENCE_MS,
        help="Silence duration (ms) before key up, after speech.",
    )
    run_p.add_argument(
        "--max-wait-seconds",
        type=float,
        default=120.0,
        help="Give up if no signal crosses squelch within this time.",
    )
    run_p.add_argument(
        "--after-record-delay",
        type=float,
        default=2.0,
        help="Wait after key up before paste (clipboard fill time).",
    )
    run_p.add_argument(
        "--paste-delay",
        type=float,
        default=0.3,
        help="Extra delay before Ctrl+Cmd+V to focus the .txt window.",
    )
    run_p.add_argument(
        "--keep-bridge",
        action="store_true",
        help="After a successful run, start `bridge` in the background (continuous routing).",
    )

    bridge_p = argparse.ArgumentParser(add_help=False)
    bridge_p.add_argument("--in-audio-device-index", type=int, required=True)
    bridge_p.add_argument("--out-audio-device-index", type=int, required=True)

    sub.add_parser("bridge", parents=[bridge_p], help="Only run ffmpeg preprocess bridge")
    sub.add_parser("run", parents=[run_p], help="Bridge + VAD-gated Wispr + paste")

    args = p.parse_args()
    if args.command == "list-devices":
        cmd_list_devices()
        return

    if args.command == "bridge":
        cmd = build_bridge_command(args.in_audio_device_index, args.out_audio_device_index)
        os.execvp(cmd[0], cmd)

    if args.command == "run":
        run_flow(
            in_idx=args.in_audio_device_index,
            out_idx=args.out_audio_device_index,
            squelch=args.squelch_threshold,
            silence_ms=args.silence_ms,
            max_wait_s=args.max_wait_seconds,
            after_record_delay=args.after_record_delay,
            paste_delay=args.paste_delay,
            keep_bridge=args.keep_bridge,
        )
        return

    p.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
