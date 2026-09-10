"""
Voxtral Mini 4B Realtime HTTP server for radio-monitor (segment mode).
Use a venv and: pip install -r scripts/voxtral-requirements.txt
See docs/voxtral.md.
"""
from __future__ import annotations

import io
import sys
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import soundfile as sf
import librosa
from flask import Flask, request, jsonify
from transformers import VoxtralRealtimeForConditionalGeneration, AutoProcessor

REPO_ID = "mistralai/Voxtral-Mini-4B-Realtime-2602"
HOST = "0.0.0.0"
PORT = 8000

app = Flask(__name__)

print("Loading processor and model...", file=sys.stderr)
processor = AutoProcessor.from_pretrained(REPO_ID)
# CPU only: device_map="auto" on macOS can offload to disk (meta) and clash with MPS.
model = VoxtralRealtimeForConditionalGeneration.from_pretrained(REPO_ID, device_map="cpu")
target_sr = processor.feature_extractor.sampling_rate
print(f"Ready. Sample rate: {target_sr}", file=sys.stderr)


@app.route("/transcribe", methods=["POST"])
def transcribe():
    content_length = request.content_length
    print(f"[transcribe] POST /transcribe (Content-Length: {content_length})", file=sys.stderr)

    if "file" not in request.files:
        print("[transcribe] 400: no file in request.files", file=sys.stderr)
        return jsonify({"error": "no file"}), 400

    file_storage = request.files["file"]
    wav_bytes = file_storage.read()
    filename = getattr(file_storage, "filename", "") or "(no filename)"

    print(f"[transcribe] file received: {filename!r}, size={len(wav_bytes)} bytes", file=sys.stderr)
    if not wav_bytes:
        print("[transcribe] 400: empty file", file=sys.stderr)
        return jsonify({"error": "empty file"}), 400

    try:
        buf = io.BytesIO(wav_bytes)
        data, sr = sf.read(buf, dtype="float32")
        n_samples = data.shape[0]
        duration_sec = n_samples / sr
        print(f"[transcribe] WAV decoded: sr={sr}, samples={n_samples}, duration={duration_sec:.2f}s", file=sys.stderr)

        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != target_sr:
            data = librosa.resample(data, orig_sr=sr, target_sr=target_sr)
            print(f"[transcribe] resampled {sr} -> {target_sr}", file=sys.stderr)

        t0 = time.perf_counter()
        inputs = processor(data, return_tensors="pt")
        inputs = inputs.to("cpu", dtype=model.dtype)
        outputs = model.generate(**inputs, max_new_tokens=256)
        decoded = processor.batch_decode(outputs, skip_special_tokens=True)
        text = (decoded[0] or "").strip()
        elapsed = time.perf_counter() - t0
        print(f"[transcribe] inference {elapsed:.2f}s -> text len={len(text)}: {text[:80]!r}{'...' if len(text) > 80 else ''}", file=sys.stderr)
        return jsonify({"text": text})
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        print(f"[transcribe] 500: {e!r}", file=sys.stderr)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host=HOST, port=PORT)
