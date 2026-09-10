方法 A：用 Python 直接將 MP3 模擬成「即時串流」（免安裝）
這個方法的原理是利用 pydub 讀取 MP3，強制將它轉換為 Whisper 系統最愛的 16000Hz、單聲道（Mono）、16-bit PCM 格式，然後用一個 while 迴圈搭配 time.sleep()，像水龍頭一樣每 30 毫秒吐出固定長度的資料，完美模擬無線電正在即時說話的狀態。

1. 先安裝必備套件
Bash
pip install pydub faster-whisper
(注意：電腦需要安裝 ffmpeg 才能讓 pydub 讀取 MP3)

2. 模擬即時串流的完整測試程式碼
Python
import time
from pydub import AudioSegment
from faster_whisper import WhisperModel

# 1. 初始化本地模型
print("正在載入地端大模型...")
model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")

# 2. 讀取你的 MP3 檔案，並標準化為無線電專用格式 (16kHz, Mono)
print("正在處理 MP3 檔案...")
audio = AudioSegment.from_mp3("your_radio_file.mp3")
audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)

# 3. 定義串流參數
# 16kHz, 16bit(2 bytes) 的音訊，每秒有 16000 * 2 = 32000 bytes 的資料
# 如果我們每 30 毫秒 (0.03秒) 送一次資料，每次長度就是 32000 * 0.03 = 960 bytes
chunk_duration = 0.03  
chunk_size = int(16000 * 2 * chunk_duration)  

raw_data = audio.raw_data
offset = 0

print("● 開始模擬即時無線電訊號輸入... (不播放聲音，直接吃資料)")

# 這裡就是你的即時處理緩衝區（模擬實體線路的輸入）
live_buffer = bytearray()

while offset < len(raw_data):
    start_time = time.time()
    
    # 擷取 30ms 的音訊片段
    chunk = raw_data[offset:offset + chunk_size]
    offset += chunk_size
    
    # 將片段塞入你的即時監聽緩衝區
    live_buffer.extend(chunk)
    
    # === 這裡可以塞你的 VAD 判斷邏輯 ===
    # 為了示範，我們假設累積到 5 秒（160000 bytes）就丟給 Whisper 轉錄一次
    if len(live_buffer) >= 160000:
        # 將 bytearray 轉換為 faster-whisper 接收的 float32 格式
        import numpy as np
        audio_np = np.frombuffer(live_buffer, dtype=np.int16).astype(np.float32) / 32768.0
        
        # 進行地端轉錄
        segments, info = model.transcribe(audio_np, beam_size=5, language="zh")
        for segment in segments:
            print(f"[{segment.start:.2f}s -> {segment.end:.2f}s]: {segment.text}")
            
        # 清空緩衝區，等待下一段語音
        live_buffer.clear()
    
    # 控制迴圈速度，使其符合現實世界的即時時間（每 30ms 跑一次）
    elapsed = time.time() - start_time
    if elapsed < chunk_duration:
        time.sleep(chunk_duration - elapsed)

print("■ MP3 檔案即時模擬轉錄結束。")