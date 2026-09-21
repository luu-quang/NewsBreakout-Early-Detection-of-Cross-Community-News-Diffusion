"""Multilingual text embedding for event clustering using sentence-transformers."""

from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Default multilingual model — lightweight, fast, supports 50+ languages including Vietnamese
DEFAULT_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


class ArticleEmbedder:
    """Encodes article text (title + description) into dense vectors."""

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, device: Optional[str] = None) -> None:
        """Initialize the embedder with a sentence-transformers model.

        Args:
            model_name: HuggingFace model identifier.
            device: 'cpu', 'cuda', or None for auto-detection.
        """
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model = SentenceTransformer(model_name, device=device)
        self.embedding_dim = self.model.get_embedding_dimension()
        logger.info(
            "Loaded model '%s' (dim=%d, device=%s)",
            model_name,
            self.embedding_dim,
            self.model.device,
        )

    def _prepare_texts(self, df: pd.DataFrame) -> List[str]:
        """Combine title and description into a single text per article.

        Strategy: "title. description" — the period forces a sentence boundary
        so the transformer treats them as two clauses rather than one.
        """
        titles = df["title"].fillna("").astype(str)
        descriptions = df["description"].fillna("").astype(str)
        combined = titles + ". " + descriptions
        # Fall back to title-only when description is empty
        combined = combined.where(descriptions.str.len() > 0, titles)
        return combined.tolist()

    def embed(
        self,
        df: pd.DataFrame,
        batch_size: int = 64,
        show_progress: bool = True,
    ) -> np.ndarray:
        """Compute embeddings for all articles.

        Args:
            df: DataFrame with 'title' and 'description' columns.
            batch_size: Encoding batch size.
            show_progress: Show tqdm progress bar.

        Returns:
            np.ndarray of shape (n_articles, embedding_dim), L2-normalized.
        """
        texts = self._prepare_texts(df)
        logger.info("Embedding %d articles with batch_size=%d …", len(texts), batch_size)

        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress,
            normalize_embeddings=True,  # L2-normalize for cosine similarity via dot product
            convert_to_numpy=True,
        )
        logger.info("Embedding complete — shape %s", embeddings.shape)
        return embeddings
