"""
FireRedASR HTTP server for radio-monitor (segment mode).
Requires: clone FireRedASR repo, install its requirements, download models, then pip install -r scripts/firered-requirements.txt
See docs/firered.md.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, verbose=False)

from flask import Flask, request, jsonify

REPO_ENV = "FIREREDASR_REPO"
MODEL_DIR_ENV = "FIREREDASR_MODEL_DIR"
MODEL_TYPE_ENV = "FIREREDASR_MODEL_TYPE"
HOST = "0.0.0.0"
PORT = 8001

app = Flask(__name__)

firered_repo = os.environ.get(REPO_ENV)
if not firered_repo or not Path(firered_repo).is_dir():
    print(f"Error: set {REPO_ENV} to the FireRedASR repo directory (clone from https://github.com/FireRedTeam/FireRedASR)", file=sys.stderr)
    sys.exit(1)

sys.path.insert(0, firered_repo)

from fireredasr.models.fireredasr import FireRedAsr

model_type = os.environ.get(MODEL_TYPE_ENV, "aed").lower()
model_dir = os.environ.get(MODEL_DIR_ENV)
if not model_dir:
    model_dir = str(Path(firered_repo) / "pretrained_models" / ("FireRedASR-AED-L" if model_type == "aed" else "FireRedASR-LLM-L"))
elif not Path(model_dir).is_absolute():
    model_dir = str(Path(firered_repo) / model_dir)

def _required_model_files(asr_type: str) -> list[str]:
    if asr_type == "aed":
        return ["model.pth.tar", "dict.txt", "train_bpe1000.model"]
    return ["model.pth.tar", "asr_encoder.pth.tar", "Qwen2-7B-Instruct"]

_model_dir = Path(model_dir)
if not _model_dir.is_dir():
    print(f"Error: model dir not found: {model_dir}", file=sys.stderr)
    print(f"Set {MODEL_DIR_ENV} to a directory with the FireRedASR model files, or download the model there. See docs/firered.md.", file=sys.stderr)
    sys.exit(1)
missing = [f for f in _required_model_files(model_type) if not (_model_dir / f).exists()]
if missing:
    print(f"Error: missing in {model_dir}: {', '.join(missing)}", file=sys.stderr)
    print(f"Run once: python scripts/download_firered_model.py   (then start this server again). See docs/firered.md.", file=sys.stderr)
    sys.exit(1)

print("Loading FireRedASR model...", file=sys.stderr)
model = FireRedAsr.from_pretrained(model_type, model_dir)
print(f"Ready. Model: {model_type}, dir: {model_dir}", file=sys.stderr)

TRANSCRIBE_OPTS_AED = {
    "use_gpu": 1,
    "beam_size": 3,
    "nbest": 1,
    "decode_max_len": 0,
    "softmax_smoothing": 1.0,
    "aed_length_penalty": 0.0,
    "eos_penalty": 1.0,
}
TRANSCRIBE_OPTS_LLM = {
    "use_gpu": 1,
    "beam_size": 3,
    "nbest": 1,
    "decode_max_len": 0,
    "decode_min_len": 0,
    "repetition_penalty": 1.0,
    "llm_length_penalty": 0.0,
    "temperature": 1.0,
}


@app.route("/transcribe", methods=["POST"])
def transcribe():
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    wav_bytes = request.files["file"].read()
    if not wav_bytes:
        return jsonify({"error": "empty file"}), 400

    opts = TRANSCRIBE_OPTS_AED if model_type == "aed" else TRANSCRIBE_OPTS_LLM
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes)
        tmp_path = f.name
    try:
        results = model.transcribe(["segment"], [tmp_path], opts)
        text = (results[0].get("text") or "").strip()
        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    app.run(host=HOST, port=PORT)
