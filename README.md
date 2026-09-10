# @forwardalliance/radio-monitor

## Architecture

完整的 pipeline 架構（前處理 → VAD → STT → 摘要 → 前端）請見 [docs/pipeline-architecture.md](docs/pipeline-architecture.md)。

## Prerequisites

- [Bun](https://bun.sh/)
- [ffmpeg](https://ffmpeg.org/) (e.g. `brew install ffmpeg` on macOS) — used for capturing and preprocessing audio
- [cmake](https://cmake.org/) (e.g. `brew install cmake` on macOS) — only needed to build Whisper.cpp

## Quick start

```bash
cd packages/radio-monitor
bun install

# Start the app (frontend + API at http://localhost:3000)
bun run app:dev
```

With live transcription (Whisper), run in two terminals or use `dev`:

```bash
# Terminal 1: Whisper server (port 8080)
bun run whisper:start

# Terminal 2: App (frontend at http://localhost:3000)
bun run app:dev
```

Or run both together:

```bash
bun run dev   # app:dev + whisper:start in parallel
```

## ASR providers

The app can use different speech-to-text backends. Set `ASR_PROVIDER` and the corresponding URL.

| Provider   | Env                      | Description                    |
| ---------- | ------------------------ | ------------------------------ |
| `whisper`  | (default)                | Local whisper-server (port 8080) |
| `voxtral`  | `VOXTRAL_API_URL`        | [Voxtral Mini 4B Realtime](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602); requires a separate HTTP service (see [docs/voxtral.md](docs/voxtral.md)) |
| `firered`  | `FIRERED_ASR_API_URL`    | [FireRedASR](https://huggingface.co/collections/FireRedTeam/fireredasr) (Mandarin-focused); requires a separate HTTP service (see [docs/firered.md](docs/firered.md)) |

**Gemma 4 E4B (Ollama)** — segment then default **Whisper STT → Gemma text**; optional **`--ollama-audio-first`** for Ollama WAV before Whisper: see [docs/gemma4-radio.md](docs/gemma4-radio.md).

Optional prompt tuning:

- `ASR_SCENARIO_PROMPT` — Short scenario/domain description prepended to context (e.g. 救護無線電常見用詞).
- `ASR_CONTEXT_LIMIT` — Number of recent transcripts to use as context (default `5`).

Example:

```bash
ASR_PROVIDER=whisper ASR_SCENARIO_PROMPT="本情境為救護無線電勤務。常見用詞：OHCA、GCS、勤務中心。" bun run app:dev
```

## Simulated audio input (mock radio)

用音檔模擬即時無線電輸入，ffmpeg 會以 `-re` 旗標按原始時間軸播放：

```bash
AUDIO_FILE=./docs/test.mp3 bun run app:dev
```

搭配 ASR provider 與 context prompt：

```bash
AUDIO_FILE=./recording.wav ASR_PROVIDER=whisper ASR_SCENARIO_PROMPT="救護無線電" bun run app:dev
```

## Microphone & troubleshooting

**預設**：不設 `AUDIO_FILE` 時會用系統預設麥克風（`MICROPHONE_ID=0`）。

### 1. 列出麥克風裝置（macOS）

```bash
ffmpeg -f avfoundation -list_devices true -i ""
```

注意：`-i` 後面要加一對空引號 `""`，才會只列出裝置而不真的開始錄影/錄音。

輸出裡 `[AVFoundation input device]` 會列出音訊裝置，前面的數字就是裝置 ID。例如：

```
[AVFoundation input device] [0] MacBook Pro Microphone
[AVFoundation input device] [1] External USB Audio
```

要用某個麥克風就設成對應數字：

```bash
MICROPHONE_ID=0 bun run app:dev
```

### 2. 確認有收到聲音

執行 app 時，對著麥克風講話，看 **跑 app 的那個 terminal** 有沒有出現：

- `Rx Start... (Signal Detected)` — 有偵測到聲音，開始錄這段
- `Rx End. Processing...` — 靜音約 1.2 秒，這段送轉錄

若從來沒有 `Rx Start...`，可能是：

- 麥克風選錯（改 `MICROPHONE_ID`）
- 音量太小，未超過門檻（門檻在 `src/contstants.ts` 的 `SQUELCH_THRESHOLD`，預設 `0.1`）

### 3. 開 debug 看 ffmpeg

```bash
LOG_LEVEL=DEBUG bun run app:dev
```

會印出 ffmpeg 的 stderr，可確認是否有抓錯裝置或錄音錯誤。

## Setup Whisper.cpp

Whisper large-v3 performs the best when transcribing radio recordings.

**Prerequisites:** [cmake](https://cmake.org/) (e.g. `brew install cmake` on macOS).

```bash
# From the monorepo root: clone the whisper.cpp submodule
git submodule update --init --recursive

# From packages/radio-monitor: build whisper.cpp, download the large-v3 model + Silero VAD model
bun run whisper:prepare

# Start the whisper server
bun run whisper:start
```

Or run each step individually:

```bash
bun run whisper:build          # Build whisper.cpp from source
bun run whisper:download-model # Download ggml-large-v3 model
bun run whisper:download-vad   # Download Silero VAD model
```

For macOS with Metal GPU support, build manually instead:

```bash
cd providers/whisper.cpp
WHISPER_METAL=1 make -j
```

## Fine-tuning (optional)

To improve recognition on your domain, you can fine-tune a model using corrected transcripts.

### 1. Export data

Export (audio, corrected text) pairs for rows that have user corrections:

```bash
bun run export-for-finetune
```

This writes `data/finetune/manifest.jsonl`: one JSON object per line, each with `audio_path` (absolute path to WAV) and `text` (corrected transcript).

### 2. Train

Use the manifest with the model of choice (run outside this repo):

- **Whisper**: Fine-tune with [Hugging Face Transformers](https://huggingface.co/docs/transformers/training) or community scripts (e.g. [openai/whisper](https://github.com/openai/whisper) fine-tuning guides). Load the manifest and train seq2seq (or adapters) to produce a new checkpoint.
- **FireRedASR**: See [FireRedTeam/FireRedASR](https://github.com/FireRedTeam/FireRedASR) and model cards on Hugging Face for fine-tune instructions; use (audio_path, text) pairs from the manifest.
- **Voxtral**: Check Mistral/vLLM docs for fine-tune support; document when available.

### 3. Deploy

Point your Whisper/Voxtral/FireRed service at the new checkpoint (or a new endpoint). Update `WHISPER_API_URL` / `VOXTRAL_API_URL` / `FIRERED_ASR_API_URL` in radio-monitor as needed; no code change required.
