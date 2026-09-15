import pytest

from app.services.relevance import match_relevance


@pytest.mark.parametrize(
    ("text", "location", "hazard"),
    [
        ("Heavy snowfall in Murree, tourists stranded", "Murree", "Snow"),
        ("Flash floods wreak havoc in Siran Valley, Balakot - Dawn", "Balakot", "Flood"),
        ("Glof, cloudburst ravage Chitral", "Chitral", "Cloudburst"),
        ("Landslides block Karakoram Highway near Chilas", "Karakoram Highway", "Landslide"),
        ("Bridge washed away in Neelum valley", "Neelum", "Bridge"),
        ("Tourists evacuated from Naran after heavy rain", "Naran", "Stranded/Rescue"),
        ("مری میں شدید برفباری، سڑکیں بند", "Murree", "Snow"),
        ("گلگت بلتستان میں سیلاب سے پل بہہ گیا", "Gilgit-Baltistan", "Flood"),
        ("سوات میں لینڈ سلائیڈنگ", "Swat", "Landslide"),
    ],
)
def test_relevant_northern_hazard_news(text, location, hazard):
    result = match_relevance(text)
    assert result.relevant
    assert location in result.locations
    assert hazard in result.hazards


@pytest.mark.parametrize(
    "text",
    [
        "PM chairs federal cabinet meeting in Islamabad",
        "Gilgit cricket team wins final",  # location without hazard
        "Heavy rain lashes Karachi",  # hazard without northern location
        "امریکہ میں برفباری",  # "مری" inside "امریکہ" must not match
        "Floods in Bahrain",  # "rain" inside "Bahrain" must not match
        "Training camp opens in Lahore",
        "بارش کی وجہ سے پرواز میں دیر",  # "دیر" means delay, not Dir district
    ],
)
def test_irrelevant_news(text):
    assert not match_relevance(text).relevant


def test_arabic_letter_variants_are_folded():
    # Arabic yeh (ي) and kaf (ك) instead of Urdu ی / ک
    assert "Murree" in match_relevance("مري ميں برفباری").locations


def test_prefix_variants():
    assert "Stranded/Rescue" in match_relevance("Families evacuating Kalam").hazards
    assert "Stranded/Rescue" in match_relevance("ناران میں سیاح پھنس گئے").hazards


def test_case_insensitive_and_multiword():
    result = match_relevance("SNOWFALL at nathia   gali")
    assert result.locations == ("Galiyat",)
    assert result.hazards == ("Snow",)
