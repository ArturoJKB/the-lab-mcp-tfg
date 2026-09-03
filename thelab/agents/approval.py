"""Single approval chokepoint for proposal execution.

Every path that turns a proposal into training must go through
:func:`ensure_executable` — there is no other approval writer in agentic code
paths. Policy:

- **Agent-initiated flows** (MCP clients such as ``agent_mcp``): require
  explicit human approval (UI approve endpoint or ``thelab proposals
  approve``). Auto-approval only behind ``THELAB_AUTO_APPROVE=1``.
- **User-initiated flows** (CLI, UI experiment runs): the initiator's mandate
  allows auto-approval, recorded as ``auto:<principal>`` so the audit trail
  shows who initiated and that no human saw the specific proposal.
- A rejected proposal can never be executed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from thelab.agents.worker import ProposalStore

AUTO_APPROVE_ENV = "THELAB_AUTO_APPROVE"

_APPROVE_HINT = (
    "approve via the UI (POST /proposals/{id}/approve), "
    "'thelab proposals approve <id>', or set THELAB_AUTO_APPROVE=1"
)


class ApprovalDenied(RuntimeError):
    """The proposal was explicitly rejected; execution is forbidden."""


class HumanApprovalRequired(RuntimeError):
    """A proposal is not approved and auto-approval is disabled."""

    def __init__(self, proposal_id: str, hint: str = _APPROVE_HINT):
        self.proposal_id = proposal_id
        self.hint = hint.format(id=proposal_id)
        super().__init__(f"proposal '{proposal_id}' is not approved; {self.hint}")


def auto_approve_enabled() -> bool:
    """Return True when auto-approval is explicitly enabled via env."""
    return os.environ.get(AUTO_APPROVE_ENV) == "1"


def ensure_executable(
    store: ProposalStore,
    proposal_id: str,
    *,
    principal: str,
    allow_auto: bool = False,
) -> Path:
    """Approve-or-verify *proposal_id* through the gate.

    Returns the approval record path (existing or newly written). Raises
    :class:`ApprovalDenied` for rejected proposals and
    :class:`HumanApprovalRequired` when unapproved with auto-approval off.
    """
    if store.is_rejected(proposal_id):
        raise ApprovalDenied(f"proposal '{proposal_id}' was rejected; execution is forbidden")
    if store.is_approved(proposal_id):
        return store.approval_path(proposal_id)
    if allow_auto:
        return store.approve(proposal_id, principal=f"auto:{principal}")
    raise HumanApprovalRequired(proposal_id)


def record_human_approval(
    store: ProposalStore,
    proposal_id: str,
    *,
    principal: str,
) -> Path:
    """Record an explicit human approval (UI click, CLI command) for *proposal_id*.

    Idempotent for already-approved proposals; a rejected proposal raises
    :class:`ApprovalDenied` — rejection is final until a new proposal is made.
    """
    if store.is_rejected(proposal_id):
        raise ApprovalDenied(f"proposal '{proposal_id}' was rejected; execution is forbidden")
    if store.is_approved(proposal_id):
        return store.approval_path(proposal_id)
    return store.approve(proposal_id, principal=principal)
