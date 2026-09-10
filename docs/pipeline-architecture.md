# Pipeline Architecture
哈囉 哈囉 123 車上一名 65 歲患者 胸口悶痛 患者意識清楚呼吸每分鐘 22 次 血壓 14590 血氧 94。
radio-monitor 的完整音訊處理 pipeline，從音訊來源到前端顯示。

## 系統總覽

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Bun Server (TypeScript)                         │
│                                                                        │
│  音訊來源          前處理             VAD             STT              │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────┐     │
│  │ 麥克風   │───▶│ ffmpeg   │───▶│ RMS 門檻 │───▶│ Whisper /    │     │
│  │ or       │    │ 濾波鏈   │    │ 靜音偵測 │    │ Voxtral /    │     │
│  │ 音檔模擬 │    │          │    │          │    │ FireRed      │     │
│  └──────────┘    └──────────┘    └──────────┘    └──────┬───────┘     │
│                                                         │              │
│                                  ┌──────────┐    ┌──────▼───────┐     │
│                                  │ SSE 推送 │◀───│ SQLite 儲存  │     │
│                                  └────┬─────┘    └──────────────┘     │
│                                       │                                │
└───────────────────────────────────────┼────────────────────────────────┘
                                        │
                                  ┌─────▼─────┐
                                  │ React 前端│
                                  │ 即時顯示   │
                                  └───────────┘


┌─────────────────────────────────────────────────────────────────────────┐
│                  Python CLI (gemma4_pipeline.py) — 獨立運作              │
│                                                                        │
│  音訊來源         VAD 分段          Whisper STT       Ollama Gemma      │
│  ┌──────────┐   ┌──────────┐    ┌──────────┐    ┌───────────────┐     │
│  │ 麥克風   │──▶│ RMS 門檻 │───▶│ HTTP API │───▶│ 結構化 JSON   │     │
│  │ or 音檔  │   │ ≤30s 分段│    │          │    │ (摘要+校正)   │     │
│  └──────────┘   └──────────┘    └──────────┘    └───────────────┘     │
│                                                                        │
└─────────────────────────────────────────────────────────────────────────┘
```

## 階段一：音訊來源

### 麥克風即時擷取（預設）

使用 macOS AVFoundation 從系統麥克風擷取。`MICROPHONE_ID` 預設為 `0`。

```
ffmpeg -f avfoundation -i :0 ...
```

### 音檔模擬即時輸入

設定 `AUDIO_FILE` 環境變數，ffmpeg 以 `-re` (real-time) 旗標播放，模擬即時串流：

```bash
AUDIO_FILE=./docs/test.mp3 bun run app:dev
```

`-re` 讓 ffmpeg 按照音檔原始時間軸播放，不會一次把整個檔案灌進去。

程式碼位置：`src/lib/ffmpeg.ts:6-13`

## 階段二：前處理（ffmpeg 濾波鏈）

無線電音訊在送入 STT 前先經過四道濾波，全部在 ffmpeg 的 `-af` 參數內完成：

| 濾波器 | 參數 | 用途 |
|--------|------|------|
| highpass | `f=300` | 去除 300Hz 以下的背景嗡嗡聲 |
| equalizer | `f=630, w=15, g=-80` | 消除 630Hz 結束傳輸音（窄帶 notch） |
| equalizer | `f=950, w=15, g=-80` | 消除 950Hz 結束傳輸音（窄帶 notch） |
| dynaudnorm | `p=0.95, m=100, s=5` | 動態正規化（目標峰值 95%，最大增益 100x，5-frame 平滑）|

輸出格式統一為：**16kHz、單聲道（mono）、16-bit PCM (s16le)**，對齊 Whisper 的 `WHISPER_SAMPLE_RATE`。

程式碼位置：
- TypeScript: `src/lib/ffmpeg.ts:14-19`
- Python: `scripts/radio_audio_core.py:13-20`（同一套參數）

## 階段三：VAD（語音活動偵測）

不使用專門的 VAD 模型，而是基於 RMS（均方根）值的簡單門檻偵測：

### 演算法

1. 從 ffmpeg stdout 不斷讀取 PCM，累積到固定 `METER_CHUNK_BYTES`（3200 bytes = 100ms）再處理
2. 計算每個 meter chunk 的 RMS 值（將 int16 正規化到 -1~1 後取均方根）
3. 非錄音狀態下，持續維護 `PRE_ROLL_CHUNKS` 個 chunk 的 circular buffer
4. RMS > `SQUELCH_THRESHOLD`(0.1) → 開始錄音（`Rx Start...`），將 pre-roll buffer 接到 audioBuffer 前面
5. RMS < 門檻 → 開始計時靜音
6. 靜音超過 `SILENCE_DURATION`(1200ms) → 結束此段錄音（`Rx End.`）

### 可調參數

| 參數 | 預設值 | 用途 |
|------|--------|------|
| `SQUELCH_THRESHOLD` | `0.1` | RMS 門檻 |
| `SILENCE_DURATION` | `1200` ms | 靜音多久結束錄音 |
| `SAMPLE_RATE` | `16000` Hz | 取樣率 |
| `METER_CHUNK_BYTES` | `3200` | 固定 chunk 大小（100ms） |
| `PRE_ROLL_CHUNKS` | `5` | Pre-roll buffer 長度（500ms） |

程式碼位置：
- TypeScript: `src/transcribe.ts`、`src/contstants.ts`
- Python: `scripts/gemma4_pipeline.py:147-173`（同邏輯，額外支援 max 30s 硬切）

詳見 `docs/asr-optimization.md` 的根因分析和待優化項目。

## 階段四：STT（語音轉文字）

VAD 結束一段後，PCM buffer 加上 WAV header 組成完整的 WAV 檔，送到 ASR provider：

### Provider 架構

```
AsrProvider interface
  ├── WhisperProvider  → POST /inference (whisper.cpp HTTP server, port 8080)
  ├── VoxtralProvider  → POST /transcribe (Voxtral Mini 4B, port 8000)
  └── FireRedProvider  → POST /transcribe (FireRedASR, port 8001)
