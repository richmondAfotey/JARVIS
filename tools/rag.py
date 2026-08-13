"""
Local RAG - "chat with your own documents" (Phase 30).

Indexes a folder of text documents into chunks, builds a term-frequency
inverse-document-frequency (TF-IDF) model locally (numpy only, no API
keys, nothing leaves the machine), and retrieves the most relevant chunks
for a question. The retrieved text is what the AI reasons over, so JARVIS
can answer from YOUR documents instead of guessing.

Design notes:

* TF-IDF is a classic, honest retrieval method: it needs no downloads or
  models and works offline. It is lexical, not semantic - "car" and
  "vehicle" will not match unless the actual words appear.
* Chunks are ~500 words with a 50-word overlap so a retrieval spans
  sentence boundaries.
* The index is cached as JSON under the data folder so a restart does not
  re-scan everything.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tools.base import Tool, ToolError
from utils.logger import get_logger

log = get_logger(__name__)

_CHUNK_WORDS = 500
_CHUNK_OVERLAP = 50
_MAX_FILES = 200
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "of", "in",
    "on", "at", "to", "for", "with", "by", "from", "as", "is", "are", "was",
    "were", "be", "been", "being", "it", "its", "this", "that", "these",
    "those", "i", "you", "he", "she", "we", "they", "my", "your", "our",
    "their", "not", "no", "so", "do", "does", "did", "what", "which", "who",
    "whom", "when", "where", "why", "how", "all", "any", "each", "more",
    "most", "other", "some", "such", "only", "own", "same", "too", "very",
}
_WORD_RE = re.compile(r"[a-z0-9']+")

_INDEX_CACHE_FILE = "rag_index.json"


class RagIndex:
    """A TF-IDF index over a folder of text documents."""

    def __init__(self, root_dir: Path | str | None = None):
        self.root_dir = Path(root_dir) if root_dir else None
        self.chunks: list[dict] = []  # {"id", "source", "text"}
        self.vocab: list[str] = []
        self._tfidf: Any = None  # numpy ndarray (n_chunks x n_terms)

    # -- Indexing -----------------------------------------------------------
    def index_folder(self, path: Path | str, reset: bool = True) -> dict:
        """Scan a folder (or single file) and build/update the index."""
        folder = Path(path)
        if folder.is_file():
            files = [folder]
        elif folder.is_dir():
            files = [
                p for p in sorted(folder.rglob("*"))
                if p.is_file() and _is_text_file(p)
            ][:_MAX_FILES]
        else:
            raise ToolError(f"Path not found: {path}")

        if not files:
            raise ToolError(f"No text documents found in {path}")

        if reset:
            self.chunks = []
        for file in files:
            text = _safe_read(file)
            if text:
                for i, chunk in enumerate(_chunk_text(text)):
                    self.chunks.append(
                        {"id": len(self.chunks), "source": str(file), "text": chunk}
                    )

        if not self.chunks:
            raise ToolError("No readable text was extracted from the documents.")
        self._build()
        return {"documents": len(files), "chunks": len(self.chunks)}

    def _build(self) -> None:
        """Build vocab + TF-IDF matrix from the current chunks."""
        tokenized = [_tokens(c["text"]) for c in self.chunks]
        vocab_set: dict[str, int] = {}
        for tokens in tokenized:
            for term in tokens:
                if term not in vocab_set:
                    vocab_set[term] = len(vocab_set)
        self.vocab = list(vocab_set)

        if not self.vocab:
            self._tfidf = None
            return

        import numpy as np  # noqa: PLC0415

        n_docs = len(self.chunks)
        n_terms = len(self.vocab)
        # Document frequency per term (for IDF).
        df = np.zeros(n_terms, dtype=float)
        tf = np.zeros((n_docs, n_terms), dtype=float)
        for row, tokens in enumerate(tokenized):
            counts: dict[int, int] = {}
            for term in tokens:
                counts[vocab_set[term]] = counts.get(vocab_set[term], 0) + 1
            total = max(1, len(tokens))
            for col, count in counts.items():
                tf[row, col] = count / total
                if tf[row, col] > 0:
                    df[col] += 1
        idf = np.log((1.0 + n_docs) / (1.0 + df)) + 1.0
        self._tfidf = tf * idf

    # -- Retrieval ----------------------------------------------------------
    def query(self, question: str, top_k: int = 5) -> list[dict]:
        """Return the most relevant chunks for a question, best first."""
        if self._tfidf is None or not self.chunks:
            raise ToolError(
                "No documents are indexed yet. Use index_documents first."
            )
        import numpy as np  # noqa: PLC0415

        vec = self._vectorize(question)
        scores = self._tfidf @ vec
        order = np.argsort(scores)[::-1][: int(top_k)]
        results = [
            {
                "score": round(float(scores[i]), 4),
                "source": self.chunks[i]["source"],
                "text": self.chunks[i]["text"],
            }
            for i in order
            if scores[i] > 0
        ]
        return results

    def _vectorize(self, text: str):
        import numpy as np  # noqa: PLC0415

        vec = np.zeros(len(self.vocab), dtype=float)
        if not len(self.vocab):
            return vec
        counts: dict[int, int] = {}
        tokens = _tokens(text)
        lookup = {term: i for i, term in enumerate(self.vocab)}
        for term in tokens:
            col = lookup.get(term)
            if col is not None:
                counts[col] = counts.get(col, 0) + 1
        total = max(1, len(tokens))
        for col, count in counts.items():
            vec[col] = count / total
        return vec

    # -- Persistence --------------------------------------------------------
    def save(self, path: Path) -> None:
        payload = {
            "root_dir": str(self.root_dir) if self.root_dir else "",
            "chunks": self.chunks,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "RagIndex":
        index = cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        index.chunks = payload.get("chunks", [])
        if index.chunks:
            index._build()
        return index


# -- helpers ----------------------------------------------------------------

_SUPPORTED_EXTS = {".txt", ".md", ".py", ".json", ".csv", ".log", ".ini", ".yaml", ".yml", ".xml", ".html"}


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in _SUPPORTED_EXTS


def _safe_read(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""
    # Skip binary-ish content (many NUL bytes suggests non-text).
    if "\x00" in text:
        return ""
    return text


def _chunk_text(text: str, chunk_words: int = _CHUNK_WORDS, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    step = max(1, chunk_words - overlap)
    for start in range(0, len(words), step):
        chunks.append(" ".join(words[start : start + chunk_words]))
        if len(chunks) > 2000:
            break
    return chunks


def _tokens(text: str) -> list[str]:
    words = _WORD_RE.findall(text.lower())
    return [w for w in words if w not in _STOPWORDS]


# -- Shared index singleton -------------------------------------------------

_shared: RagIndex | None = None


def get_shared_index() -> RagIndex:
    """The app-wide RAG index, cached at the configured data folder."""
    global _shared
    if _shared is not None:
        return _shared
    from config import settings

    cache_dir = Path(settings.rag_index_dir) if settings.rag_index_dir else (
        settings.data_dir / "rag_index"
    )
    cache_file = cache_dir / _INDEX_CACHE_FILE
    if cache_file.exists():
        try:
            _shared = RagIndex.load(cache_file)
            return _shared
        except Exception as exc:  # noqa: BLE001 - a stale cache must not crash
            log.debug("Could not load RAG cache: %s", exc)
    _shared = RagIndex(root_dir=cache_dir)
    return _shared


def save_shared_index() -> None:
    index = get_shared_index()
    if not index.chunks:
        return
    from config import settings

    cache_dir = Path(settings.rag_index_dir) if settings.rag_index_dir else (
        settings.data_dir / "rag_index"
    )
    try:
        index.save(cache_dir / _INDEX_CACHE_FILE)
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not save RAG cache: %s", exc)


# -- Tools -------------------------------------------------------------------

class IndexDocumentsTool(Tool):
    name = "index_documents"
    description = (
        "Scan a folder (or a single text file) and build a local searchable "
        "index of its contents so JARVIS can answer questions from those "
        "documents. Text-based files only (.txt, .md, .py, .json, .csv, ...)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Folder (or file) path to index.",
            }
        },
        "required": ["path"],
    }

    def execute(self, args: dict) -> str:
        path = (args or {}).get("path", "").strip()
        if not path:
            raise ToolError("Please provide a path to index.")
        index = get_shared_index()
        result = index.index_folder(path)
        save_shared_index()
        return (
            f"Indexed {result['documents']} documents into {result['chunks']} "
            f"chunks. You can now use query_documents to ask about them."
        )


class QueryDocumentsTool(Tool):
    name = "query_documents"
    description = (
        "Search the locally indexed documents for the passages most relevant "
        "to the user's question and return them. Use AFTER index_documents. "
        "Quoting the retrieved text back is a normal (source-based) answer."
    )
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The thing the user wants to know about the docs.",
            },
            "top_k": {
                "type": "integer",
                "description": "How many passages to retrieve (default 5).",
            },
        },
        "required": ["question"],
    }

    def execute(self, args: dict) -> str:
        question = (args or {}).get("question", "").strip()
        if not question:
            raise ToolError("Please provide a question to search for.")
        top_k = int((args or {}).get("top_k", 5) or 5)
        try:
            results = get_shared_index().query(question, top_k=top_k)
        except ToolError:
            raise
        lines = [f"Relevant passages for: {question}"]
        for r in results:
            lines.append(f"\n[{r['source']}] (score {r['score']})")
            lines.append(r["text"])
        return "\n".join(lines)


class ForgetIndexTool(Tool):
    name = "forget_index"
    description = "Clear the local document index so queries start fresh."
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self, args: dict) -> str:
        index = get_shared_index()
        index.chunks = []
        index._tfidf = None
        save_shared_index()
        return "Document index cleared."


def register_rag_tools(registry) -> None:
    registry.register(IndexDocumentsTool())
    registry.register(QueryDocumentsTool())
    registry.register(ForgetIndexTool())