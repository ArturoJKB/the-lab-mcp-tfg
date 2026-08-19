
from thelab.context.redaction import redact, redact_dict


def test_redact_leaves_safe_text_unchanged():
    text = "Dataset validation completed successfully for iris.csv."
    assert redact(text) == text


def test_redact_api_key_sk():
    text = "Using key sk-abcdefghijklmnopqrstuvwxyz1234567890 for inference."
    assert "sk-" not in redact(text)
    assert "[REDACTED]" in redact(text)


def test_redact_bearer_token():
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    result = redact(text)
    assert "eyJhb" not in result
    assert "Bearer [REDACTED]" in result


def test_redact_password_assignment():
    text = "Config: password=supersecret123 and user=admin"
    result = redact(text)
    assert "supersecret123" not in result
    assert "user=admin" in result


def test_redact_private_key_block():
    text = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC...\n-----END PRIVATE KEY-----"
    result = redact(text)
    assert "BEGIN PRIVATE KEY" not in result
    assert "MIIEvQ" not in result
    assert "[REDACTED]" in result


def test_redact_env_secret_pattern():
    text = "Environment: API_KEY=ak_live_12345, TOKEN=ghp_secrettoken"
    result = redact(text)
    assert "ak_live_12345" not in result
    assert "ghp_secrettoken" not in result


def test_redact_github_classic_token():
    text = "GitHub: ghp_abcdefghijklmnopqrstuvwxyz12 for CI"
    result = redact(text)
    assert "ghp_" not in result
    assert "[REDACTED]" in result


def test_redact_github_fine_grained_token():
    text = "GitHub: github_pat_11ABCDEF0_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcdef"
    result = redact(text)
    assert "github_pat_" not in result
    assert "[REDACTED]" in result


def test_redact_github_oauth_token():
    text = "OAuth: gho_abcdefghijklmnopqrstuvwxyz12"
    result = redact(text)
    assert "gho_" not in result
    assert "[REDACTED]" in result


def test_redact_google_api_key():
    text = "Maps API key AIzaSyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    result = redact(text)
    assert "AIza" not in result
    assert "[REDACTED]" in result


def test_redact_aws_access_key():
    text = "AWS access key AKIAIOSFODNN7EXAMPLE in config"
    result = redact(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in result
    assert "[REDACTED]" in result


def test_redact_slack_tokens():
    text = "Slack: xoxb-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx and xoxp-1234567890123-XYZ"
    result = redact(text)
    assert "xoxb-" not in result
    assert "xoxp-" not in result
    assert "[REDACTED]" in result


def test_redact_slack_app_and_user_tokens():
    text = "Tokens: xoxa-1234567890123-abc xoxs-1234567890123-def"
    result = redact(text)
    assert "xoxa-" not in result
    assert "xoxs-" not in result
    assert "[REDACTED]" in result


def test_redact_dict_redacts_string_values():
    data = {
        "message": "password=secret",
        "count": 42,
        "nested": {"password": "kept"},
    }
    result = redact_dict(data)
    assert "secret" not in result["message"]
    assert result["count"] == 42
    assert result["nested"]["password"] == "kept"


def test_redact_empty_string():
    assert redact("") == ""
