# FireRedASR (Mandarin-focused) as ASR provider

[FireRedASR](https://huggingface.co/fireredteam) is optimized for Mandarin, Chinese dialects and English. radio-monitor calls it in **segment mode**: each silence-separated chunk is sent as one WAV file to an HTTP endpoint.

## Quick start

**1. Clone FireRedASR and install dependencies**

```bash
git clone https://github.com/FireRedTeam/FireRedASR.git
cd FireRedASR
python -m venv .venv-firered
source .venv-firered/bin/activate   # Windows: .venv-firered\Scripts\activate
pip install -r requirements.txt
```

**2. Download model weights**

Download from [Hugging Face](https://huggingface.co/fireredteam) and place files in `pretrained_models/` inside the FireRedASR repo.

- **AED** (1.1B, faster; input up to 60s per segment):

  ```bash
  huggingface-cli download fireredteam/FireRedASR-AED-L --local-dir pretrained_models/FireRedASR-AED-L
  ```

- **LLM** (8.3B, higher quality; input up to 30s per segment): download [FireRedASR-LLM-L](https://huggingface.co/fireredteam/FireRedASR-LLM-L) and [Qwen2-7B-Instruct](https://huggingface.co/Qwen/Qwen2-7B-Instruct). Put both in `pretrained_models/`, then from `pretrained_models/FireRedASR-LLM-L` run:

  ```bash
  ln -s ../Qwen2-7B-Instruct Qwen2-7B-Instruct
  ```

**3. Install server deps and run** (from `packages/radio-monitor`)

```bash
cd path/to/rd-projects-monorepo/packages/radio-monitor
pip install -r scripts/firered-requirements.txt
export FIREREDASR_REPO=/path/to/FireRedASR
# Optional: FIREREDASR_MODEL_DIR=pretrained_models/FireRedASR-AED-L  (default)
# Optional: FIREREDASR_MODEL_TYPE=aed  (or llm)
python scripts/firered_server.py
```

Server listens on `http://0.0.0.0:8001/transcribe`. If the model dir or required files are missing, the script exits with a clear error and hints.

**4. Point radio-monitor at FireRedASR**

```bash
ASR_PROVIDER=firered FIRERED_ASR_API_URL=http://127.0.0.1:8001/transcribe bun run app:dev
```

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `FIREREDASR_REPO` | Yes | Path to the cloned FireRedASR repo directory. |
| `FIREREDASR_MODEL_DIR` | No | Model directory (default: `pretrained_models/FireRedASR-AED-L` inside the repo). Can be absolute or relative to repo. |
| `FIREREDASR_MODEL_TYPE` | No | `aed` (default) or `llm`. |

Optional: set `HF_TOKEN` in `.env` for faster or gated model downloads; the server loads `.env` from the package root.

## Request / response

- **Request:** `POST /transcribe`, multipart form with `file` = WAV (16 kHz mono preferred). Optional form field `context` is ignored by this server.
- **Response:** `{ "text": "轉寫結果" }`

Input length: FireRedASR-AED supports up to 60s per segment; FireRedASR-LLM up to 30s. Longer input may cause hallucination or errors.
