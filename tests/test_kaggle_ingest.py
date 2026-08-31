"""Tests for Kaggle ingestion and dataset context packs (P3.5). Network-free."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from thelab.ide.kaggle_api import (
    _extract_keywords,
    _extract_markdown_description,
    build_context_pack,
    fetch_kaggle_page_context,
    ingest_kaggle_dataset,
)

PAGE_HTML = """
<html><head>
<meta name="description" content="EDA of e-commerce sales data.">
<script type="application/ld+json">{"@type":"Dataset","description":"short"}</script>
</head><body>
<script>window.__NEXT_DATA__ = {"description":"# E-Commerce Sales\\n\\nCleaned transactions for EDA.","keywords":["business","sales","eda"]};</script>
</body></html>
"""


@pytest.fixture
def kaggle_env(tmp_path: Path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setenv("THELAB_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("THELAB_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("THELAB_CONTEXT_DB", str(tmp_path / "context" / "context.db"))
    return uploads


def _fake_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "sales": [100.5, 250.0, 80.25],
            "category": ["A", "B", "A"],
        }
    )


def _patch_kagglehub(monkeypatch, df: pd.DataFrame) -> None:
    import kagglehub
    from kagglehub import KaggleDatasetAdapter

    calls: dict[str, tuple] = {}

    def fake_load(adapter, slug, file_path, **kwargs):
        calls["adapter"] = adapter
        calls["slug"] = slug
        calls["file_path"] = file_path
        return df.copy()

    monkeypatch.setattr(kagglehub, "load_dataset", fake_load)
    return calls, (KaggleDatasetAdapter.PANDAS)


def test_ingest_kaggle_dataset_saves_upload(kaggle_env, monkeypatch):
    calls, pandas_adapter = _patch_kagglehub(monkeypatch, _fake_df())
    result = ingest_kaggle_dataset("erfan4524/e-commerce-sales", file_path="sales.csv")

    assert result["dataset_id"] == "uploads/erfan4524_e-commerce-sales.csv"
    assert (kaggle_env / "erfan4524_e-commerce-sales.csv").is_file()
    assert result["profile"]["rows"] == 3
    assert result["profile"]["columns"] == 3
    assert calls["adapter"] == pandas_adapter
    assert calls["slug"] == "erfan4524/e-commerce-sales"


def test_ingest_rejects_bad_slug(kaggle_env):
    with pytest.raises(ValueError):
        ingest_kaggle_dataset("not-a-slug")


def test_extract_markdown_description_picks_longest():
    assert _extract_markdown_description(PAGE_HTML) == "# E-Commerce Sales\n\nCleaned transactions for EDA."


def test_extract_keywords():
    assert _extract_keywords(PAGE_HTML) == ["business", "sales", "eda"]


def test_fetch_page_context_parses_fixture(kaggle_env, monkeypatch):
    import httpx

    def fake_get(url, **kwargs):
        return SimpleNamespace(text=PAGE_HTML, raise_for_status=lambda: None)

    monkeypatch.setattr(httpx, "get", fake_get)
    context = fetch_kaggle_page_context("erfan4524/e-commerce-sales")
    assert context["errors"] == []
    assert context["description_markdown"].startswith("# E-Commerce Sales")
    assert context["keywords"] == ["business", "sales", "eda"]


def test_fetch_page_context_fail_soft(kaggle_env, monkeypatch):
    import httpx

    def fake_get(url, **kwargs):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "get", fake_get)
    context = fetch_kaggle_page_context("erfan4524/e-commerce-sales")
    assert context["description_markdown"] is None
    assert context["errors"]


def test_context_pack_built_and_indexed(kaggle_env, monkeypatch):
    calls, _ = _patch_kagglehub(monkeypatch, _fake_df())
    ingestion = ingest_kaggle_dataset("erfan4524/e-commerce-sales")
    page_context = {"url": "https://www.kaggle.com/datasets/x", "description_markdown": "# Sales",
                    "description_short": "EDA of sales", "keywords": ["sales"], "errors": []}
    pack = build_context_pack("erfan4524/e-commerce-sales", ingestion, page_context)

    assert pack["profile"]["rows"] == 3
    pack_file = kaggle_env / "erfan4524_e-commerce-sales.kaggle.json"
    assert pack_file.is_file()
    stored = json.loads(pack_file.read_text(encoding="utf-8"))
    assert stored["description_short"] == "EDA of sales"


def test_get_dataset_context_tool_returns_pack(kaggle_env, monkeypatch):
    _patch_kagglehub(monkeypatch, _fake_df())
    ingestion = ingest_kaggle_dataset("erfan4524/e-commerce-sales")
    page_context = {"url": "u", "description_markdown": "# Sales", "description_short": None,
                    "keywords": [], "errors": []}
    build_context_pack("erfan4524/e-commerce-sales", ingestion, page_context)

    result = asyncio_run_tool("uploads/erfan4524_e-commerce-sales.csv")
    assert result["ok"] is True
    data = result["data"]
    assert isinstance(data, dict) or isinstance(data, str)


def asyncio_run_tool(dataset_id: str):
    import asyncio

    from thelab.agents.chat import _build_tools

    _, registry = _build_tools(dataset_id)
    return asyncio.run(registry["get_dataset_context"]({}))


def test_get_dataset_context_tool_local_dataset(kaggle_env):
    result = asyncio_run_tool("fixtures/iris.csv")
    assert result["ok"] is True
    assert "No external context pack" in str(result["data"])
