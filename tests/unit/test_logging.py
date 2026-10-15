from app.core.logging import REDACTED, redact_sensitive_fields


def test_sensitive_keys_are_redacted_at_any_depth() -> None:
    event = {
        "event": "login_attempt",
        "email": "ada@example.com",
        "password": "hunter2-hunter2",
        "headers": {"Authorization": "Bearer abc.def.ghi", "Accept": "application/json"},
        "attempts": [{"access_token": "abc"}],
        "jwt_secret_key": "s3cret",
    }

    result = redact_sensitive_fields(None, "info", event)

    assert result["password"] == REDACTED
    assert result["headers"]["Authorization"] == REDACTED
    assert result["attempts"][0]["access_token"] == REDACTED
    assert result["jwt_secret_key"] == REDACTED
    # Non-sensitive fields are left untouched.
    assert result["email"] == "ada@example.com"
    assert result["headers"]["Accept"] == "application/json"
    assert result["event"] == "login_attempt"
