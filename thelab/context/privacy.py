"""Privacy-level policy for the local context store.

This module defines the agent-safe privacy subset and a documented,
conservative mapping from the existing ``/log`` privacy object to the
stored ``PrivacyLevel``.
"""

from __future__ import annotations

from typing import Any

from thelab.contracts import PrivacyLevel

# Privacy levels that are safe to return to a future agent/Context MCP client
# by default. ``restricted`` and ``secret`` require an explicit override.
AGENT_SAFE_PRIVACY_LEVELS: tuple[PrivacyLevel, ...] = (
    PrivacyLevel.public,
    PrivacyLevel.internal,
)


def normalize_log_privacy(raw_privacy: Any) -> PrivacyLevel:
    """Map an explicit ``/log`` privacy object level to a stored ``PrivacyLevel``.

    Only ``privacy.level`` is honored. Supported values are the four canonical
    ``PrivacyLevel`` strings: ``public``, ``internal``, ``restricted``,
    ``secret``. Any missing, non-dict, or unrecognized value falls back to
    ``internal`` safely.

    Examples:
        >>> normalize_log_privacy({"level": "restricted"})
        <PrivacyLevel.restricted: 'restricted'>
        >>> normalize_log_privacy({"redactions_applied": True})
        <PrivacyLevel.internal: 'internal'>
    """
    if isinstance(raw_privacy, dict):
        level = raw_privacy.get("level")
        if isinstance(level, str):
            try:
                return PrivacyLevel(level)
            except ValueError:
                pass
    return PrivacyLevel.internal
