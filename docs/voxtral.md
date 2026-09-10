# Voxtral Mini 4B Realtime as ASR provider

[Voxtral Mini 4B Realtime](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602) supports 13 languages and can be used as an alternative to Whisper. radio-monitor calls it in **segment mode**: each silence-separated chunk is sent as one WAV file to an HTTP endpoint.

## Quick start (recommended)

**1. Create a venv and install deps** (GPU with ≥16GB VRAM recommended; PyTorch is required):

```bash
cd packages/radio-monitor
python -m venv .venv-voxtral
source .venv-voxtral/bin/activate   # Windows: .venv-voxtral\Scripts\activate
pip install -r scripts/voxtral-requirements.txt
```

For GPU: install PyTorch with CUDA first from [pytorch.org](https://pytorch.org/get-started/locally/), then run the `pip install -r` above.

**2. Start the Voxtral HTTP server** (with the same venv activated):

```bash
python scripts/voxtral_server.py
```

First run will download the model from Hugging Face. Server listens on `http://0.0.0.0:8000/transcribe`.  
Optional: set `HF_TOKEN` in `.env` (or create a token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)) for higher rate limits and gated models; the server loads `.env` from the package root.

**3. Point radio-monitor at Voxtral:**

```bash
ASR_PROVIDER=voxtral VOXTRAL_API_URL=http://127.0.0.1:8000/transcribe bun run app:dev
```

Or with Whisper server in parallel:

```bash
ASR_PROVIDER=voxtral VOXTRAL_API_URL=http://127.0.0.1:8000/transcribe bun run dev
```

---

## Option B: vLLM Realtime API

vLLM exposes a [Realtime API](https://blog.vllm.ai/2026/01/31/streaming-realtime.html) (WebSocket). For segment-based use you would need an adapter that accepts HTTP POST with a WAV, streams it into the WebSocket, and returns the final transcript. That is more involved; the script above is simpler for radio-monitor’s chunked flow.
