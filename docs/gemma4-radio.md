# Gemma 4 E4B radio pipeline (Ollama)

End-to-end flow aligned with radio-monitor preprocessing (16 kHz mono, same FFmpeg filters as `src/lib/ffmpeg.ts`): optional live capture or file input → VAD segments capped at **30 s** (Gemma 4 audio limit per [model card](https://huggingface.co/google/gemma-4-E4B)) → inference.

## Inference paths

| Mode | Behavior |
|------|----------|
| **Default** | **Whisper STT → Gemma text** (structured JSON; best for noisy radio + ASR cleanup). Requires Whisper HTTP (`WHISPER_API_URL`). |
| **`--ollama-audio-first`** | Try **Ollama multimodal** (WAV via `audios` / `images`+base64) first; on failure or empty, **Whisper → Gemma** unless **`--no-whisper-fallback`**. |
| **`--whisper-first`** | Same as default (explicit). |
| **`--skip-ollama-audio`** | Same as **`--whisper-first`**. |
| **`--text-only`** | No WAV/STT; you supply the transcript. |

## 1. Install Ollama and pull the model

Install from [ollama.com](https://ollama.com). Then:

```bash
ollama pull gemma4:e4b-it-q4_K_M
```

Optional: `OLLAMA_GEMMA_MODEL` selects another tag (e.g. `gemma4:e4b-it-bf16`).

## 2. Python dependencies

From `packages/radio-monitor`:

```bash
pip install -r scripts/gemma4-requirements.txt
```

## 3. Verify Ollama + system prompt

```bash
python scripts/gemma4_pipeline.py check-ollama
```

The command runs `ollama --version`, then **`GET /api/tags`**, then a small **`POST /api/chat`** JSON smoke test.

- **`--model`**: model used for **`infer`** / **`--pipeline`** (your production Gemma tag).
- **`--chat-model`**: optional model used **only** for the JSON smoke step (default: env **`OLLAMA_CHAT_CHECK_MODEL`**, else same as `--model`). Use a small tag (e.g. `llama3.2:1b`) if your main Gemma image crashes the runner but you still want `check-ollama` to prove the HTTP API works.

Add **`--pull`** to download **`--model`**.

**`--no-chat`** skips `/api/chat` and only checks the CLI, **`GET /api/tags`**, and that **`--model`** appears in the local tag list.

**End-to-end (recommended for the Whisper → Gemma workflow):** with Whisper running, use **`--pipeline`** and a sample segment:

```bash
bun run whisper:start   # separate terminal if needed
python scripts/gemma4_pipeline.py check-ollama --pipeline --wav ./segments/seg_00001.wav
```

This runs Whisper STT on the WAV, then Gemma text with **`--model`**, matching the default **`infer`** path.

## 4. Build WAV segments

**From a file** (any format `ffmpeg` can decode):

```bash
python scripts/gemma4_pipeline.py segment-file \
  --input-audio ./recording.wav \
  --output-dir ./segments
```

**From macOS microphone** (same device index as `whispr.py list-devices`):

```bash
python scripts/gemma4_pipeline.py segment-mic \
  --in-audio-device-index 0 \
  --output-dir ./segments
```

Stop `segment-mic` with Ctrl+C. Tunables: `--squelch-threshold`, `--silence-ms`, `--max-chunk-seconds` (default 30).

## 5. Inference

### Default (Whisper → Gemma)

```bash
bun run whisper:start   # when needed
python scripts/gemma4_pipeline.py infer --wav ./segments/seg_00001.wav
```

### Ollama WAV first (optional)

```bash
python scripts/gemma4_pipeline.py infer --wav ./segments/seg_00001.wav --ollama-audio-first
```

**No Whisper fallback** when using Ollama WAV first:

```bash
python scripts/gemma4_pipeline.py infer --wav ./segments/seg_00001.wav --ollama-audio-first --no-whisper-fallback
```

Add `-v` / `--verbose` on any subcommand for DEBUG logs.

**Text-only** (no WAV):

```bash
python scripts/gemma4_pipeline.py infer --text-only --transcript "91 回報 OHCA 現場已 CPR"
```

**Batch**:

```bash
python scripts/gemma4_pipeline.py process-dir --input-dir ./segments
```

`process-dir` accepts **`--ollama-audio-first`**, **`--whisper-first`**, **`--skip-ollama-audio`**, **`--no-whisper-fallback`** the same as `infer`.

## 6. Prompt and output schema

Edit [`scripts/prompts/gemma_radio_system.txt`](../scripts/prompts/gemma_radio_system.txt) for abbreviations and JSON keys. With **Whisper in the loop**, **`raw_transcript`** tracks the ASR line; **`polished`** and **`reasoning`** carry corrections and notes on garbled or ambiguous keywords.

Override path: `--prompt-file /path/to/custom.txt`.

## Environment

| Variable | Purpose |
|----------|---------|
| `OLLAMA_HOST` | Base URL (default `http://127.0.0.1:11434`) |
| `OLLAMA_GEMMA_MODEL` | Model tag for **`infer`** / **`--pipeline`** (default `gemma4:e4b-it-q4_K_M`) |
| `OLLAMA_CHAT_CHECK_MODEL` | Optional model for **`check-ollama`** JSON smoke only (when `--chat-model` not passed) |
| `WHISPER_API_URL` | Whisper HTTP endpoint (default `http://127.0.0.1:8080/inference`) |
| `ASR_SCENARIO_PROMPT` | Domain hint sent to Whisper during STT (optional) |

## Troubleshooting

### `check-ollama` fails but you want to isolate the failure

| Symptom | Likely meaning |
|--------|----------------|
| Error right after **`GET /api/tags`** (connection / timeout) | Ollama is not listening on `OLLAMA_HOST`, or the URL is wrong (include `http://`; bare `host:port` can break clients). |
| **`GET /api/tags` OK**, **`/api/chat` HTTP 500** with *runner stopped* | **Smoke model** failed to run. Try **`--chat-model llama3.2:1b`** (after `ollama pull`) or set **`OLLAMA_CHAT_CHECK_MODEL`**, while keeping **`--model`** for real inference. Or use **`--no-chat`** for connectivity-only. |
| Smoke OK, **`--pipeline`** fails at Gemma | Whisper succeeded; **`--model`** runner still crashes — same mitigations as `infer` (other tag, restart Ollama, logs). |
| **`--pipeline`** fails before Gemma | Start Whisper HTTP (**`bun run whisper:start`**) and check **`WHISPER_API_URL`**. |

### `model runner has unexpectedly stopped` (Ollama HTTP 500)

Whisper (if used) may have finished, but Ollama’s Gemma **runner** exited. The API message cites **resource limits *or* internal errors** — it is **not** always “out of RAM,” and **text-only chat is not automatically heavier than sending WAV** (multimodal usually touches the audio encoder too). If one path works and the other fails, note **different Ollama code paths** (template/renderer) or **intermittent** crashes.

- Reproduce outside this repo: `ollama run <same-model-tag>` with a one-line prompt.
- Run `ollama ps` and stop models you do not need (`ollama stop <name>`).
- Restart Ollama and retry; upgrade Ollama if you are on an older build.
- Try another tag, e.g. `OLLAMA_GEMMA_MODEL=gemma4:e2b-it-q4_K_M` or pass `--model` to `check-ollama` / `infer`.
- **Server logs:** on macOS the path is not always `~/.ollama/logs/server.log`. Prefer running `ollama serve` in the foreground in a terminal, use **Console.app** filtered for Ollama, or follow [Ollama troubleshooting](https://docs.ollama.com/troubleshooting) for your OS to find the real reason (Metal OOM, assert, etc.).

### Ollama `/api/chat` shape (this repo)

**Multimodal (WAV),** with **`--ollama-audio-first`**: `system` = `gemma_radio_system.txt`; `user` has string `content` plus **`audios`** or **`images`** = list of one base64 WAV (see `infer_ollama_multimodal` in `scripts/gemma4_pipeline.py`).

**Default (Whisper → Gemma):** same `system`; `user.content` = `USER_INSTRUCTION_TEXT` + transcript. No WAV fields.
