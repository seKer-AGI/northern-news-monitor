from app.services.normalization import normalize_text


def test_collapses_repeated_spaces_and_trims():
    assert normalize_text("  Looking   for\t an  AI   engineer.  ") == "Looking for an AI engineer."


def test_normalizes_line_breaks_and_limits_blank_lines():
    text = "Line one\r\nLine two\rLine three\n\n\n\n\nLine four"
    assert normalize_text(text) == "Line one\nLine two\nLine three\n\nLine four"


def test_trims_whitespace_around_each_line():
    assert normalize_text("  first  \n   second   ") == "first\nsecond"


def test_preserves_emoji_including_zwj_sequences():
    text = "Team 👩‍💻 needed 🙏🏽!"
    assert normalize_text(text) == text


def test_preserves_non_latin_unicode_and_punctuation():
    text = "کیا کوئی اچھا ڈویلپر جانتا ہے؟ — «yes»; ¿sí?"
    assert normalize_text(text) == text


def test_preserves_urls_by_default():
    assert (
        normalize_text("Apply: https://example.com/job?id=1")
        == "Apply: https://example.com/job?id=1"
    )


def test_optionally_removes_urls():
    assert (
        normalize_text("Apply at https://example.com/job now", remove_urls=True) == "Apply at now"
    )


def test_non_breaking_and_unicode_spaces_collapse():
    assert normalize_text("a  b　c") == "a b c"


def test_empty_values():
    assert normalize_text(None) == ""
    assert normalize_text("   \n\t ") == ""


def test_unicode_nfc_normalization_is_meaning_preserving():
    decomposed = "Café"
    assert normalize_text(decomposed) == "Café"
