# ASR 前處理與推論優化筆記

本文件記錄 radio-monitor ASR pipeline 的已知品質問題、根因分析、已完成修復和待優化項目。

## 觀察到的問題

使用 Whisper large-v3 對 EMS 無線電錄音進行轉錄，出現嚴重的漏字和幻覺：

| | 內容 |
|---|------|
| **原文** | 哈囉 哈囉 123 車上一名 65 歲患者 **胸口悶痛** 患者**意識清楚**呼吸每分鐘 22 次 血壓 **145/90** **血氧 94** |
| **ASR 輸出** | 65歲患者 **必須**呼吸每分鐘22次 血壓14590 |

具體問題：

1. 開頭「哈囉 哈囉 123 車上一名」完全消失
2. 「胸口悶痛」消失
3. 「患者意識清楚」→ 幻覺成「必須」
4. 「血壓 145/90」→「血壓14590」（斜線消失）
5. 結尾「血氧 94」消失

根因並非模型能力不足（large-v3 是 Whisper 系列精度最高的模型），而是前處理 pipeline 送進模型的音訊品質有問題。

---

## 根因一：Pre-roll 截斷（開頭漏字）

### 問題

原本的 VAD 邏輯在 `transcribe.ts` 中：

```
ffmpeg stdout → reader.read()（不定大小）→ calculateRMS → 超過 squelch → 開始錄音
```

**只有在 RMS 超過 squelch threshold 之後才開始存 audio chunk**。在此之前的所有音訊都被丟棄。

無線電通訊的起始有一個 ramp-up 過程：
1. 對講機按下 PTT（Push To Talk）
2. 載波建立，但初始幾百毫秒音量較低
3. 加上 `dynaudnorm` 的 gain ramp-up 延遲（見根因二），RMS 要經過一段時間才會超過 squelch

這意味著通話開頭的 200ms~1s 可能被截掉，對應到「哈囉 哈囉 123 車上一名」這類開場語。

### 修復（已完成）

加入 **pre-roll circular buffer**：

```
┌──────────────────────────────────────────────────────────────┐
│ 修復前                                                        │
│                                                              │
│  [丟棄][丟棄][丟棄]|squelch|[錄音開始 ──────── 錄音結束]     │
│                     ↑ 開頭被截                                │
│                                                              │
│ 修復後                                                        │
│                                                              │
│  [pre-roll buffer ──]|squelch|[繼續錄音 ────── 錄音結束]     │
│  ↑ 500ms 保留         ↑ buffer 接到錄音前面                   │
└──────────────────────────────────────────────────────────────┘
```

在非錄音狀態下，持續保留最近 `PRE_ROLL_CHUNKS`（預設 5）個 meter chunk（每個 100ms，共 500ms）。squelch 觸發時，把 pre-roll 整段接到 audioBuffer 前面。

相關程式碼：`src/transcribe.ts`、`src/contstants.ts`

### 調校建議

如果 500ms 仍不夠（dynaudnorm gain ramp-up 在極端情況可能需要 ~1s），可將 `PRE_ROLL_CHUNKS` 調到 10（1 秒）。代價是每段音訊前面多了 1 秒可能是純噪音的部分，但對 Whisper 影響不大。

---

## 根因二：dynaudnorm 過度放大噪音（幻覺）

### 問題

ffmpeg 濾波鏈中的動態正規化：

```
dynaudnorm=p=0.95:m=100:s=5
```

參數解析：
- `p=0.95`：目標峰值為 95% full scale
- **`m=100`：最大增益 100 倍（+40dB）**
- `s=5`：smoothing window 5 frames（frame_len 預設 500ms，所以 ≈2.5 秒平滑窗口）

#### 增益行為圖解

```
音量 ↑
     │
 95% │ ·········──────────────────────  ← dynaudnorm 目標
     │        /
     │       / ← gain 快速拉升
     │      /
     │·····/   ← 靜音段噪音被放大 100x
     │    /
  0% │───/
     └────────────────────────────────→ 時間
      靜音    語音開始    語音持續
```

在靜音段（通話間隙、句間停頓），dynaudnorm 會把背景噪音放大最多 100 倍（40dB）。這些被放大的噪音送到 Whisper 後：

1. Whisper 試圖從噪音中解讀出文字 → **產生幻覺 token**（如「必須」）
2. 高增益噪音可能讓 RMS 虛高，干擾 squelch 判斷

#### 對比：語音段 vs 靜音段

| 狀態 | 原始 RMS | dynaudnorm 後 RMS | Whisper 看到的 |
|------|---------|-------------------|---------------|
| 語音 | 0.3 | ~0.9（正常放大） | 清晰語音 |
| 靜音 | 0.003 | ~0.3（100x 放大） | 像是有人在說話的噪音 |

### 建議修復（待實作）

降低 `m` 值，從 100 降到 10~20（+20~26dB）：

```
dynaudnorm=p=0.95:m=15:s=5
```

或改用 compressor + limiter 組合，只壓縮動態範圍而不過度放大靜音：

