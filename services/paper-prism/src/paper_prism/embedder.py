"""Stage-1 ranking: local embeddings via ONNX Runtime (PRD §3.2 steps 2-3).

Runs `all-MiniLM-L6-v2` with onnxruntime + tokenizers — no torch. Produces
mean-pooled, L2-normalized sentence embeddings so cosine similarity is a dot
product. The ONNX weights and tokenizer are pulled once from the Xenova mirror
and cached by huggingface_hub.
"""

from __future__ import annotations

import logging

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

log = logging.getLogger("paper_prism.embedder")

_REPO = "Xenova/all-MiniLM-L6-v2"
_ONNX_FILE = "onnx/model.onnx"
_TOKENIZER_FILE = "tokenizer.json"
_MAX_TOKENS = 256


class Embedder:
    def __init__(self) -> None:
        log.info("Loading MiniLM (ONNX) — first run downloads ~90MB...")
        model_path = hf_hub_download(_REPO, _ONNX_FILE)
        tokenizer_path = hf_hub_download(_REPO, _TOKENIZER_FILE)

        self.session = ort.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )
        self._input_names = {i.name for i in self.session.get_inputs()}

        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.tokenizer.enable_truncation(max_length=_MAX_TOKENS)
        self.tokenizer.enable_padding()

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        """Return an (n, dim) float32 array of normalized embeddings."""
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)

        vectors: list[np.ndarray] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            vectors.append(self._encode_batch(batch))
        return np.vstack(vectors)

    def _encode_batch(self, batch: list[str]) -> np.ndarray:
        encodings = self.tokenizer.encode_batch(batch)
        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array(
            [e.attention_mask for e in encodings], dtype=np.int64
        )

        inputs = {"input_ids": input_ids, "attention_mask": attention_mask}
        if "token_type_ids" in self._input_names:
            inputs["token_type_ids"] = np.zeros_like(input_ids)

        # Output 0 is last_hidden_state: (batch, tokens, dim)
        last_hidden = self.session.run(None, inputs)[0]
        return _mean_pool_normalize(last_hidden, attention_mask)


def _mean_pool_normalize(last_hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
    mask_f = mask[:, :, None].astype(np.float32)
    summed = (last_hidden * mask_f).sum(axis=1)
    counts = np.clip(mask_f.sum(axis=1), a_min=1e-9, a_max=None)
    pooled = summed / counts
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    return (pooled / np.clip(norms, 1e-9, None)).astype(np.float32)


def rank_top_k(
    profile_vec: np.ndarray, candidate_vecs: np.ndarray, k: int
) -> list[tuple[int, float]]:
    """Return [(index, cosine_score), ...] for the top-k candidates.

    Vectors are L2-normalized, so cosine == dot product. Fewer than k are
    returned when there are fewer candidates (PRD §3.3 tolerance).
    """
    if candidate_vecs.shape[0] == 0:
        return []
    scores = candidate_vecs @ profile_vec
    k = min(k, scores.shape[0])
    top_idx = np.argsort(-scores)[:k]
    return [(int(i), float(scores[i])) for i in top_idx]
