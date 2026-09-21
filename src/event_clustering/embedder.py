"""Multilingual text embedding for event clustering using sentence-transformers."""

from __future__ import annotations

import hashlib
import html
import logging
import re
import unicodedata
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Default multilingual model — lightweight, fast, supports 50+ languages including Vietnamese
DEFAULT_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

_WHITESPACE = re.compile(r"\s+")


def clean_text(value: object) -> str:
    """Normalise raw feed text for embedding: HTML-unescape, NFC, collapse whitespace.

    Only used to build embedding input; the article columns themselves are never modified.
    """
    if value is None or value is pd.NA or value is pd.NaT or (isinstance(value, float) and np.isnan(value)):
        return ""
    text = html.unescape(str(value))
    text = unicodedata.normalize("NFC", text)
    return _WHITESPACE.sub(" ", text).strip()


def build_texts(df: pd.DataFrame) -> List[str]:
    """Build one embedding text per article: ``"title. description"`` (title only if no description)."""
    titles = df["title"].map(clean_text)
    descriptions = df["description"].map(clean_text)
    combined = titles + ". " + descriptions
    combined = combined.where(descriptions.str.len() > 0, titles)
    return combined.tolist()


class ArticleEmbedder:
    """Encodes article text (title + description) into dense L2-normalised vectors."""

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, device: Optional[str] = None) -> None:
        """Store model settings; the model itself is loaded lazily on first encode.

        Args:
            model_name: HuggingFace model identifier.
            device: 'cpu', 'cuda', or None for auto-detection.
        """
        self.model_name = model_name
        self.device = device
        self._model = None
        self.embedding_dim: Optional[int] = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
            logger.info("Loaded model '%s' (device=%s)", self.model_name, self._model.device)
        return self._model

    def _cache_path(self, cache_dir: Path, article_ids: List[str], texts: List[str]) -> Path:
        digest = hashlib.sha256()
        digest.update(self.model_name.encode("utf-8"))
        for article_id, text in zip(article_ids, texts):
            digest.update(b"\x00")
            digest.update(str(article_id).encode("utf-8"))
            digest.update(b"\x01")
            digest.update(text.encode("utf-8"))
        safe_model = re.sub(r"[^A-Za-z0-9._-]", "_", self.model_name)
        return cache_dir / f"emb_{safe_model}_{digest.hexdigest()[:16]}.npy"

    def embed(
        self,
        df: pd.DataFrame,
        batch_size: int = 64,
        show_progress: bool = True,
        cache_dir: Optional[Path] = None,
    ) -> np.ndarray:
        """Compute embeddings for all articles (row order preserved).

        Args:
            df: DataFrame with 'article_id', 'title' and 'description' columns.
            batch_size: Encoding batch size.
            show_progress: Show tqdm progress bar.
            cache_dir: If given, embeddings are cached on disk keyed by model + article ids + cleaned text.

        Returns:
            np.ndarray of shape (n_articles, embedding_dim), L2-normalised.
        """
        texts = build_texts(df)

        cache_file: Optional[Path] = None
        if cache_dir is not None:
            cache_dir = Path(cache_dir)
            cache_file = self._cache_path(cache_dir, df["article_id"].astype(str).tolist(), texts)
            if cache_file.is_file():
                embeddings = np.load(cache_file)
                self.embedding_dim = int(embeddings.shape[1])
                logger.info("Loaded cached embeddings from %s", cache_file)
                return embeddings

        logger.info("Embedding %d articles with batch_size=%d …", len(texts), batch_size)
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress,
            normalize_embeddings=True,  # L2-normalise so cosine similarity is a dot product
            convert_to_numpy=True,
        )
        self.embedding_dim = int(embeddings.shape[1])
        logger.info("Embedding complete — shape %s", embeddings.shape)

        if cache_file is not None:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            np.save(cache_file, embeddings)
        return embeddings
