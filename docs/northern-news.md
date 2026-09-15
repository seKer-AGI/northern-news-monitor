# Northern-areas weather & hazard news

Collects news and forecast alerts about weather and hazards in Pakistan's
northern areas (Murree, Galiyat, Kaghan/Naran, Swat, Chitral, Gilgit-Baltistan,
Neelum/AJK, KKH). It writes them to a daily CSV file. It needs no Facebook
account, login, or API key.

```text
Google News RSS searches ─┐
Publisher RSS feeds ──────┼─▶ fetch ─▶ window filter ─▶ relevance filter ─▶ dedupe ─▶ PostgreSQL ─▶ CSV
Open-Meteo forecasts ─────┘                         (location AND hazard)
```

## Quick start

```bash
python -m app db migrate
python -m app sources seed-northern
python -m app collect
python -m app export news-csv --since-hours 24 --output exports/northern-weather-news.csv
```

Daily, on Windows: `scripts\run-daily.ps1` starts the database, collects, and
writes `exports\northern-weather-news-YYYY-MM-DD.csv` plus
`exports\northern-weather-news-latest.csv`. Schedule it with Windows Task
Scheduler. The computer must be on at the scheduled time. A missed day is caught
up on the next run, because each source remembers its last successful window.

## CSV columns

| Column | Meaning |
|---|---|
| `posted_at_pkt` | Publish time, Pakistan time (`YYYY-MM-DD HH:MM`) |
| `source_name` | e.g. `Google News: Gilgit-Baltistan / KKH`, `Dawn — Pakistan`, `Weather: Skardu` |
| `source_type` | `google_news`, `rss` or `weather` |
| `locations` | Matched northern locations, e.g. `Chitral; Swat` |
| `hazards` | Matched hazards, e.g. `Flood; Landslide; Road blocked` |
| `text` | Headline, plus a short summary for publisher feeds |
| `url` | Link to the article, or to the forecast for weather alerts |

Rows are newest first. When several outlets carry the same headline, they are
collapsed into one row (use `--no-dedupe` to keep every row).

## Default sources (`sources seed-northern`)

Each URL was fetched and parsed successfully before being added.

**Google News recency:** the `when:2d` operator must come *first* in the query.
At the end of a long query Google News ignores it and returns months-old
stories. Measured on 2026-09-15, that gave 3 of 100 items recent, versus 22 of 22 with
`when:` first. With the fix, each regional query returns 9–40 recent items. How
many pass the relevance filter depends on whether anything actually happened
that day. On 2026-09-15 it was 3 stories (KKH blocked, Khunjerab snowfall), plus 9
forecast alerts.

| Type | Sources |
|---|---|
| `google_news` | 5 regional searches: Hazara/Galiyat/Kaghan · Swat/Chitral/Dir/Kohistan · Gilgit-Baltistan/KKH · Neelum/AJK · NDMA/PDMA/PMD alerts |
| `rss` | Dawn (Pakistan), Express Tribune (Pakistan), Geo News, ARY News, Daily Jang (Urdu), Express (Urdu), Pamir Times (GB), Chitral Times (Urdu + English), Chitral Today, Daily K2 (GB) |
| `advisory_page` | NDMA advisories, PDMA Khyber Pakhtunkhwa, PMD press releases |
| `weather` | 16 Open-Meteo locations: Murree, Nathia Gali, Naran, Babusar Top, Kalam, Malam Jabba, Chitral, Chilas, Gilgit, Hunza, Khunjerab, Skardu, Astore, Deosai, Sharda (Neelum), Muzaffarabad |

General publisher feeds carry all national news, so on most days few or none of
their items are relevant. They're kept because they catch Urdu stories and
local GB coverage.

Official pages checked but **not** used:

- **GBDMA (PDMA Gilgit-Baltistan)**: `gbdma.gog.pk` doesn't resolve, so the site is down or has moved. GB advisories still arrive through Google News and the GB outlets.
- **SDMA AJK** (`sdma.pk`): returned HTTP 403 to automated requests, which is respected.
- **PDMA KP reporting portal** (`rms.pdma.gov.pk`), **NDMA news**, **GB government news**: these pages have no dated links in their HTML, because the content is loaded by JavaScript.
- **PMD alerts page**: HTTP 404.
- **GB Tribune** and **NHA**: HTTP 403. **Hunza News** has had no updates in months. The **Dawn Urdu** feed is invalid.

