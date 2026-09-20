# Pakistan places master list (names only)

`processed_data/pakistan_places_master.csv` (single column `name`) and `.txt` (one name per line)
hold **130,676 unique Pakistani place names** (cities, towns, villages, hamlets, localities).
No coordinates, population, IDs, province/district or any other metadata are in those files.

## Quick start

```
python scripts/build_master_dataset.py
```

Requires Python 3.9+ and nothing else (standard library only). It reads the raw sources in this folder,
writes `processed_data/` and `reports/`, and asserts the final-file quality checks (single `name` column,
no blank/duplicate/non-ASCII names, TXT == CSV). It prints a summary and saves it to `reports/build_summary.txt`.

## Folder layout

| Path | What |
|---|---|
| `PK.txt` | raw: GeoNames Pakistan dump (27 MB) |
| `6a80b80c-ecd2-4594-829c-d75c6509259e.csv` | raw: Pakistan Post area names |
| `pakistan-cities-by-population-2026.json` | raw: 127 major cities |
| `combined_places.json`, `populated_places_min.json`, `code.py`, `code2.py` | earlier work: derived files and the scripts that made them (verified redundant, see inventory) |
| `original_data/additional_sources/` | OpenStreetMap Overpass download, its query (`.overpassql`) and `manifest.json` |
| `processed_data/` | **final output**: `pakistan_places_master.csv` / `.txt` |
| `reports/` | QC reports (see below) |
| `scripts/build_master_dataset.py`, `scripts/northern_checklist.py` | reproducible pipeline + northern validation checklist |

To add another public source, drop the file in `original_data/additional_sources/`, add an entry to
`manifest.json` (formats supported: `osm_overpass_json`, `geonames_tsv`, `csv_column`) and re-run the script.

## Sources

| Source | Used | Notes |
|---|---|---|
| `PK.txt` - GeoNames Pakistan dump, 229,955 rows, Pakistan-only | yes - class `P` (populated place) with fcodes PPL/PPLA*/PPLC/PPLG/PPLL/PPLF/PPLS/PPLR (145,810 rows) | classes H/T/L/S/R/V/A (rivers, mountains, areas, buildings, roads, admin) are not settlements; admin class used only as a cross-check |
| `6a80b80c-...csv` - Pakistan Post area names, 6,444 rows | yes | post-office names: needs suffix (Gpo/Npo/...) and parenthetical cleanup, and institution filtering |
| `pakistan-cities-by-population-2026.json` - 127 cities | yes | population/growth fields dropped |
| `combined_places.json`, `populated_places_min.json` | no | verified to be pure derivatives of the sources above (name sets identical) |
| OpenStreetMap via Overpass API (`https://overpass-api.de/api/interpreter`, (c) OpenStreetMap contributors, ODbL) - 31,675 place elements inside the PK boundary, snapshot 2026-09-20 | yes - `place=city/town/village/hamlet` (26,914 records incl. Urdu-script-only names, of which 26,869 kept) | contributed 13,826 names found in no other source; many are in Northern Pakistan |

Not used: Kaggle (needs login), Wikidata (not approved for download; thin on villages).

## Cleaning and deduplication

* Unicode NFC; curly quotes -> `'`; **diacritics folded to ASCII** (`Ziārat` -> `Ziarat`, 735 names); whitespace collapsed/trimmed.
* ALL-CAPS / all-lowercase names are title-cased; mixed-case names are left alone.
* Removed post-office suffixes (`Gpo`, `Npo`, `N.P.O.`, `T.So`, `H.O`), parentheticals (`(Nd)`, `(Ak)`, `(Seasonal)`) and everything after a comma (`Village, Tehsil X, District Y` -> `Village`).
* Excluded (all logged in `reports/excluded_names.csv`, with reason): GeoNames `PPLX/PPLQ/PPLW/PPLH`, OSM suburb/neighbourhood/quarter/locality/isolated_dwelling, schools, colleges, universities, hospitals, factories, hotels, post offices, roads/bridges/barrages, admin-unit names (`... Tehsil`, `District ...`), generic single words, Urdu-script-only OSM names with no Latin name.
* Dedup levels: exact -> case-insensitive -> whitespace -> obvious format (diacritics/quotes/dots). Only these are merged: 179,082 kept records collapse to 130,676 unique names (ladder in `reports/build_summary.txt`).
* **Not merged, listed for review** in `reports/possible_duplicates.csv` (6,031 pairs): differences only in spaces/hyphens (`Khair Pur` / `Khairpur`) and phonetic-lite variants (`Dhaki` / `Dhakki`). Places that legitimately share a name are kept as one name (the file has names only).

