"""Relevance filter for northern-areas weather and hazard news (English + Urdu).

A news item is relevant when it mentions at least one northern location AND at
least one weather/hazard term. Matching respects word boundaries in both scripts
(so "مری" does not match inside "امریکہ", and "rain" does not match "Bahrain").
A trailing ``*`` on a variant means prefix match (e.g. ``evacuat*``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LOCATIONS: dict[str, tuple[str, ...]] = {
    "Murree": ("murree", "مری"),
    "Galiyat": ("galiyat", "nathia gali", "nathiagali", "ayubia", "گلیات", "نتھیا گلی", "ایوبیہ"),
    "Abbottabad": ("abbottabad", "ایبٹ آباد"),
    "Mansehra": ("mansehra", "مانسہرہ"),
    "Balakot": ("balakot", "بالاکوٹ"),
    "Kaghan": ("kaghan", "کاغان"),
    "Naran": ("naran", "ناران"),
    "Babusar": ("babusar", "بابوسر"),
    "Shogran": ("shogran", "شوگران"),
    "Neelum": ("neelum", "نیلم"),
    "Muzaffarabad": ("muzaffarabad", "مظفرآباد", "مظفر آباد"),
    "Azad Kashmir": ("azad kashmir", "ajk", "آزاد کشمیر"),
    "Swat": ("swat", "سوات"),
    "Kalam": ("kalam", "کالام"),
    "Malam Jabba": ("malam jabba", "مالم جبہ"),
    "Shangla": ("shangla", "شانگلہ"),
    "Dir": ("upper dir", "lower dir", "اپر دیر", "لوئر دیر"),
    "Chitral": ("chitral", "چترال"),
    "Kohistan": ("kohistan", "کوہستان"),
    "Besham": ("besham", "بشام"),
    "Dasu": ("dasu", "داسو"),
    "Chilas": ("chilas", "چلاس"),
    "Diamer": ("diamer", "دیامر"),
    "Gilgit": ("gilgit", "گلگت"),
    "Gilgit-Baltistan": ("gilgit-baltistan", "gilgit baltistan", "گلگت بلتستان"),
    "Hunza": ("hunza", "karimabad", "attabad", "ہنزہ", "کریم آباد", "عطا آباد"),
    "Nagar": ("nagar valley", "نگر ویلی"),
    "Khunjerab": ("khunjerab", "sost", "خنجراب", "سوست"),
    "Skardu": ("skardu", "اسکردو", "سکردو"),
    "Shigar": ("shigar", "شگر"),
    "Khaplu": ("khaplu", "ghanche", "خپلو", "گانچھے"),
    "Deosai": ("deosai", "دیوسائی"),
    "Astore": ("astore", "استور"),
    "Ghizer": ("ghizer", "gupis", "غذر", "گوپس"),
    "Fairy Meadows": ("fairy meadows", "فیری میڈوز"),
    "Karakoram Highway": ("karakoram highway", "kkh", "شاہراہ قراقرم", "قراقرم ہائی وے"),
    "Batagram": ("batagram", "بٹگرام"),
    "Northern Areas": ("northern areas", "شمالی علاقہ جات", "شمالی علاقوں"),
}

HAZARDS: dict[str, tuple[str, ...]] = {
    "Snow": ("snow", "snowfall", "snowstorm", "blizzard", "برفباری", "برف باری", "برف"),
    "Rain": ("rain", "rains", "rainfall", "downpour", "monsoon", "بارش", "بارشیں", "مون سون"),
    "Flood": (
        "flood",
        "floods",
        "flooding",
        "flash flood",
        "inundat*",
        "سیلاب",
        "سیلابی",
        "طغیانی",
    ),
    "Landslide": (
        "landslide",
        "landslides",
        "landsliding",
        "mudslide",
        "rockslide",
        "لینڈ سلائیڈنگ",
        "لینڈسلائیڈنگ",
        "لینڈ سلائیڈ",
        "مٹی کے تودے",
        "پتھر گرنے",
    ),
    "Avalanche": ("avalanche", "avalanches", "برفانی تودہ", "برفانی تودے"),
    "Glacier/GLOF": ("glacier", "glaciers", "glof", "glacial lake", "گلیشیئر", "گلیشیر"),
    "Cloudburst": ("cloudburst", "cloud burst", "کلاؤڈ برسٹ"),
    "Storm": (
        "storm",
        "thunderstorm",
        "hailstorm",
        "windstorm",
        "strong wind*",
        "gust*",
        "طوفان",
        "آندھی",
        "ژالہ باری",
    ),
    "Earthquake": ("earthquake", "tremor", "tremors", "زلزلہ", "زلزلے"),
    "Road blocked": (
        "road closed",
        "road blocked",
        "roads blocked",
        "roads closed",
        "highway closed",
        "highway blocked",
        "traffic suspended",
        "سڑک بند",
        "سڑکیں بند",
        "شاہراہ بند",
        "راستے بند",
        "ٹریفک معطل",
    ),
    "Bridge": ("bridge", "bridges", "washed away", "پل", "بہہ گیا", "بہہ گئے"),
    "Stranded/Rescue": (
        "stranded",
        "trapped",
        "rescue",
        "rescued",
        "evacuat*",
        "پھنس*",
        "ریسکیو",
        "امدادی",
    ),
    "Weather": (
        "weather",
        "cold wave",
        "temperature",
        "met office",
        "pmd",
        "ndma",
        "pdma",
        "موسم",
        "محکمہ موسمیات",
        "این ڈی ایم اے",
        "پی ڈی ایم اے",
        "درجہ حرارت",
    ),
}

# Arabic-script code points that look identical but differ between Arabic and Urdu keyboards.
_URDU_FOLD = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ه": "ہ", "‌": "", "‍": ""})


def _compile(variants: tuple[str, ...]) -> re.Pattern[str]:
    parts = []
    for variant in variants:
        prefix = variant.endswith("*")
        core = re.escape(variant.rstrip("*").translate(_URDU_FOLD)).replace(r"\ ", r"\s+")
        parts.append(rf"(?<!\w){core}" + ("" if prefix else r"(?!\w)"))
    return re.compile("|".join(parts), re.IGNORECASE)


_LOCATION_PATTERNS = {name: _compile(v) for name, v in LOCATIONS.items()}
_HAZARD_PATTERNS = {name: _compile(v) for name, v in HAZARDS.items()}


_PUBLISHER_SUFFIX_RE = re.compile(r"\s+[-–|]\s+[^-–|\n]{2,60}$")


def strip_publisher_suffix(text: str) -> str:
    """Drop Google News' trailing ``" - Publisher"`` from the headline line.

    Otherwise an outlet name such as "Chitral Today" is mistaken for a location.
    """
    headline, sep, rest = text.partition("\n")
    return _PUBLISHER_SUFFIX_RE.sub("", headline) + sep + rest


@dataclass(frozen=True, slots=True)
class Relevance:
    locations: tuple[str, ...]
    hazards: tuple[str, ...]

    @property
    def relevant(self) -> bool:
        return bool(self.locations and self.hazards)


def match_relevance(text: str) -> Relevance:
    folded = text.translate(_URDU_FOLD)
    return Relevance(
        locations=tuple(n for n, p in _LOCATION_PATTERNS.items() if p.search(folded)),
        hazards=tuple(n for n, p in _HAZARD_PATTERNS.items() if p.search(folded)),
    )
