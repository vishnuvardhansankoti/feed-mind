# ONNX-slimmed image, same approach as services/paper-prism: onnxruntime +
# tokenizers, no torch. Target ~300-400MB so it stays under the Artifact
# Registry free-storage line.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf

WORKDIR /app

# 1. Dependencies (no compiler needed — all wheels are manylinux).
#    requirements.txt is GENERATED from pyproject.toml (`uv pip compile`, see
#    scripts/lock-all.sh).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 2. Bake the MiniLM ONNX weights + tokenizer into the image so a cold Cloud
#    Run instance never depends on HuggingFace at request time.
RUN python -c "from huggingface_hub import hf_hub_download as d; \
d('Xenova/all-MiniLM-L6-v2','onnx/model.onnx'); \
d('Xenova/all-MiniLM-L6-v2','tokenizer.json')"

# After prefetch, forbid runtime network calls to HF — use the baked cache only.
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

# 3. Application code.
COPY src ./src
ENV PYTHONPATH=/app/src

# Cloud Run service: gunicorn serves main:app on $PORT (Cloud Run sets it;
# 8080 is the default outside Cloud Run). Single worker, matching the
# feedmind-audio pattern of "one request at a time" — a push that arrives
# mid-run should queue behind it, not race it for the same curation_status
# backlog.
ENV PORT=8080
CMD exec gunicorn --bind :$PORT --workers 1 --threads 1 --timeout 0 news_curator.main:app