```
acompressor=threshold=-20dB:ratio=4:attack=5:release=50,alimiter=limit=0.95
```

需要實測比較兩種方案對 ASR 品質的影響。

---

## 根因三：雙重 VAD 截斷（結尾漏字）

### 問題

目前有 **兩層 VAD** 在切割音訊：

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────┐
│ 外部 VAD        │     │ WAV 音檔         │     │ Whisper      │
│ (RMS squelch    │────▶│ 已經過 squelch   │────▶│ 內建 VAD     │
│  在 transcribe  │     │ 切割的語音段     │     │ 再做一次     │
│  .ts)           │     │                  │     │ 靜音偵測     │
└─────────────────┘     └──────────────────┘     └──────────────┘
         ↑ 第一次切割                                    ↑ 第二次切割
```

Whisper 的 `vad: 'true'` 參數（使用 Silero VAD v6.2.0）會在收到的音訊上**再做一次**語音活動偵測。

問題場景：
1. 外部 VAD 以 1200ms 靜音門檻結束錄音
2. 結尾的最後幾個字（如「血氧 94」）音量較低或語速放慢
3. 外部 VAD 剛好在「血氧 94」後面切斷
4. Whisper 內建 VAD 看到結尾能量下降，判定為非語音 → **再砍一刀** → 「血氧 94」消失

兩層 VAD 各自獨立運作，各有自己的靜音判定邏輯，結果是邊界處的語音被雙重截斷。

### 建議修復（待實作）

**方案 A：關閉 Whisper 內建 VAD**

在 `whisper-provider.ts` 中將 `vad` 改為 `'false'`：

```ts
// whisper-provider.ts
const formData = createFormData({
  // ...
  vad: 'false',   // 外部 VAD 已處理，不需要二次切割
})
```

外部 VAD 已經負責了語音段的切割，Whisper 只需要對收到的完整 WAV 做轉錄即可。

**方案 B：加尾部 padding**

在 `finishTransmission` 中，於 WAV 結尾追加 300~500ms 靜音 padding：

```ts
const paddingBytes = preprocessorConfig.SAMPLE_RATE * 2 * 0.3  // 300ms
const silence = new Uint8Array(paddingBytes)
// 追加到 combinedBuffer 末尾再組 WAV
```

這樣即使 Whisper VAD 砍尾，也只是砍到 padding 而非實際語音。

**建議先試方案 A**，因為更簡單且直接消除根因。

---

## 根因四：Chunk 大小不固定（RMS 不穩定）

### 問題

ffmpeg stdout 經 `reader.read()` 讀取，每次回傳的 bytes 數量不固定（可能是 256 bytes 到數 KB）。對小 chunk 計算 RMS 會得到不穩定的值：

```
chunk 大小    樣本數    RMS 統計可靠性
─────────    ─────    ──────────
256 bytes    128      非常不穩定
1024 bytes   512      偏不穩定
3200 bytes   1600     穩定（100ms，推薦）
```

不穩定的 RMS 會導致 squelch 閃爍：語音中間偶爾一個低 RMS 的小 chunk 觸發靜音計時，或噪音中偶爾一個高 RMS 的小 chunk 誤觸錄音。

### 修復（已完成）

新增 `pendingBytes` buffer，將 ffmpeg 輸出累積到 3200 bytes（`METER_CHUNK_BYTES`，100ms at 16kHz mono s16le）後才做一次 RMS 計算。與 Python 端的 `radio_audio_core.py:METER_CHUNK_BYTES = 3200` 保持一致。

相關程式碼：`src/transcribe.ts`、`src/contstants.ts`

---

## Whisper 模型選擇

| 模型 | 參數量 | Decoder 層數 | 中文品質 | 速度 |
|------|--------|-------------|---------|------|
| **large-v3** | 1550M | 32 | 最高 | 1x |
| large-v3-turbo | 809M | 4 | 稍低 | ~6-8x |
| distil-large-v3 | 756M | 2 | 較低（英文優化） | ~6x |
| medium | 769M | 24 | 中等 | ~3x |

**目前使用 large-v3**，對於嘈雜中文 + 醫療術語場景是正確選擇。

Turbo 版本將 32 層 decoder 蒸餾到 4 層，在乾淨英文語音上品質損失不大，但在嘈雜中文 radio 場景下差距會更顯著（decoder 深度直接影響 language model 對 noisy input 的修正能力）。

---

## 修復狀態總覽

| 問題 | 影響 | 狀態 | 備註 |
|------|------|------|------|
| Pre-roll 截斷 | 開頭漏字 | 已修復 | `PRE_ROLL_CHUNKS=5`（500ms） |
| Chunk 大小不固定 | RMS 不穩定 | 已修復 | 固定 3200 bytes per chunk |
| dynaudnorm m=100 | 幻覺 token | 待優化 | 建議降到 m=15 或改用 compressor |
| 雙重 VAD | 結尾漏字 | 待優化 | 建議關閉 Whisper 內建 VAD |
| Notch filter -80dB | 語音可懂度下降 | 待評估 | 630Hz/950Hz 在語音 F1/F2 範圍 |
