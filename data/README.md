# Sample data

`northern-weather-news-2026-09-15.csv` is the first real output of the
northern-areas weather/hazard news collector (see
[docs/northern-news.md](../docs/northern-news.md)). It has 12 rows: 3 news
headlines and 9 forecast alerts.

| Column | Meaning |
|---|---|
| `posted_at_pkt` | Publish time, Pakistan time |
| `source_name` / `source_type` | Where it came from (`google_news`, `rss`, `weather`) |
| `locations` / `hazards` | Matched northern locations and hazard types |
| `text` | Headline or forecast alert text |
| `url` | Link to the original article or forecast |

Attribution:

- **News headlines** belong to their publishers. Only headlines and links are
  included, so follow the link for the full article.
- **Forecast alerts** are derived from [Open-Meteo](https://open-meteo.com/)
  data, licensed CC BY 4.0. They are model forecasts, not official warnings.

What is *not* included: the local database, the `.env` file (secrets), mock
Facebook test data, and run logs.
