#!/usr/bin/env python3
"""
Gemma 4 E4B radio pipeline: Ollama check, VAD WAV segments (≤30s), infer.

Default infer path: Whisper STT → Gemma text (structured JSON, handles noisy ASR).
Use --ollama-audio-first to try Ollama multimodal (WAV) before Whisper.

Run from package root:
  cd packages/radio-monitor
  pip install -r scripts/gemma4-requirements.txt
  python scripts/gemma4_pipeline.py check-ollama
  python scripts/gemma4_pipeline.py segment-mic --in-audio-device-index 0 --output-dir ./segments
  python scripts/gemma4_pipeline.py infer --wav ./segments/seg_00001.wav

See docs/gemma4-radio.md.
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import NoReturn

import requests

from radio_audio_core import (
    METER_CHUNK_BYTES,
    SAMPLE_RATE,
    build_audio_file_to_stdout_command,
    build_capture_to_stdout_command,
    calculate_rms,
)

logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_PROMPT_PATH = SCRIPTS_DIR / "prompts" / "radio_system.txt"
DEFAULT_OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")
DEFAULT_WHISPER_URL = os.environ.get("WHISPER_API_URL", "http://127.0.0.1:8080/inference")

OLLAMA_GEN_OPTIONS = {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "num_ctx": 2048}


def resolve_whisper_first(args: argparse.Namespace) -> bool:
    if getattr(args, "whisper_first", False) or getattr(args, "skip_ollama_audio", False):
        return True
    if getattr(args, "ollama_audio_first", False):
        return False
    return True

USER_INSTRUCTION_AUDIO = (
    "Process the attached preprocessed EMS radio audio segment. "
    "Respond with only the JSON object (keys raw_transcript, polished, reasoning, summary) as specified in the system message."
)

USER_INSTRUCTION_TEXT = (
    "The following is a raw ASR transcript of an EMS radio segment. "
    "It may contain homophone errors, dropped syllables, or garbage tokens; use context and domain knowledge to infer likely "
    "intended terms, but never invent clinical facts not supported by the transcript. "
    "Respond with only the JSON object (keys raw_transcript, polished, reasoning, summary) as specified in the system message.\n\n"
    "Raw transcript:\n"
)


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [gemma4] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
        force=True,
    )


def wav_duration_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            if rate <= 0:
                return None
            return frames / float(rate)
    except (wave.Error, OSError):
        return None


def load_system_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def write_wav_s16le_mono(path: Path, pcm_s16le: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm_s16le)


def segment_s16le_stream(
    stream,
    output_dir: Path,
    squelch: float,
    silence_ms: int,
    max_chunk_seconds: float,
    prefix: str = "seg",
) -> list[Path]:
    max_bytes = int(max_chunk_seconds * SAMPLE_RATE * 2)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    seq = 0

    def flush_segment(pcm: bytes) -> None:
        nonlocal seq
        if len(pcm) < SAMPLE_RATE * 2:
            return
        seq += 1
        p = output_dir / f"{prefix}_{seq:05d}.wav"
        write_wav_s16le_mono(p, pcm)
        written.append(p)
        dur = len(pcm) / (2 * SAMPLE_RATE)
        logger.info("Wrote segment %s (%.2fs, %d bytes PCM)", p, dur, len(pcm))

    buf = b""
    accumulating = False
    seg = b""
    silence_t0: float | None = None

    def flush_hard_splits() -> None:
        nonlocal seg
        while len(seg) >= max_bytes:
            flush_segment(seg[:max_bytes])
            seg = seg[max_bytes:]

    def process_meter_chunk(chunk: bytes, now: float) -> None:
        nonlocal accumulating, seg, silence_t0
        rms = calculate_rms(chunk)
        loud = rms > squelch

        if not accumulating:
            if loud:
                accumulating = True
                seg = chunk
                silence_t0 = None
            return

        seg += chunk
        if loud:
            silence_t0 = None
        else:
            if silence_t0 is None:
                silence_t0 = now
            elif (now - silence_t0) * 1000.0 >= silence_ms:
                flush_hard_splits()
                if seg:
                    flush_segment(seg)
                seg = b""
                accumulating = False
                silence_t0 = None
                return

        flush_hard_splits()

    while True:
        piece = stream.read(4096)
        if not piece:
            break
        buf += piece
        while len(buf) >= METER_CHUNK_BYTES:
            chunk = buf[:METER_CHUNK_BYTES]
            buf = buf[METER_CHUNK_BYTES:]
            process_meter_chunk(chunk, time.monotonic())

    if buf:
        if len(buf) % 2:
            buf += b"\x00"
        if len(buf) < METER_CHUNK_BYTES:
            buf = buf + b"\x00" * (METER_CHUNK_BYTES - len(buf))
        while len(buf) >= METER_CHUNK_BYTES:
            chunk = buf[:METER_CHUNK_BYTES]
            buf = buf[METER_CHUNK_BYTES:]
            process_meter_chunk(chunk, time.monotonic())

    if accumulating and seg:
        while len(seg) >= max_bytes:
            flush_segment(seg[:max_bytes])
            seg = seg[max_bytes:]
        if len(seg) >= SAMPLE_RATE * 2:
            flush_segment(seg)

    logger.info(
        "Segmentation done: %d file(s) in %s (squelch=%s silence_ms=%s max_chunk_s=%s)",
        len(written),
        output_dir,
        squelch,
        silence_ms,
        max_chunk_seconds,
    )
    return written


def cmd_segment_mic(args: argparse.Namespace) -> None:
    logger.info(
        "segment-mic: device_index=%s output_dir=%s squelch=%s silence_ms=%s max_chunk_s=%s",
        args.in_audio_device_index,
        args.output_dir,
        args.squelch_threshold,
        args.silence_ms,
        args.max_chunk_seconds,
    )
    cmd = build_capture_to_stdout_command(args.in_audio_device_index)
    logger.debug("ffmpeg: %s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    try:
        segment_s16le_stream(
            proc.stdout,
            Path(args.output_dir),
            args.squelch_threshold,
            args.silence_ms,
            args.max_chunk_seconds,
            args.prefix,
        )
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def cmd_segment_file(args: argparse.Namespace) -> None:
    path = Path(args.input_audio)
    if not path.is_file():
        sys.exit(f"Not a file: {path}")
    logger.info(
        "segment-file: input=%s size=%d bytes output_dir=%s squelch=%s silence_ms=%s max_chunk_s=%s",
        path.resolve(),
        path.stat().st_size,
        args.output_dir,
        args.squelch_threshold,
        args.silence_ms,
        args.max_chunk_seconds,
    )
    cmd = build_audio_file_to_stdout_command(path)
    logger.debug("ffmpeg: %s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    try:
        segment_s16le_stream(
            proc.stdout,
            Path(args.output_dir),
            args.squelch_threshold,
            args.silence_ms,
            args.max_chunk_seconds,
            args.prefix,
        )
    finally:
        proc.wait(timeout=60)


def ollama_chat(
    base_url: str,
    model: str,
    messages: list[dict],
    options: dict | None = None,
    timeout_s: float = 600.0,
) -> dict:
    url = base_url.rstrip("/") + "/api/chat"
    body: dict = {"model": model, "messages": messages, "stream": False}
    if options:
        body["options"] = options
    t0 = time.perf_counter()
    logger.debug("POST %s model=%s messages=%d", url, model, len(messages))
    r = requests.post(url, json=body, timeout=timeout_s)
    elapsed = time.perf_counter() - t0
    logger.info("Ollama POST %s -> HTTP %s in %.2fs", url, r.status_code, elapsed)
    if not r.ok:
        logger.error("Ollama error body prefix: %r", r.text[:500])
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError:
        logger.warning("Ollama response not JSON, body prefix=%r", r.text[:200])
        raise
    eval_count = data.get("eval_count")
    if eval_count is not None:
        logger.info("Ollama eval_count=%s", eval_count)
    total_dur = data.get("total_duration")
    if total_dur is not None:
        logger.debug("Ollama total_duration=%s load_duration=%s", total_dur, data.get("load_duration"))
    return data


def ollama_http_error_detail(e: requests.HTTPError) -> tuple[int | str, str]:
    detail = ""
    if e.response is not None:
        try:
            payload = e.response.json()
            detail = str(payload.get("error") or "")[:800]
        except (ValueError, TypeError):
            detail = (e.response.text or "")[:800]
    code = e.response.status_code if e.response is not None else "?"
    return code, detail


def ollama_get_tags(base_url: str, timeout_s: float = 15.0) -> dict:
    url = base_url.rstrip("/") + "/api/tags"
    t0 = time.perf_counter()
    logger.debug("GET %s", url)
    r = requests.get(url, timeout=timeout_s)
    elapsed = time.perf_counter() - t0
    logger.info("Ollama GET %s -> HTTP %s in %.2fs", url, r.status_code, elapsed)
    if not r.ok:
        logger.error("Ollama error body prefix: %r", r.text[:500])
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        logger.warning("Ollama /api/tags response not JSON, body prefix=%r", r.text[:200])
        raise


def ollama_tags_contain_model(tags: dict, model: str) -> bool:
    for entry in tags.get("models") or []:
        name = str(entry.get("name") or "").strip()
        if name == model:
            return True
    return False


def exit_on_ollama_tags_http_error(e: requests.HTTPError) -> NoReturn:
    code, detail = ollama_http_error_detail(e)
    logger.error("Ollama GET /api/tags failed: %s", detail or str(e))
    print(
        f"Ollama GET /api/tags failed (HTTP {code}). "
        "The server is reachable but the tags request was rejected.\n"
        f"Server message: {detail or e}",
        file=sys.stderr,
    )
    sys.exit(1)


def exit_on_ollama_chat_http_error(e: requests.HTTPError, *, after_whisper: bool = True) -> NoReturn:
    code, detail = ollama_http_error_detail(e)
    logger.error("Ollama chat failed: %s", detail or str(e))
    whisper_line = ""
    if after_whisper:
        whisper_line = (
            "If this run used Whisper first, STT may have succeeded; the failure is on the Gemma/Ollama side.\n"
        )
    print(
        f"Ollama /api/chat failed (HTTP {code}).\n"
        f"{whisper_line}"
        "Ollama often reports this as resource limits *or an internal runner error* — text-only is not inherently heavier than "
        "multimodal; if one path fails and the other works, treat it as intermittent or template/runtime-specific, not proof of RAM alone.\n"
        "Try: restart Ollama, `ollama ps` / stop unused models, upgrade Ollama, try another model tag, or read `ollama logs`.\n"
        f"Server message: {detail or e}",
        file=sys.stderr,
    )
    sys.exit(1)


def wav_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def infer_ollama_multimodal(
    base_url: str,
    model: str,
    system_prompt: str,
    wav_path: Path,
    use_audios_key: bool,
) -> tuple[str, str]:
    """Returns (mode_used, message_content). mode is 'audios' or 'images'."""
    wav_bytes = wav_path.stat().st_size
    b64 = wav_to_base64(wav_path)
    logger.debug(
        "Multimodal payload: wav_file_bytes=%d base64_len=%d key=%s",
        wav_bytes,
        len(b64),
        "audios" if use_audios_key else "images",
    )
    user_msg: dict = {"role": "user", "content": USER_INSTRUCTION_AUDIO}
    key = "audios" if use_audios_key else "images"
    user_msg[key] = [b64]
    messages = [
        {"role": "system", "content": system_prompt},
        user_msg,
    ]
    data = ollama_chat(base_url, model, messages, options=OLLAMA_GEN_OPTIONS)
    msg = data.get("message") or {}
    content = (msg.get("content") or "").strip()
    logger.debug("Multimodal response key=%s chars=%d preview=%r", key, len(content), content[:300] if content else "")
    return key, content


def infer_ollama_text_only(
    base_url: str,
    model: str,
    system_prompt: str,
    transcript: str,
) -> str:
    t = transcript.strip()
    logger.info("Ollama text-only path: transcript_chars=%d system_prompt_chars=%d", len(t), len(system_prompt))
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": USER_INSTRUCTION_TEXT + t},
    ]
    try:
        data = ollama_chat(base_url, model, messages, options=OLLAMA_GEN_OPTIONS)
    except requests.HTTPError as err:
        exit_on_ollama_chat_http_error(err)
    msg = data.get("message") or {}
    out = (msg.get("content") or "").strip()
    logger.debug("Ollama text-only response_chars=%d preview=%r", len(out), out[:300] if out else "")
    return out


def transcribe_whisper_local(wav_path: Path, whisper_url: str, scenario_prompt: str) -> str:
    logger.info("Whisper POST %s file=%s (%d bytes)", whisper_url, wav_path, wav_path.stat().st_size)
    t0 = time.perf_counter()
    with wav_path.open("rb") as f:
        files = {"file": ("audio.wav", f, "audio/wav")}
        data = {
            "response_format": "json",
            "language": "zh",
            "prompt": scenario_prompt,
            "temperature": "0",
            "temperature_inc": "0.1",
            "entropy_thold": "2.0",
            "logprob_thold": "-0.5",
            "best_of": "5",
            "suppress_nst": "true",
            "vad": "true",
        }
        r = requests.post(whisper_url, files=files, data=data, timeout=600.0)
    elapsed = time.perf_counter() - t0
    logger.info("Whisper HTTP %s in %.2fs", r.status_code, elapsed)
    r.raise_for_status()
    out = r.json()
    text = (out.get("text") or "").strip()
    logger.info("Whisper transcript_chars=%d preview=%r", len(text), text[:120] if text else "")
    return text


def whisper_scenario_prompt() -> str:
    return os.environ.get(
        "ASR_SCENARIO_PROMPT",
        "本情境為119救護無線電通報，注意可能有救護車代號如路竹91車、E4車等。注意體溫回報是否合理"
        "CVA、GCS三分、GCS八分、E4V5M6、OHCA、ROSC、CPR、AED、"
        "血壓、收縮壓、舒張壓、over、SpO2、血氧、血糖、體溫、心跳、呼吸次數、"
        "意識不清、意識清楚、瞳孔、偏移、抽搐、"
        "CVA、STEMI、chest pain、胸痛、呼吸困難、"
        "到院前心肺功能停止、自發循環恢復、"
        "高等、急診、可以收嗎、可以送、"
        "救護車、分隊、91車、",
    )


def _stop_whisper_server(whisper_url: str) -> bool:
    """Kill the whisper-server process listening on the whisper_url port to free GPU memory."""
    from urllib.parse import urlparse

    parsed = urlparse(whisper_url)
    port = parsed.port or 8080
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split()
        if not pids:
            return False
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGTERM)
                logger.info("Stopped whisper-server pid=%s (port %d) to free GPU memory", pid, port)
            except (ProcessLookupError, ValueError):
                pass
        time.sleep(2)
        return True
    except Exception as e:
        logger.warning("Failed to stop whisper-server on port %d: %s", port, e)
        return False


def run_whisper_then_gemma_text(
    ollama_url: str,
    model: str,
    system_prompt: str,
    wav_path: Path,
    whisper_url: str,
    scenario_prompt: str,
    free_gpu: bool = False,
) -> str:
    logger.info("infer: pipeline Whisper STT → Gemma (text)")
    transcript = transcribe_whisper_local(wav_path, whisper_url, scenario_prompt)
    if not transcript:
        sys.exit("Whisper returned empty transcript")
    if free_gpu:
        stopped = _stop_whisper_server(whisper_url)
        if stopped:
            logger.info("infer: whisper-server stopped; GPU memory freed for Ollama")
    text = infer_ollama_text_only(ollama_url, model, system_prompt, transcript)
    logger.info("infer: Gemma text step done, response_chars=%d", len(text))
    logger.debug("infer: response preview=%r", text[:400] if text else "")
    return text


def run_ollama_multimodal_attempts(
    ollama_url: str,
    model: str,
    system_prompt: str,
    wav_path: Path,
) -> tuple[str | None, str | None]:
    """Try audios then images. Returns (content, mode_tag) or (None, None)."""
    last_err: Exception | None = None
    for use_audios in (True, False):
        key = "audios" if use_audios else "images"
        try:
            logger.info("infer: trying Ollama multimodal key=%s", key)
            mode, content = infer_ollama_multimodal(
                ollama_url,
                model,
                system_prompt,
                wav_path,
                use_audios_key=use_audios,
            )
            if content:
                logger.info("infer: success via ollama:%s response_chars=%d", mode, len(content))
                return content, mode
            logger.warning("infer: ollama:%s returned empty content, trying next path", mode)
        except requests.HTTPError as e:
            last_err = e
            body = e.response.text[:500] if e.response is not None else ""
            logger.warning("infer: ollama:%s HTTPError %s body_prefix=%r", key, e, body[:200])
        except requests.RequestException as e:
            last_err = e
            logger.warning("infer: ollama:%s RequestException %s", key, e)
    if last_err:
        logger.debug("infer: multimodal last error: %s", last_err)
    return None, None


def cmd_infer(args: argparse.Namespace) -> None:
    pf = Path(args.prompt_file)
    system_prompt = load_system_prompt(pf)
    wav_path = Path(args.wav) if args.wav else None
    whisper_fallback = not args.no_whisper_fallback
    scenario = whisper_scenario_prompt()

    whisper_first = resolve_whisper_first(args)
    ollama_audio_first = not whisper_first
    if whisper_first:
        logger.info("infer: pipeline order Whisper STT → Gemma (text)")
    else:
        logger.info("infer: pipeline order Ollama multimodal (WAV) first, optional Whisper → Gemma fallback")

    logger.info(
        "infer: ollama_url=%s model=%s prompt_file=%s (%d chars) ollama_audio_first=%s "
        "whisper_fallback=%s whisper_url=%s",
        args.ollama_url,
        args.model,
        pf.resolve(),
        len(system_prompt),
        ollama_audio_first,
        whisper_fallback,
        args.whisper_url,
    )

    if args.text_only:
        if not args.transcript and not args.transcript_file:
            sys.exit("--text-only requires --transcript or --transcript-file")
        transcript = args.transcript or Path(args.transcript_file).read_text(encoding="utf-8")
        logger.info("infer: text-only mode (skip STT)")
        text = infer_ollama_text_only(args.ollama_url, args.model, system_prompt, transcript)
        logger.info("infer: done, response_chars=%d", len(text))
        logger.debug("infer: response preview=%r", text[:400] if text else "")
        print(text)
        return

    if wav_path is None or not wav_path.is_file():
        sys.exit("Provide --wav for infer, or use --text-only")

    wav_resolved = wav_path.resolve()
    dur = wav_duration_seconds(wav_path)
    logger.info(
        "infer: wav=%s size=%d bytes duration_s=%s",
        wav_resolved,
        wav_path.stat().st_size,
        f"{dur:.2f}" if dur is not None else "unknown",
    )

    if ollama_audio_first:
        content, mode = run_ollama_multimodal_attempts(
            args.ollama_url,
            args.model,
            system_prompt,
            wav_path,
        )
        if content:
            logger.debug("infer: response preview=%r", content[:400])
            print(f"[ollama:{mode}]", file=sys.stderr)
            print(content)
            return
        if not whisper_fallback:
            sys.exit("Ollama multimodal failed or empty and --no-whisper-fallback set")
        logger.info("infer: multimodal failed; falling back to Whisper STT → Gemma text")
        text = run_whisper_then_gemma_text(
            args.ollama_url,
            args.model,
            system_prompt,
            wav_path,
            args.whisper_url,
            scenario,
            free_gpu=args.free_gpu,
        )
        print(text)
        return

    text = run_whisper_then_gemma_text(
        args.ollama_url,
        args.model,
        system_prompt,
        wav_path,
        args.whisper_url,
        scenario,
        free_gpu=args.free_gpu,
    )
    print(text)


def cmd_check_ollama(args: argparse.Namespace) -> None:
    if not shutil.which("ollama"):
        logger.error("Ollama CLI not found. Install from https://ollama.com then re-run.")
        sys.exit(1)
    logger.info("check-ollama: running `ollama --version`")
    subprocess.run(["ollama", "--version"], check=True)
    if args.pull:
        logger.info("check-ollama: pulling model %s (large download)", args.model)
        subprocess.run(["ollama", "pull", args.model], check=True)

    logger.info(
        "check-ollama: GET /api/tags ollama_url=%s",
        args.ollama_url,
    )
    try:
        tags = ollama_get_tags(args.ollama_url)
    except requests.HTTPError as e:
        exit_on_ollama_tags_http_error(e)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        logger.error("Cannot reach Ollama at %s: %s", args.ollama_url, e)
        print(
            f"Cannot reach Ollama at {args.ollama_url!r} (connection error or timeout).\n"
            "Confirm the daemon is running (e.g. `ollama serve`, or start the Ollama app / brew service) "
            "and that OLLAMA_HOST includes a scheme, e.g. http://127.0.0.1:11434.",
            file=sys.stderr,
        )
        sys.exit(1)
    n_models = len(tags.get("models") or [])
    logger.info("check-ollama: API reachable; %d model(s) in local tag list", n_models)

    if args.no_chat and getattr(args, "pipeline", False):
        sys.exit("check-ollama: --no-chat cannot be used with --pipeline")

    if args.no_chat:
        if not ollama_tags_contain_model(tags, args.model):
            logger.error("Model %r not listed in /api/tags; run `ollama pull %s`", args.model, args.model)
            print(
                f"Model {args.model!r} is not in the local Ollama library (GET /api/tags).\n"
                f"Run: ollama pull {args.model}",
                file=sys.stderr,
            )
            sys.exit(1)
        logger.info("check-ollama: OK (--no-chat) model %s present", args.model)
        print(f"check-ollama: server OK, model {args.model!r} present (--no-chat, chat skipped)")
        return

    if getattr(args, "pipeline", False):
        wav_path = Path(args.wav) if args.wav else None
        if wav_path is None or not wav_path.is_file():
            sys.exit("check-ollama --pipeline requires --wav pointing to an existing WAV file")
        system_prompt = load_system_prompt(Path(args.prompt_file))
        logger.info(
            "check-ollama: pipeline test whisper_url=%s ollama model=%s wav=%s",
            args.whisper_url,
            args.model,
            wav_path.resolve(),
        )
        scenario = whisper_scenario_prompt()
        try:
            transcript = transcribe_whisper_local(wav_path, args.whisper_url, scenario)
        except requests.RequestException as e:
            logger.error("check-ollama: Whisper request failed: %s", e)
            print(
                f"Whisper STT failed ({type(e).__name__}): {e}\n"
                f"Start the Whisper HTTP server (e.g. bun run whisper:start); endpoint: {args.whisper_url}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not transcript:
            sys.exit("Whisper returned empty transcript")
        text = infer_ollama_text_only(args.ollama_url, args.model, system_prompt, transcript)
        logger.info("check-ollama: OK pipeline response_chars=%d", len(text))
        print(text)
        return

    chat_model = args.chat_model or os.environ.get("OLLAMA_CHAT_CHECK_MODEL") or args.model
    system_prompt = load_system_prompt(Path(args.prompt_file))
    logger.info(
        "check-ollama: chat smoke test ollama_url=%s chat_model=%s (infer model / --model=%s)",
        args.ollama_url,
        chat_model,
        args.model,
    )
    messages = [
        {"role": "system", "content": system_prompt[:2000]},
        {
            "role": "user",
            "content": 'Reply with exactly: {"raw_transcript":"ok","polished":"ok","reasoning":"test","summary":"ok"}',
        },
    ]
    try:
        data = ollama_chat(
            args.ollama_url,
            chat_model,
            messages,
            options=OLLAMA_GEN_OPTIONS,
            timeout_s=120.0,
        )
    except requests.HTTPError as e:
        exit_on_ollama_chat_http_error(e, after_whisper=False)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        logger.error("Chat request to Ollama failed: %s", e)
        print(
            f"Ollama /api/chat request failed ({type(e).__name__}): {e}\n"
            "The earlier GET /api/tags succeeded; the server may have stopped or the connection dropped during chat.",
            file=sys.stderr,
        )
        sys.exit(1)
    msg = data.get("message") or {}
    content = (msg.get("content") or "").strip()
    logger.info("check-ollama: OK response_chars=%d", len(content))
    logger.debug("check-ollama: preview=%r", content[:300])
    print(content)


def cmd_process_dir(args: argparse.Namespace) -> None:
    d = Path(args.input_dir)
    if not d.is_dir():
        sys.exit(f"Not a directory: {d}")
    wavs = sorted(d.glob("*.wav"))
    if not wavs:
        sys.exit(f"No .wav files in {d}")
    logger.info("process-dir: %d wav(s) in %s", len(wavs), d.resolve())
    for i, w in enumerate(wavs, start=1):
        logger.info("process-dir: [%d/%d] %s", i, len(wavs), w.name)
        ns = argparse.Namespace(
            ollama_url=args.ollama_url,
            model=args.model,
            prompt_file=args.prompt_file,
            wav=str(w),
            text_only=False,
            transcript=None,
            transcript_file=None,
            whisper_first=getattr(args, "whisper_first", False),
            ollama_audio_first=getattr(args, "ollama_audio_first", False),
            skip_ollama_audio=getattr(args, "skip_ollama_audio", False),
            no_whisper_fallback=args.no_whisper_fallback,
            whisper_url=args.whisper_url,
            free_gpu=getattr(args, "free_gpu", False),
        )
        cmd_infer(ns)


def main() -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true", help="DEBUG logging on stderr")
    common.add_argument("--ollama-url", default=DEFAULT_OLLAMA)
    common.add_argument("--model", default=DEFAULT_MODEL)
    common.add_argument("--prompt-file", default=str(DEFAULT_PROMPT_PATH))

    p = argparse.ArgumentParser(description="Gemma 4 E4B radio pipeline (Ollama + segments + infer)")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser(
        "check-ollama",
        parents=[common],
        help="Verify ollama CLI, GET /api/tags, optional pull, JSON smoke chat",
    )
    c.add_argument("--pull", action="store_true", help="Run ollama pull (downloads model)")
    c.add_argument(
        "--no-chat",
        action="store_true",
        help="Only verify CLI + /api/tags + that --model appears in local tags (skip /api/chat)",
    )
    c.add_argument(
        "--chat-model",
        default=None,
        metavar="NAME",
        help="Model for JSON smoke only (default: OLLAMA_CHAT_CHECK_MODEL env or --model)",
    )
    c.add_argument(
        "--pipeline",
        action="store_true",
        help="Whisper STT on --wav then Gemma text (end-to-end); requires Whisper HTTP server",
    )
    c.add_argument("--wav", default=None, help="WAV path (required with --pipeline)")
    c.add_argument("--whisper-url", default=DEFAULT_WHISPER_URL)
    c.set_defaults(func=cmd_check_ollama)

    s1 = sub.add_parser(
        "segment-mic",
        parents=[common],
        help="macOS AVFoundation capture → preprocessed VAD WAV segments (Ctrl+C to stop)",
    )
    s1.add_argument("--in-audio-device-index", type=int, required=True)
    s1.add_argument("--output-dir", required=True)
    s1.add_argument("--squelch-threshold", type=float, default=0.1)
    s1.add_argument("--silence-ms", type=int, default=1200)
    s1.add_argument("--max-chunk-seconds", type=float, default=30.0)
    s1.add_argument("--prefix", default="seg")
    s1.set_defaults(func=cmd_segment_mic)

    s2 = sub.add_parser("segment-file", parents=[common], help="Decode file with same preprocess chain → WAV segments")
    s2.add_argument("--input-audio", required=True)
    s2.add_argument("--output-dir", required=True)
    s2.add_argument("--squelch-threshold", type=float, default=0.1)
    s2.add_argument("--silence-ms", type=int, default=1200)
    s2.add_argument("--max-chunk-seconds", type=float, default=30.0)
    s2.add_argument("--prefix", default="seg")
    s2.set_defaults(func=cmd_segment_file)

    i = sub.add_parser(
        "infer",
        parents=[common],
        help="Default: Whisper STT → Gemma text; or --ollama-audio-first for Ollama WAV first",
    )
    i.add_argument("--wav", default=None)
    i.add_argument("--text-only", action="store_true")
    i.add_argument("--transcript", default=None)
    i.add_argument("--transcript-file", default=None)
    i.add_argument(
        "--whisper-first",
        action="store_true",
        help="Whisper STT → Gemma only (same as default; explicit)",
    )
    i.add_argument(
        "--ollama-audio-first",
        action="store_true",
        help="Try Ollama multimodal (WAV) before Whisper; optional Whisper→Gemma fallback unless --no-whisper-fallback",
    )
    i.add_argument(
        "--skip-ollama-audio",
        action="store_true",
        help="Same as --whisper-first (skip Ollama multimodal)",
    )
    i.add_argument(
        "--no-whisper-fallback",
        action="store_true",
        help="With --ollama-audio-first: if Ollama multimodal fails, exit without Whisper",
    )
    i.add_argument("--whisper-url", default=DEFAULT_WHISPER_URL)
    i.add_argument(
        "--free-gpu",
        action="store_true",
        help="Stop whisper-server after STT to free GPU memory for Ollama (useful on low-VRAM machines)",
    )
    i.set_defaults(func=cmd_infer)

    pd = sub.add_parser("process-dir", parents=[common], help="Run infer on every *.wav in a directory")
    pd.add_argument("--input-dir", required=True)
    pd.add_argument("--whisper-first", action="store_true")
    pd.add_argument(
        "--ollama-audio-first",
        action="store_true",
        help="Try Ollama multimodal (WAV) before Whisper (same as infer)",
    )
    pd.add_argument("--skip-ollama-audio", action="store_true")
    pd.add_argument("--no-whisper-fallback", action="store_true")
    pd.add_argument("--whisper-url", default=DEFAULT_WHISPER_URL)
    pd.add_argument("--free-gpu", action="store_true", help="Stop whisper-server after STT to free GPU memory")
    pd.set_defaults(func=cmd_process_dir)

    args = p.parse_args()
    configure_logging(args.verbose)
    logger.debug("argv=%s", sys.argv)
    args.func(args)


if __name__ == "__main__":
    main()