## Reports

* `source_inventory.csv` - every file: role, rows, name column, place types, nulls, duplicates, malformed counts, scope, used or not.
* `source_contributions.csv` - per-source records, exclusions, unique and exclusive names.
* `possible_duplicates.csv` - manual-review pairs.
* `northern_areas_validation.csv` - 45 northern regions + 4 province rows (counts, checklist coverage, low-coverage flags, missing places, GeoNames admin units not in master).
* `northern_checklist_place_checks.csv` - 390 place-level checks: found/variant/alias/missing, whether a located record falls in the region, other evidence, similar names nearby.
* `excluded_names.csv`, `normalization_log.csv`, `build_summary.txt`.

## Northern Pakistan validation - what was done and what it shows

The checklist (`scripts/northern_checklist.py`) covers every area you listed (Murree, Galiyat, Abbottabad, Mansehra, Kaghan/Naran/Balakot, Swat/Kalam/Mingora/Malam Jabba, Upper/Lower Dir, Chitral/Kalash, Kohistan, Torghar, Shangla, Buner, Battagram, Astore, Diamer, Gilgit, Hunza, Nagar, Ghizer, Skardu, Shigar, Kharmang, Ghanche, Roundu, Deosai, Neelum, Muzaffarabad, Bagh, Poonch/Rawalakot, Haveli, Sudhanoti, Kotli, Mirpur, Bhimber) plus the China-border belt, Malakand/Bajaur, Haripur-Swabi-Mardan and the NE/Lahore-Kasur India-border belts: 372 distinct settlements, 390 region-place checks.

* 334 of the 372 checklist places are present in the master (some under a variant spelling); 38 are not.
* **The checklist is author-curated from general knowledge, not an authoritative gazetteer.** "Missing" means "not found under the listed spellings", not "does not exist".
* Adding OSM cut the checklist places not found from 60 to 35 (30 after accepting a few extra spellings; 9 more exist only as GeoNames alternate names) and raised located names for Nagar from 89 to 140, Hunza 178 -> 251, Gilgit 248 -> 290.
* 18 of 45 regions are still flagged `LOW/REVIEW` in `northern_areas_validation.csv` (mostly Gilgit-Baltistan: Nagar, Diamer, Skardu, Shigar, Kharmang, Ghanche, Roundu, Deosai, China border belt; plus Upper Chitral, Upper Dir, Muzaffarabad, Poonch, Haveli, Sudhanoti, Bhimber, Lahore-Kasur). Flags mean "some checklist places absent or only found elsewhere", not necessarily an error.

## Known limitations

* No claim of completeness. Location-level checks use rough bounding boxes and only sources with coordinates (GeoNames, OSM); postal-CSV names have no coordinates.
* Checklist places not found under any listed spelling include Chalt, Askurdas, Ghulmet, Garmasai, Thol (Nagar), Kuardu, Chutron, Thurgo, Kharkoo, Gonar Farm, Khanbari, Peochar, Chagharzai, Banjosa, Toli Pir, Nakyal, Ranjata, Kiwai, Numbal, Ghora Dhaka and Tarbela (only as a destroyed/dam feature); Sadpara, Haramosh, Hodar, Jandol, Khunjerab exist only as area/terrain features. Full list with evidence and similar nearby names: `northern_checklist_place_checks.csv`.
* Some places exist in sources only as areas/localities/neighbourhoods and were excluded by design (e.g. Haramosh, Hodar, Jandol as GeoNames `L`; Kuldana, Naluchi as OSM neighbourhoods). Review `northern_checklist_place_checks.csv` -> `other_evidence`.
* Spelling: only one spelling per place is kept when sources agree exactly after normalisation. E.g. `Nathia Gali` is present but `Nathiagali` is not.
* Chak names with spelled-out numbers (`Chak One Hundred Twelve ...`) and `Chak 112/6-R`-style numeric variants are both kept (not auto-merged).
* Diacritic folding to ASCII is a deliberate choice; non-Latin (Urdu) script names are not in the output.
* 2-letter names and a few abbreviations (`B.T.M`, `P.A.F`) come straight from GeoNames/postal data and were not judged individually.