```

每個 provider 都接收 `{ id, wavBuffer, context }` 並回傳文字。

### Whisper 推論參數

| 參數 | 值 | 用途 |
|------|-----|------|
| `language` | `zh` | 強制中文 |
| `temperature` | `0` | 低溫確定性輸出 |
| `best_of` | `5` | 多次取樣選最佳 |
| `vad` | `true` | Whisper 內建 VAD 二次過濾 |
| `suppress_nst` | `true` | 抑制無語音 token |
| `prompt` | (context) | 注入近期轉錄作為提示 |

### Context 機制

每次轉錄前，server 會組合：
1. `ASR_SCENARIO_PROMPT`（領域提示，如「救護無線電常見用詞」）
2. 最近 N 筆（`ASR_CONTEXT_LIMIT`，預設 5）已轉錄/已校正的文字

作為 Whisper 的 `prompt` 參數，幫助模型適應當前對話脈絡。

程式碼位置：`src/index.ts:146-158`

## 階段五：儲存與即時推送

1. 轉錄結果存入 **SQLite**（透過 Drizzle ORM）
2. 同時透過 **SSE (Server-Sent Events)** 推送到所有已連線的前端
3. WAV 音檔存到 `data/audios/{id}.wav`，前端可回放

程式碼位置：`src/index.ts:86-105`（SSE），`src/index.ts:160-166`（存儲+推送）

## 階段六：前端顯示

React 前端三欄布局：

| 面板 | 狀態 | 說明 |
|------|------|------|
| 轉錄紀錄 | ✅ 已實作 | SSE 即時顯示轉錄，支援回放音訊、手動校正 |
| AI 摘要 | ❌ 空 stub | 目前只有標題，無摘要邏輯 |
| AI 聊天 | ❌ 空 stub | 目前只有標題，無聊天邏輯 |

## Gemma 4 Pipeline（獨立 Python CLI）

`scripts/gemma4_pipeline.py` 是一個**獨立運作**的 CLI 工具，未整合進 Bun server。

### 流程

```
segment-mic / segment-file
  → ffmpeg 前處理（同 Bun server 的濾波鏈）
  → RMS VAD 分段（每段 ≤30s）
  → 輸出 .wav 檔案

infer
  → Whisper STT（HTTP POST 到 whisper-server）
  → Ollama Gemma 4 E4B 文字推論
  → 輸出結構化 JSON:
    {
      "raw_transcript": "ASR 原始輸出",
      "polished": "校正後的正式文字",
      "reasoning": "消歧義筆記",
      "summary": "一兩句摘要"
    }
```

### 關鍵差異

| 項目 | Bun Server | Gemma 4 CLI |
|------|-----------|-------------|
| 語言 | TypeScript | Python |
| VAD | 無上限 | 每段上限 30s |
| STT | 直接呼叫 | 相同 Whisper HTTP |
| 摘要 | ❌ 無 | Ollama Gemma → JSON |
| 即時性 | 串流即時 | 批次 / 手動 |
| 前端 | 有 | 無 |

---

## 硬體需求參考

### M1 Pro 16GB RAM 限制

| 元件 | 記憶體用量 | 備註 |
|------|-----------|------|
| whisper.cpp large-v3 | ~3-4 GB | Metal 加速，推論 ~3-5x 即時速度 |
| whisper.cpp medium | ~1.5 GB | 中文品質稍降但仍可用 |
| Ollama Gemma 4 E4B q4_K_M | ~4-5 GB | 量化後可在 16GB 機器運行 |
| Ollama qwen2.5:7b q4_K_M | ~4-5 GB | 預設 summarization model |
| Bun server + ffmpeg + SQLite | ~200 MB | 負擔很低 |

**同時跑 Whisper large-v3 + Ollama 7B 會逼近 16GB 上限**。建議：
- 使用 `--free-gpu` 旗標，在 STT 完成後關閉 Whisper 釋放記憶體再跑摘要
- 或改用 Whisper medium / distil-large-v3 降低記憶體
- 或將摘要改用更小的模型（如 qwen2.5:3b）
