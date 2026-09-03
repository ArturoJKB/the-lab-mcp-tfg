"""Tests for the single approval gate (P5.A3)."""

from __future__ import annotations

import pytest

from thelab.agents.approval import (
    ApprovalDenied,
    HumanApprovalRequired,
    auto_approve_enabled,
    ensure_executable,
    record_human_approval,
)
from thelab.agents.worker import ProposalStore, _generate_proposal_id


@pytest.fixture
def store(tmp_path):
    return ProposalStore(tmp_path / "proposals")


@pytest.fixture
def proposal_id(store: ProposalStore) -> str:
    pid = _generate_proposal_id()
    store.save(_make_proposal(pid))
    return pid


def _make_proposal(pid: str):
    from datetime import UTC, datetime

    from thelab.agents.worker import ExperimentProposal

    return ExperimentProposal(
        proposal_id=pid,
        goal="test",
        dataset="fixtures/iris.csv",
        target="species",
        created_at=datetime.now(UTC),
    )


def test_ensure_executable_requires_human_by_default(store: ProposalStore, proposal_id: str):
    with pytest.raises(HumanApprovalRequired) as excinfo:
        ensure_executable(store, proposal_id, principal="agent_mcp", allow_auto=False)
    assert proposal_id in str(excinfo.value)
    assert not store.is_approved(proposal_id)


def test_ensure_executable_auto_records_principal(store: ProposalStore, proposal_id: str):
    path = ensure_executable(store, proposal_id, principal="agent_mcp", allow_auto=True)
    assert path is not None and path.is_file()
    assert store.is_approved(proposal_id)
    import json

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["principal"] == "auto:agent_mcp"


def test_ensure_executable_idempotent_for_approved(store: ProposalStore, proposal_id: str):
    first = ensure_executable(store, proposal_id, principal="a", allow_auto=True)
    second = ensure_executable(store, proposal_id, principal="b", allow_auto=False)
    assert first == second


def test_rejected_proposal_can_never_execute(store: ProposalStore, proposal_id: str):
    store.reject(proposal_id, principal="human", reason="bad idea")
    with pytest.raises(ApprovalDenied):
        ensure_executable(store, proposal_id, principal="x", allow_auto=True)
    with pytest.raises(ApprovalDenied):
        record_human_approval(store, proposal_id, principal="human")


def test_record_human_approval_does_not_prefix_auto(store: ProposalStore, proposal_id: str):
    import json

    path = record_human_approval(store, proposal_id, principal="ui")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["principal"] == "ui"


def test_gate_on_missing_proposal_raises_required(store: ProposalStore):
    with pytest.raises(HumanApprovalRequired):
        ensure_executable(store, "prop-missing", principal="x", allow_auto=False)


def test_auto_approve_env_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("THELAB_AUTO_APPROVE", raising=False)
    assert auto_approve_enabled() is False
    monkeypatch.setenv("THELAB_AUTO_APPROVE", "1")
    assert auto_approve_enabled() is True
    monkeypatch.setenv("THELAB_AUTO_APPROVE", "0")
    assert auto_approve_enabled() is False
