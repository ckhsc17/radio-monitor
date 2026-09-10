"""
Download FireRedASR-AED-L (or LLM) model files from Hugging Face into FIREREDASR_REPO/pretrained_models/.

Pipeline:
  1. Load .env (HF_TOKEN if set).
  2. Resolve FIREREDASR_REPO (must be the FireRedASR clone path) and FIREREDASR_MODEL_TYPE (aed | llm).
  3. AED: repo fireredteam/FireRedASR-AED-L → 4 files (model.pth.tar, dict.txt, train_bpe1000.model, cmvn.ark).
  4. LLM: repo fireredteam/FireRedASR-LLM-L → 2 files (model.pth.tar, asr_encoder.pth.tar).
  5. For each file: skip if already in local_dir, else hf_hub_download to local_dir.

Run from packages/radio-monitor with venv active. Install: pip install huggingface_hub [tqdm]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, verbose=False)

REPO_ENV = "FIREREDASR_REPO"
MODEL_TYPE_ENV = "FIREREDASR_MODEL_TYPE"
REPO_ID_AED = "fireredteam/FireRedASR-AED-L"
REPO_ID_LLM = "fireredteam/FireRedASR-LLM-L"

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, desc=None, total=None, **kwargs):
        return iterable


def main():
    print("[1/4] Checking environment...", file=sys.stderr)
    firered_repo = os.environ.get(REPO_ENV)
    if not firered_repo or not Path(firered_repo).is_dir():
        print(f"Error: set {REPO_ENV} to the FireRedASR repo directory.", file=sys.stderr)
        sys.exit(1)
    print(f"  {REPO_ENV}={firered_repo}", file=sys.stderr)

    model_type = os.environ.get(MODEL_TYPE_ENV, "aed").lower()
    if model_type == "aed":
        repo_id = REPO_ID_AED
        local_dir = Path(firered_repo) / "pretrained_models" / "FireRedASR-AED-L"
        files = ["model.pth.tar", "dict.txt", "train_bpe1000.model", "cmvn.ark"]
    else:
        repo_id = REPO_ID_LLM
        local_dir = Path(firered_repo) / "pretrained_models" / "FireRedASR-LLM-L"
        files = ["model.pth.tar", "asr_encoder.pth.tar"]

    print(f"[2/4] Model type: {model_type!r} -> repo {repo_id}", file=sys.stderr)
    print(f"  local_dir={local_dir}", file=sys.stderr)
    print(f"  files={files}", file=sys.stderr)

    local_dir.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("Run: pip install huggingface_hub", file=sys.stderr)
        sys.exit(1)

    # FireRedASR-AED-L model.pth.tar is ~4.4 GB (LFS); allow resume if interrupted.
    LARGE_FILE_MB = {"model.pth.tar": 4400}
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
    to_download = [(i, fn) for i, fn in enumerate(files) if not (local_dir / fn).exists()]
    skipped = len(files) - len(to_download)
    if skipped:
        print(f"[3/4] Skipping {skipped} file(s) (already present).", file=sys.stderr)
    print(f"[4/4] Downloading {len(to_download)} file(s)...", file=sys.stderr)

    for i, fn in tqdm(to_download, desc="Files", unit="file", file=sys.stderr):
        note = f" (~{LARGE_FILE_MB[fn]} MB, may take several minutes)" if fn in LARGE_FILE_MB else ""
        print(f"  Downloading ({i + 1}/{len(files)}) {fn}{note} ...", file=sys.stderr)
        sys.stderr.flush()
        hf_hub_download(
            repo_id=repo_id,
            filename=fn,
            local_dir=str(local_dir),
            resume_download=True,
        )
        path = local_dir / fn
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"  -> {fn} ok ({size_mb:.2f} MB)", file=sys.stderr)

    print(f"Done. Model dir: {local_dir}", file=sys.stderr)
    for fn in files:
        p = local_dir / fn
        if p.exists():
            print(f"  {fn}: {p.stat().st_size / (1024*1024):.2f} MB")


if __name__ == "__main__":
    main()
