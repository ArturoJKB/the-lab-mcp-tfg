"""Kaggle dataset ingestion and web-context extraction.

Downloads a Kaggle dataset via ``kagglehub`` into the uploads workspace,
fetches the dataset page for its own documentation (description, tags), and
builds a **dataset context pack** that is saved alongside the CSV and indexed
into the context store so agents can ground proposals in it.

Network is used only in the ingestion path on explicit user action. The
sandbox is untouched. Tests mock both the kagglehub adapter and the page
fetch (zero network).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from thelab.context.contracts import IndexedEntry
from thelab.contracts import EventType, PrivacyLevel

from .datasets import get_uploads_root

_KAGGLE_PAGE_URL = "https://www.kaggle.com/datasets/{slug}"
_DESCRIPTION_RE = re.compile(r'"description":"((?:[^"\\]|\\.)*)"')
_KEYWORDS_RE = re.compile(r'"keywords":\[(.*?)\]')
_MAX_PAGE_BYTES = 2 * 1024 * 1024


class KaggleIngestError(ValueError):
    """Raised when a Kaggle dataset cannot be ingested."""


def _slug_to_stem(slug: str) -> str:
    """Return a filesystem-safe stem for a dataset slug (owner_dataset)."""
    parts = slug.strip("/").split("/")
    if len(parts) < 2:
        raise KaggleIngestError(f"invalid Kaggle dataset slug: {slug}")
    raw = "_".join(parts[-2:])
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")
    return stem or "kaggle_dataset"


def _profile_dataframe(df: Any) -> dict[str, Any]:
    """Build a JSON-safe profile of a downloaded DataFrame."""
    head = json.loads(df.head(5).to_json(orient="records"))
    describe: dict[str, Any] = {}
    numeric = df.select_dtypes(include="number")
    if not numeric.empty:
        describe = json.loads(numeric.describe().to_json())
    return {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "column_types": {c: str(t) for c, t in df.dtypes.items()},
        "head": head,
        "describe": describe,
    }


def ingest_kaggle_dataset(slug: str, file_path: str | None = None) -> dict[str, Any]:
    """Download a Kaggle dataset via kagglehub and save it as an upload CSV.

    Returns the dataset id, a local profile, and the kagglehub cache path.
    """
    if not slug or "/" not in slug:
        raise KaggleIngestError(f"invalid Kaggle dataset slug: {slug}")

    try:
        import kagglehub
        from kagglehub import KaggleDatasetAdapter
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise KaggleIngestError(f"kagglehub is not installed: {exc}") from exc

    try:
        df = kagglehub.load_dataset(
            KaggleDatasetAdapter.PANDAS,
            slug,
            file_path or "",
        )
        cache_path: Path | None = None
    except Exception:
        # Adapter path failed (e.g. ambiguous file); fall back to file download.
        cache_path = Path(kagglehub.dataset_download(slug))
        csvs = sorted(p for p in cache_path.rglob("*.csv") if p.is_file())
        if not csvs:
            raise KaggleIngestError(
                f"no CSV files found in Kaggle dataset '{slug}'"
            ) from None
        import pandas as pd

        df = pd.read_csv(csvs[0])

    stem = _slug_to_stem(slug)
    uploads = get_uploads_root()
    target = uploads / f"{stem}.csv"
    counter = 1
    while target.exists():
        target = uploads / f"{stem}_{counter}.csv"
        counter += 1
    df.to_csv(target, index=False)

    dataset_id = f"uploads/{target.name}"
    return {
        "dataset_id": dataset_id,
        "slug": slug,
        "profile": _profile_dataframe(df),
        "cache_path": str(cache_path) if cache_path else None,
    }


def _extract_markdown_description(html: str) -> str | None:
    """Return the longest decodable 'description' string embedded in page state."""
    best: str | None = None
    for match in _DESCRIPTION_RE.finditer(html):
        raw = f'"{match.group(1)}"'
        try:
            text = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(text, str) and (best is None or len(text) > len(best)):
            best = text
    return best


def _extract_keywords(html: str) -> list[str]:
    match = _KEYWORDS_RE.search(html)
    if not match:
        return []
    try:
        parsed = json.loads(f"[{match.group(1)}]")
    except json.JSONDecodeError:
        return []
    return [str(k) for k in parsed if isinstance(k, (str, int))][:12]


def fetch_kaggle_page_context(slug: str) -> dict[str, Any]:
    """Fetch the public Kaggle page and extract its self-description.

    Fail-soft: returns whatever could be extracted with ``errors`` notes.
    """
    url = _KAGGLE_PAGE_URL.format(slug=slug.strip("/"))
    context: dict[str, Any] = {
        "url": url,
        "description_markdown": None,
        "description_short": None,
        "keywords": [],
        "errors": [],
    }
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (TheLab local research agent)"},
            timeout=30.0,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        context["errors"].append(f"page fetch failed: {exc}")
        return context

    html = response.text[:_MAX_PAGE_BYTES]
    context["description_markdown"] = _extract_markdown_description(html)
    meta = re.search(r'<meta name="description" content="([^"]*)"', html)
    if meta:
        context["description_short"] = meta.group(1)
    context["keywords"] = _extract_keywords(html)
    return context


def _context_pack_path(dataset_id: str) -> Path | None:
    """Locate the context pack for an uploads dataset id, if any."""
    if not dataset_id.startswith("uploads/"):
        return None
    name = dataset_id.split("/", 1)[1]
    stem = Path(name).stem
    uploads = get_uploads_root()
    exact = uploads / f"{stem}.kaggle.json"
    if exact.is_file():
        return exact
    candidates = sorted(uploads.glob(f"{stem}*.kaggle.json"))
    return candidates[0] if candidates else None


def get_dataset_context(dataset_id: str) -> dict[str, Any] | None:
    """Return the stored Kaggle context pack for a dataset, if present."""
    path = _context_pack_path(dataset_id)
    if path is None:
        return None
    try:
        data: dict[str, Any] | None = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data


def build_context_pack(
    slug: str,
    ingestion: dict[str, Any],
    page_context: dict[str, Any],
) -> dict[str, Any]:
    """Merge web context + local profile, persist it, and index a context event."""
    pack = {
        "slug": slug,
        "dataset_id": ingestion["dataset_id"],
        "source_url": page_context.get("url"),
        "description_markdown": page_context.get("description_markdown"),
        "description_short": page_context.get("description_short"),
        "keywords": page_context.get("keywords", []),
        "fetch_errors": page_context.get("errors", []),
        "profile": ingestion["profile"],
        "built_at": datetime.now(UTC).isoformat(),
    }
    dataset_id = ingestion["dataset_id"]
    stem = Path(dataset_id.split("/", 1)[1]).stem
    pack_path = get_uploads_root() / f"{stem}.kaggle.json"
    pack_path.write_text(json.dumps(pack, indent=2), encoding="utf-8")

    _index_pack_event(slug, pack)
    return pack


def _index_pack_event(slug: str, pack: dict[str, Any]) -> None:
    """Index an ingestion summary event so context search surfaces it."""
    from thelab.context.redaction import redact
    from thelab.context.repository import ContextRepository

    description = pack.get("description_short") or (pack.get("description_markdown") or "")
    summary = (
        f"Kaggle dataset '{slug}' ingested as {pack['dataset_id']} "
        f"({pack['profile']['rows']} rows x {pack['profile']['columns']} cols). "
        f"{str(description)[:300]}"
    )
    entry = IndexedEntry(
        event_id=f"evt-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}",
        event_type=EventType.agent_session_summary,
        session_id=f"kaggle_ingest_{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}",
        run_id=None,
        tags=["kaggle", slug.split("/")[-1]],
        redacted_summary=redact(summary),
        related_artifact_refs=[],
        privacy_level=PrivacyLevel.internal,
        timestamp=datetime.now(UTC),
        content_hash=uuid.uuid4().hex,
    )
    db_path = Path(os.environ.get("THELAB_CONTEXT_DB", ".thelab/context/context.db"))
    repo = ContextRepository(db_path)
    repo.upsert(entry)