Other sources checked but **not** used:

- **Nawa-i-Waqt**: no RSS feed. Its stories still reach Google News.
- **NDMA website**: no feed.
- **UrduPoint**: returned HTTP 403, which is respected and not bypassed.
- **The News RSS**: stale.
- **GDELT DOC API**: returned HTTP 429 (one request per 5 seconds) even when paced, so it's unreliable for now.

Add your own:

```bash
python -m app sources add --type rss --name "Chitral Today" --identifier chitral-today --url https://example/feed
python -m app sources validate <id>
```

## Relevance filter

`app/services/relevance.py` keeps an item only if it mentions **at least one
northern location and at least one hazard/weather term**, in English or Urdu.
Matching respects word boundaries, so:

- "مری" doesn't match inside "امریکہ".
- "rain" doesn't match inside "Bahrain".
- Urdu "دیر" (delay) isn't treated as Dir district.

Arabic and Urdu letter variants (ي/ی, ك/ک) are normalised before matching. Edit
the `LOCATIONS` and `HAZARDS` lists to widen or narrow the filter.

Facebook `page`/`group` sources are **not** relevance-filtered.

## Official advisory pages (`advisory_page`)

Some agencies publish advisories only as links (usually PDFs) on a web page,
with no RSS feed. For these sources, each run:

1. Reads the site's `robots.txt` and **does not touch the page if it disallows
   access**. A `robots.txt` answer of 403 also counts as "stay out".
2. Fetches the page once and keeps links whose text looks like an advisory,
   such as "Weather Advisory 11-09-2026" or "NDMA Flash Flood Advisory (KP & GB) - 22 July 2026".
3. Dates each link from the date in its title (`11 Sep 2026`, `11-09-2026`,
   `12th to 17th April, 2026`), treated as the end of that day in PKT.

Links without a date (menus, maps, plans) get no timestamp and are dropped by
the window filter. Official advisories skip the keyword filter, because they
are relevant by definition. `hazards` starts with `Official advisory`, and
`url` points to the PDF.

```bash
python -m app sources add --type advisory_page --name "NDMA" --identifier ndma-advisories --url https://www.ndma.gov.pk/advisories
```

## Weather alerts

For each location, the Open-Meteo daily forecast (3 days by default) produces
an alert row when any of these thresholds is crossed (configurable in `.env`):

| Setting | Default |
|---|---|
| `WEATHER_SNOWFALL_CM` | 2 cm/day |
| `WEATHER_PRECIPITATION_MM` | 25 mm/day |
| `WEATHER_WIND_GUST_KMH` | 60 km/h |
| thunderstorm weather codes | 95, 96, 99 |

Example: `Weather forecast alert – Skardu (اسکردو): heavy snowfall about 12 cm expected on Wed 16 Sep 2026.`
An alert ID includes the location, date, and alert kinds. The same alert is
stored once, and a new kind of alert for the same day is stored as a new row.

These are **model forecasts, not official warnings**. For official warnings,
look at the PMD, NDMA, and PDMA stories that come through the news sources.

## Being a good citizen (and not getting blocked)

- Sources are public feeds and an open API, meant for exactly this kind of reading.
- About 30 requests per day in total. Each source is fetched once per run.
- A clear User-Agent, timeouts, and a 5 MB response cap.
- Retries are limited to temporary errors, with backoff. HTTP 401/403 counts as a refusal and isn't retried.
- There's no login, no cookies, no proxy or IP rotation, and no scraping of web pages.

## Limits & terms

- **Open-Meteo** free API: **non-commercial use only**. Limits are 600 calls a minute, 5,000 an hour and 10,000 a day, and the data is CC BY 4.0, so keep the attribution. Commercial use needs a paid plan.
- **Google News RSS**: meant for personal feed-reader use. For commercial or redistributed use, review Google's terms or use a licensed news API.
- Publisher feeds and articles belong to their publishers. The CSV stores headlines, short summaries, and links, not full articles.
- **Facebook Groups** posts from local residents are **not** included. There is no permitted automated way to read them. See [meta-api.md](meta-api.md).
