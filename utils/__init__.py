from __future__ import annotations

from .my_vcr import MyVcr
from .qwen_model import FORCE_MULTIMODAL_MODELS, create_qwen_model, normalize_content

__all__ = [
    "MyVcr",
    "qwen_embeddings",
    "create_qwen_model",
    "FORCE_MULTIMODAL_MODELS",
    "normalize_content",
]


class _LazyQwenEmbeddings:
    _instance = None

    def _get_instance(self):
        if self._instance is None:
            from .qwen_embeddings import qwen_embeddings

            self._instance = qwen_embeddings
        return self._instance

    def __getattr__(self, name: str):
        return getattr(self._get_instance(), name)


qwen_embeddings = _LazyQwenEmbeddings()