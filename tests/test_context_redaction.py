
from thelab.context.redaction import redact, redact_dict


def test_redact_leaves_safe_text_unchanged():
    text = "Dataset validation completed successfully for iris.csv."
    assert redact(text) == text


def test_redact_api_key_sk():
    token = "sk-" + "abcdefghijklmnopqrstuvwxyz1234567890"
    text = f"Using key {token} for inference."
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
    token = "ghp_" + "secrettoken"
    text = "Environment: API_KEY=ak_live_12345, TOKEN=" + token
    result = redact(text)
    assert "ak_live_12345" not in result
    assert "ghp_" not in result


def test_redact_github_classic_token():
    token = "ghp_" + "abcdefghijklmnopqrstuvwxyz12"
    text = f"GitHub: {token} for CI"
    result = redact(text)
    assert "ghp_" not in result
    assert "[REDACTED]" in result


def test_redact_github_fine_grained_token():
    token = "github_pat_" + "11ABCDEF0_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcdef"
    text = f"GitHub: {token}"
    result = redact(text)
    assert "github_pat_" not in result
    assert "[REDACTED]" in result


def test_redact_github_oauth_token():
    token = "gho_" + "abcdefghijklmnopqrstuvwxyz12"
    text = f"OAuth: {token}"
    result = redact(text)
    assert "gho_" not in result
    assert "[REDACTED]" in result


def test_redact_google_api_key():
    token = "AIza" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    text = f"Maps API key {token}"
    result = redact(text)
    assert "AIza" not in result
    assert "[REDACTED]" in result


def test_redact_aws_access_key():
    token = "AKIA" + "IOSFODNN7EXAMPLE"
    text = f"AWS access key {token} in config"
    result = redact(text)
    assert "AKIA" not in result
    assert "[REDACTED]" in result


def test_redact_slack_tokens():
    token1 = "xox" + "b-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx"
    token2 = "xox" + "p-1234567890123-XYZ"
    text = f"Slack: {token1} and {token2}"
    result = redact(text)
    assert "xoxb-" not in result
    assert "xoxp-" not in result
    assert "[REDACTED]" in result


def test_redact_slack_app_and_user_tokens():
    token1 = "xox" + "a-1234567890123-abc"
    token2 = "xox" + "s-1234567890123-def"
    text = f"Tokens: {token1} {token2}"
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
