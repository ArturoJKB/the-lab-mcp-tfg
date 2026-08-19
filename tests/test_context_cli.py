import json
import os
import subprocess
import sys
from pathlib import Path

from thelab.context.cli import main as context_main


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def test_cli_index_creates_database(tmp_path, monkeypatch):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            {
                "event_id": "evt-1",
                "event_type": "system",
                "session_id": "session-1",
                "redacted_summary": "Run started",
                "timestamp": "2026-08-09T12:00:00+00:00",
            },
        ],
    )
    db = tmp_path / "context.db"

    monkeypatch.chdir(tmp_path)
    rc = context_main(["index", "--source", str(source), "--db", str(db)])
    assert rc == 0
    assert db.exists()


def test_cli_search_returns_results(tmp_path, monkeypatch, capsys):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            {
                "event_id": "evt-1",
                "event_type": "system",
                "session_id": "session-1",
                "redacted_summary": "Run started",
                "timestamp": "2026-08-09T12:00:00+00:00",
            },
            {
                "event_id": "evt-2",
                "event_type": "validation",
                "session_id": "session-1",
                "redacted_summary": "Validation error occurred",
                "timestamp": "2026-08-09T12:01:00+00:00",
            },
        ],
    )
    db = tmp_path / "context.db"

    monkeypatch.chdir(tmp_path)
    context_main(["index", "--source", str(source), "--db", str(db)])

    captured = capsys.readouterr()
    capsys.readouterr()  # clear

    rc = context_main(["search", "error", "--db", str(db)])
    captured = capsys.readouterr()
    assert rc == 0
    result = json.loads(captured.out)
    assert result["ok"] is True
    assert result["count"] == 1
    assert result["data"][0]["event_id"] == "evt-2"


def test_cli_show_existing_entry(tmp_path, monkeypatch, capsys):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            {
                "event_id": "evt-1",
                "event_type": "system",
                "session_id": "session-1",
                "redacted_summary": "Run started",
                "timestamp": "2026-08-09T12:00:00+00:00",
            },
        ],
    )
    db = tmp_path / "context.db"

    monkeypatch.chdir(tmp_path)
    context_main(["index", "--source", str(source), "--db", str(db)])
    capsys.readouterr()

    rc = context_main(["show", "evt-1", "--db", str(db)])
    captured = capsys.readouterr()
    assert rc == 0
    result = json.loads(captured.out)
    assert result["ok"] is True
    assert result["data"]["event_id"] == "evt-1"


def test_cli_show_missing_entry(tmp_path, monkeypatch, capsys):
    db = tmp_path / "context.db"
    monkeypatch.chdir(tmp_path)
    rc = context_main(["show", "missing", "--db", str(db)])
    captured = capsys.readouterr()
    assert rc == 1
    result = json.loads(captured.out)
    assert result["ok"] is False


def test_cli_search_with_run_id_filter(tmp_path, monkeypatch, capsys):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            {
                "event_id": "evt-1",
                "event_type": "system",
                "session_id": "session-1",
                "run_id": "run-a",
                "redacted_summary": "Run started",
                "timestamp": "2026-08-09T12:00:00+00:00",
            },
            {
                "event_id": "evt-2",
                "event_type": "system",
                "session_id": "session-1",
                "run_id": "run-b",
                "redacted_summary": "Run started",
                "timestamp": "2026-08-09T12:00:00+00:00",
            },
        ],
    )
    db = tmp_path / "context.db"

    monkeypatch.chdir(tmp_path)
    context_main(["index", "--source", str(source), "--db", str(db)])
    capsys.readouterr()

    rc = context_main(["search", "--run-id", "run-a", "--db", str(db)])
    captured = capsys.readouterr()
    assert rc == 0
    result = json.loads(captured.out)
    assert result["count"] == 1
    assert result["data"][0]["run_id"] == "run-a"


def test_thelab_context_invocation_via_subprocess(tmp_path):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            {
                "event_id": "evt-1",
                "event_type": "system",
                "session_id": "session-1",
                "redacted_summary": "Run started",
                "timestamp": "2026-08-09T12:00:00+00:00",
            },
        ],
    )
    db = tmp_path / "context.db"

    env = dict(os.environ)
    env["THELAB_CONTEXT_DB"] = str(db)
    proc = subprocess.run(
        [sys.executable, "-m", "thelab", "context", "index", "--source", str(source)],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(proc.stdout)
    assert result["ok"] is True
    assert result["indexed"] == 1


def test_cli_index_returns_ok_false_on_malformed_records(tmp_path, monkeypatch, capsys):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            {"event_id": "evt-ok", "event_type": "system", "session_id": "s1", "redacted_summary": "Good", "timestamp": "2026-08-09T12:00:00+00:00"},
            {"valid": True},
        ],
    )
    db = tmp_path / "context.db"

    monkeypatch.chdir(tmp_path)
    rc = context_main(["index", "--source", str(source), "--db", str(db)])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert rc == 1
    assert result["ok"] is False
    assert result["indexed"] == 1
    assert result["skipped"] == 1
    assert len(result["errors"]) == 1


