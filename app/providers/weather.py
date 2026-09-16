"""Open-Meteo forecast provider: turns severe forecasts into alert "posts".

Source type ``weather``; ``source_identifier`` is a slug from
:data:`NORTHERN_LOCATIONS`. One API call per location per run.

Open-Meteo's free API is for non-commercial use (CC BY 4.0 attribution;
limits 600/min, 5,000/hour, 10,000/day). Commercial use needs a paid plan.
Coordinates are approximate town/pass centres.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime

from app.providers.base import (
    DataProvider,
    ProviderError,
    ProviderErrorCode,
    ProviderHealth,
    ProviderPost,
    SourceRef,
    SourceValidation,
)
from app.providers.http_fetch import HttpFetcher

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
THUNDERSTORM_CODES = frozenset({95, 96, 99})


@dataclass(frozen=True, slots=True)
class Location:
    slug: str
    name: str
    name_ur: str
    latitude: float
    longitude: float


NORTHERN_LOCATIONS: dict[str, Location] = {
    loc.slug: loc
    for loc in (
        Location("murree", "Murree", "مری", 33.907, 73.394),
        Location("nathia-gali", "Nathia Gali (Galiyat)", "نتھیا گلی", 34.073, 73.381),
        Location("naran", "Naran (Kaghan)", "ناران", 34.909, 73.651),
        Location("babusar-top", "Babusar Top", "بابوسر ٹاپ", 35.148, 74.046),
        Location("kalam", "Kalam (Swat)", "کالام", 35.489, 72.585),
        Location("malam-jabba", "Malam Jabba (Swat)", "مالم جبہ", 34.799, 72.573),
        Location("chitral", "Chitral", "چترال", 35.851, 71.786),
        Location("chilas", "Chilas", "چلاس", 35.420, 74.094),
        Location("gilgit", "Gilgit", "گلگت", 35.920, 74.308),
        Location("hunza", "Hunza (Karimabad)", "ہنزہ", 36.317, 74.667),
        Location("khunjerab", "Khunjerab Pass", "خنجراب", 36.850, 75.428),
        Location("skardu", "Skardu", "اسکردو", 35.297, 75.633),
        Location("astore", "Astore", "استور", 35.366, 74.857),
        Location("deosai", "Deosai Plains", "دیوسائی", 35.017, 75.483),
        Location("neelum-sharda", "Sharda (Neelum)", "شاردہ نیلم", 34.793, 74.187),
        Location("muzaffarabad", "Muzaffarabad", "مظفرآباد", 34.370, 73.471),
    )
}


@dataclass(frozen=True, slots=True)
class WeatherThresholds:
    snowfall_cm: float = 2.0
    precipitation_mm: float = 25.0
    wind_gust_kmh: float = 60.0
    forecast_days: int = 3


class OpenMeteoProvider(DataProvider):
    name = "open_meteo"
    supported_source_types = frozenset({"weather"})

    def __init__(self, fetcher: HttpFetcher, thresholds: WeatherThresholds | None = None) -> None:
        self._fetcher = fetcher
        self._t = thresholds or WeatherThresholds()

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(ok=True, provider=self.name, message="Open-Meteo needs no API key.")

    def validate_source(self, source: SourceRef) -> SourceValidation:
        try:
            location = self._location(source)
        except ProviderError as exc:
            return SourceValidation(ok=False, error_code=exc.code, message=exc.message)
        return SourceValidation(ok=True, resolved_name=location.name)

    def fetch_posts(
        self, source: SourceRef, since: datetime, until: datetime
    ) -> list[ProviderPost]:
        location = self._location(source)
        result = self._fetcher.get(
            FORECAST_URL,
            params={
                "latitude": location.latitude,
                "longitude": location.longitude,
                "daily": "snowfall_sum,precipitation_sum,weather_code,wind_gusts_10m_max",
                "timezone": "Asia/Karachi",
                "forecast_days": self._t.forecast_days,
            },
            operation=f"weather:{location.slug}",
        )
        try:
            daily = json.loads(result.content)["daily"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_ERROR, "Unexpected Open-Meteo response."
            ) from exc
        return self.alerts_from_daily(location, daily, posted_at=until)

    def alerts_from_daily(
        self, location: Location, daily: dict, *, posted_at: datetime
    ) -> list[ProviderPost]:
        posts: list[ProviderPost] = []
        days = daily.get("time") or []
        for i, day in enumerate(days):
            snow = _value(daily, "snowfall_sum", i)
            precip = _value(daily, "precipitation_sum", i)
            gust = _value(daily, "wind_gusts_10m_max", i)
            code = _value(daily, "weather_code", i)

            kinds: list[str] = []
            details: list[str] = []
            if snow is not None and snow >= self._t.snowfall_cm:
                kinds.append("snow")
                details.append(f"heavy snowfall about {snow:.0f} cm")
            if precip is not None and precip >= self._t.precipitation_mm:
                kinds.append("rain")
                details.append(f"heavy rain/precipitation about {precip:.0f} mm")
            if gust is not None and gust >= self._t.wind_gust_kmh:
                kinds.append("wind")
                details.append(f"strong wind gusts up to {gust:.0f} km/h")
            if code is not None and int(code) in THUNDERSTORM_CODES:
                kinds.append("thunderstorm")
                details.append("thunderstorm")
            if not kinds:
                continue

            label = date.fromisoformat(day).strftime("%a %d %b %Y")
            text = (
                f"Weather forecast alert – {location.name} ({location.name_ur}): "
                f"{', '.join(details)} expected on {label}. "
                "Source: Open-Meteo forecast (CC BY 4.0)."
            )
            posts.append(
                ProviderPost(
                    external_post_id=f"{location.slug}:{day}:{'+'.join(kinds)}",
                    posted_at=posted_at,
                    text=text,
                    url=(
                        "https://open-meteo.com/en/docs"
                        f"?latitude={location.latitude}&longitude={location.longitude}"
                    ),
                )
            )
        return posts

    @staticmethod
    def _location(source: SourceRef) -> Location:
        location = NORTHERN_LOCATIONS.get(source.identifier)
        if location is None:
            raise ProviderError(
                ProviderErrorCode.INVALID_SOURCE,
                f"Unknown weather location {source.identifier!r}. "
                f"Known: {', '.join(sorted(NORTHERN_LOCATIONS))}.",
            )
        return location

    def close(self) -> None:
        self._fetcher.close()


def _value(daily: dict, key: str, index: int) -> float | None:
    values = daily.get(key) or []
    if index >= len(values) or values[index] is None:
        return None
    return float(values[index])
