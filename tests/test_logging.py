import json
import logging

from app.core.logging import JsonFormatter, RedactingFilter


def _record(msg, *args, **extra):
    record = logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_redacts_configured_secret_values():
    f = RedactingFilter(["my-meta-token-value"])
    record = _record("token is %s", "my-meta-token-value", url="x?t=my-meta-token-value")
    f.filter(record)
    assert "my-meta-token-value" not in record.getMessage()
    assert "my-meta-token-value" not in record.url


def test_redacts_token_patterns_even_if_unknown():
    f = RedactingFilter()
    record = _record(
        "GET https://graph.facebook.com/v25.0/me?access_token=EAAB123&appsecret_proof=abc "
        "Authorization: Bearer sk-xyz"
    )
    f.filter(record)
    message = record.getMessage()
    assert "EAAB123" not in message
    assert "abc" not in message.split("appsecret_proof=")[1]
    assert "sk-xyz" not in message
    assert message.count("[REDACTED]") == 3


def test_json_formatter_includes_extra_fields():
    record = _record("Posts saved", source_id=7, posts_saved=3)
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "Posts saved"
    assert payload["source_id"] == 7
    assert payload["posts_saved"] == 3
