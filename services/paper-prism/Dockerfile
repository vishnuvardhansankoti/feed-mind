# ONNX-slimmed image (PRD §5 / Branch 4b): onnxruntime + tokenizers, no torch.
# Target ~300-400MB so it stays under the Artifact Registry free-storage line.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf

WORKDIR /app

# 1. Dependencies (no compiler needed — all wheels are manylinux).
#    requirements.txt is GENERATED from pyproject.toml (`uv pip compile`, see
#    scripts/lock-all.sh) and is the single dependency list — the former
#    core/deploy split existed only so a SINK=local run could skip the
#    Firestore client, which one lockfile makes not worth maintaining.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 2. Bake the MiniLM ONNX weights + tokenizer into the image so the scheduled
#    job never depends on HuggingFace at runtime.
RUN python -c "from huggingface_hub import hf_hub_download as d; \
d('Xenova/all-MiniLM-L6-v2','onnx/model.onnx'); \
d('Xenova/all-MiniLM-L6-v2','tokenizer.json')"

# After prefetch, forbid runtime network calls to HF — use the baked cache only.
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

# 3. Application code.
COPY src ./src
ENV PYTHONPATH=/app/src

# Run-to-completion batch entrypoint (the Cloud Run Job command).
ENTRYPOINT ["python", "-m", "paper_prism"]
