import pytest

from app.services.relevance import match_relevance, strip_publisher_suffix


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Snowfall Transforms Khunjerab Border Into Snowy Wonderland - Chitral Today",
            "Snowfall Transforms Khunjerab Border Into Snowy Wonderland",
        ),
        ("KKH blocked today | Dawn", "KKH blocked today"),
        ("Headline without outlet", "Headline without outlet"),
        (
            "Glof hits Hunza - Pamir Times\nsummary - keeps dashes",
            "Glof hits Hunza\nsummary - keeps dashes",
        ),
    ],
)
def test_strip_publisher_suffix(text, expected):
    assert strip_publisher_suffix(text) == expected


def test_outlet_name_is_not_a_location():
    headline = "Snowfall Transforms Khunjerab Border Into Snowy Wonderland - Chitral Today"
    assert "Chitral" in match_relevance(headline).locations  # the bug being prevented
    assert match_relevance(strip_publisher_suffix(headline)).locations == ("Khunjerab",)
