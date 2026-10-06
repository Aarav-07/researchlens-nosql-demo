# ResearchLens API.
#
# The embedding model is baked into the image at build time. Downloading it on
# first request instead would make a cold container slow, and a hub outage would
# silently drop the process onto the hashing fallback - which is much weaker and
# writes vectors in a different space to the rest of the corpus.
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf

WORKDIR /app

# curl is used by the container healthcheck below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-ml.txt ./
# The CPU-only torch wheel keeps the image a few GB smaller than the CUDA build.
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-ml.txt

ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
ENV RL_EMBEDDING_MODEL_NAME=${EMBEDDING_MODEL}
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"

COPY . .

# Run unprivileged; the model cache has to be readable by that user.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app /opt/hf
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