def test_cli_search_does_not_create_missing_database(tmp_path, monkeypatch, capsys):
    db = tmp_path / "context.db"
    monkeypatch.chdir(tmp_path)

    rc = context_main(["search", "hello", "--db", str(db)])
    captured = capsys.readouterr()

    assert rc == 0
    assert not db.exists()
    result = json.loads(captured.out)
    assert result["ok"] is True
    assert result["count"] == 0


def test_cli_search_is_read_only_byte_for_byte(tmp_path, monkeypatch, capsys):
    import hashlib

    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            {
                "event_id": "evt-1",
                "event_type": "system",
                "session_id": "session-1",
                "redacted_summary": "Run started",
                "timestamp": "2026-08-09T12:00:00+00:00",
            },
        ],
    )
    db = tmp_path / "context.db"
    monkeypatch.chdir(tmp_path)
    context_main(["index", "--source", str(source), "--db", str(db)])
    capsys.readouterr()

    before = hashlib.sha256(db.read_bytes()).hexdigest()
    rc = context_main(["search", "Run", "--db", str(db)])
    context_main(["show", "evt-1", "--db", str(db)])
    after = hashlib.sha256(db.read_bytes()).hexdigest()

    assert rc == 0
    assert before == after


def test_cli_search_respects_privacy_filter(tmp_path, monkeypatch, capsys):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            {
                "event_id": "evt-public",
                "event_type": "system",
                "session_id": "session-1",
                "redacted_summary": "Public event",
                "privacy_level": "public",
                "timestamp": "2026-08-09T12:00:00+00:00",
            },
            {
                "event_id": "evt-internal",
                "event_type": "system",
                "session_id": "session-1",
                "redacted_summary": "Internal event",
                "privacy_level": "internal",
                "timestamp": "2026-08-09T12:01:00+00:00",
            },
            {
                "event_id": "evt-restricted",
                "event_type": "system",
                "session_id": "session-1",
                "redacted_summary": "Restricted event",
                "privacy_level": "restricted",
                "timestamp": "2026-08-09T12:02:00+00:00",
            },
            {
                "event_id": "evt-secret",
                "event_type": "system",
                "session_id": "session-1",
                "redacted_summary": "Secret event",
                "privacy_level": "secret",
                "timestamp": "2026-08-09T12:03:00+00:00",
            },
        ],
    )
    db = tmp_path / "context.db"
    monkeypatch.chdir(tmp_path)
    context_main(["index", "--source", str(source), "--db", str(db)])
    capsys.readouterr()

    rc = context_main(["search", "event", "--db", str(db)])
    captured = capsys.readouterr()
    assert rc == 0
    result = json.loads(captured.out)
    event_ids = {e["event_id"] for e in result["data"]}
    assert event_ids == {"evt-public", "evt-internal"}

    rc = context_main(["show", "evt-restricted", "--db", str(db)])
    captured = capsys.readouterr()
    assert rc == 1
    result = json.loads(captured.out)
    assert result["ok"] is False


def test_cli_search_rejects_invalid_limit_and_query(tmp_path, monkeypatch, capsys):
    source = tmp_path / "agent-events.jsonl"
    _write_jsonl(
        source,
        [
            {
                "event_id": "evt-1",
                "event_type": "system",
                "session_id": "session-1",
                "redacted_summary": "Run started",
                "timestamp": "2026-08-09T12:00:00+00:00",
            },
        ],
    )
    db = tmp_path / "context.db"
    monkeypatch.chdir(tmp_path)
    context_main(["index", "--source", str(source), "--db", str(db)])
    capsys.readouterr()

    rc = context_main(["search", "--limit", "0", "--db", str(db)])
    captured = capsys.readouterr()
    assert rc == 1
    assert json.loads(captured.out)["ok"] is False

    rc = context_main(["search", "x" * 201, "--db", str(db)])
    captured = capsys.readouterr()
    assert rc == 1
    assert json.loads(captured.out)["ok"] is False


def test_context_cli_does_not_import_ml_runtime():
    """The `context` CLI branch must not pull in sklearn or pandas."""
    script = (
        "import sys\n"
        "from thelab.cli import main\n"
        "try:\n"
        "    main(['context', '--help'])\n"
        "except SystemExit as exc:\n"
        "    rc = exc.code if isinstance(exc.code, int) else 0\n"
        "print('pandas' in sys.modules or 'sklearn' in sys.modules)\n"
        "raise SystemExit(rc)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    last_line = proc.stdout.strip().splitlines()[-1]
    assert last_line == "False"
