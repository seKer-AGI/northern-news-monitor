#!/usr/bin/env python3
"""Build the Pakistan place-name master list (names only) from the project's source files.

Run from anywhere:   python scripts/build_master_dataset.py

Inputs (never modified):
  * PK.txt                                        GeoNames Pakistan dump (all feature classes)
  * 6a80b80c-...csv                               Pakistan Post area names (post-office / locality names)
  * pakistan-cities-by-population-2026.json       127 major cities
  * combined_places.json, populated_places_min.json   DERIVED from the above by code.py / code2.py;
                                                  verified to be subsets, therefore not used again
  * original_data/additional_sources/manifest.json   OPTIONAL extra public sources (see README)

Outputs:
  processed_data/pakistan_places_master.csv|txt   single column `name`
  reports/*.csv, reports/build_summary.txt

The script uses the standard library only.
"""
import csv
import difflib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from northern_checklist import REGIONS, PROVINCE_ROWS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DATA = ROOT / "processed_data"
OUT_REP = ROOT / "reports"
ADDL_DIR = ROOT / "original_data" / "additional_sources"

GEONAMES = ROOT / "PK.txt"
POSTAL = ROOT / "6a80b80c-ecd2-4594-829c-d75c6509259e.csv"
CITIES = ROOT / "pakistan-cities-by-population-2026.json"
DERIVED_COMBINED = ROOT / "combined_places.json"
DERIVED_POPMIN = ROOT / "populated_places_min.json"

# GeoNames populated-place feature codes we accept as settlements.
GN_KEEP_FCODES = {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLC", "PPLG", "PPLL", "PPLF", "PPLS", "PPLR"}
GN_DROP_FCODES = {
    "PPLX": "GeoNames PPLX = section of a populated place (neighbourhood, no independent identity)",
    "PPLQ": "GeoNames PPLQ = abandoned populated place",
    "PPLW": "GeoNames PPLW = destroyed populated place",
    "PPLH": "GeoNames PPLH = historical populated place",
}
OSM_KEEP = {"city", "town", "village", "hamlet"}

# --------------------------------------------------------------------------- normalisation
QUOTE_MAP = str.maketrans({
    "’": "'", "‘": "'", "ʼ": "'", "ʻ": "'", "ʿ": "'", "ʾ": "'", "`": "'", "´": "'",
    "“": '"', "”": '"', "–": "-", "—": "-", "‐": "-", "‑": "-", " ": " ",
})
POSTAL_SUFFIX_RE = re.compile(r"\s+(?:g\.?\s?p\.?\s?o\.?|n\.?\s?p\.?\s?o\.?|t\.?\s?so\.?|h\.?\s?o\.?)$", re.I)
PAREN_RE = re.compile(r"\s*\([^)]*\)?")
TRAILING_COUNTRY_RE = re.compile(r"^(?P<keep>\S+\s+\S.*?)\s+Pakistan$", re.I)
EDGE_PUNCT = " .,;:-_/\\'\""


def fold_ascii(s: str) -> str:
    """Strip diacritics (NFKD) -> plain ASCII where possible. Non-Latin letters are left alone."""
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def smart_case(s: str) -> str:
    letters = [c for c in s if c.isalpha()]
    if letters and (all(c.isupper() for c in letters) or all(c.islower() for c in letters)):
        return re.sub(r"[A-Za-z]+(?:'[A-Za-z]+)?", lambda m: m.group(0).capitalize(), s.lower())
    return s


def clean_name(raw: str, source_kind: str):
    """Return (clean_name, [change tags])."""
    changes = []
    s = unicodedata.normalize("NFC", raw)
    t = s.translate(QUOTE_MAP)
    if t != s:
        changes.append("punctuation-unicode")
    s = t
    if PAREN_RE.search(s):
        s = PAREN_RE.sub("", s)
        changes.append("stripped-parenthetical")
    if "," in s:  # "Village, Tehsil X, District Y, ..." -> keep only the leading place name
        s = s.split(",")[0]
        changes.append("comma-qualifier-stripped")
    n = TRAILING_COUNTRY_RE.sub(r"\g<keep>", s)
    if n != s:
        changes.append("stripped-trailing-country")
        s = n
    if source_kind == "postal":
        n = POSTAL_SUFFIX_RE.sub("", s)
        if n != s:
            changes.append("stripped-post-office-suffix")
            s = n
    f = fold_ascii(s)
    if f != s:
        changes.append("diacritics-folded")
        s = f
    t = re.sub(r"\s+", " ", s).strip(EDGE_PUNCT)
    t = re.sub(r"\s+", " ", t).strip()
    if t != s.strip() and "whitespace" not in changes and re.sub(r"\s+", " ", raw.strip()) != raw:
        changes.append("whitespace")
    s = t
    c = smart_case(s)
    if c != s:
        changes.append("recased")
        s = c
    return s, changes


# --------------------------------------------------------------------------- filters
STRICT_KW = re.compile(
    r"\b(university|stadium|cricket ground|dispensary|factory|tube well|bus stop|check ?post|petrol pump)\b", re.I)
BROAD_KW = re.compile(
    r"\b(school|college|university|hospital|dispensary|institute|academy|stadium|cricket|hotel|factory|workshop|"
    r"depot|petrol|airport|railway station|post office|training|ordinance|telegraph|express post|police recruit|"
    r"tube well|grain market|cloth market|check ?post|mental)\b", re.I)
INFRA_SUFFIX = re.compile(r"\b(road|highway|motorway|bypass|street|bridge|flyover|underpass|interchange|barrage)$", re.I)
GENERIC_WORDS = {"college", "hill", "mall", "gate", "workshop", "cantt", "station", "school", "hospital", "camp",
                 "block", "market", "bazar", "colony", "town", "city", "village", "chowk", "dam", "fort", "airport",
                 "pass", "post", "farm", "park", "unknown", "none", "null", "nan", "pakistan"}
ADMIN_UNIT = re.compile(r"(\b(tehsil|tahsil|district|division|subdivision|province)$)|(^district\b)", re.I)
GENERIC_SUBUNIT = re.compile(r"^(block|sector|phase)( number)?( [a-z0-9\-]+)?$", re.I)


def exclusion_reason(name: str, source_kind: str):
    if len(name) < 2:
        return "too-short"
    if not re.search(r"[A-Za-z]", name):
        return "no-letters"
    if re.search(r"[^\x00-\x7f]", name):
        return "non-latin-characters"
    if name.casefold() in GENERIC_WORDS:
        return "generic-single-word"
    if GENERIC_SUBUNIT.match(name):
        return "generic-numbered-subunit"
    if ADMIN_UNIT.search(name):
        return "administrative-unit-name"
    if INFRA_SUFFIX.search(name):
        return "road/bridge/barrage-infrastructure"
    kw = BROAD_KW if source_kind == "postal" else STRICT_KW
    m = kw.search(name)
    if m:
        return f"non-settlement-keyword:{m.group(1).lower()}"
    return None


# --------------------------------------------------------------------------- dedup keys
def key_l2(s):  # case-insensitive
    return s.casefold()


def key_l3(s):  # + whitespace-normalised
    return re.sub(r"\s+", " ", s.casefold()).strip()


def key_l4(s):  # + obvious formatting: unicode/diacritics, quote and dot removal
    return re.sub(r"[.'\"`]", "", key_l3(fold_ascii(s))).strip()


def key_alnum(s):  # spaces/hyphens/slashes removed - REVIEW ONLY, never auto-merged
    return re.sub(r"[^a-z0-9]", "", key_l4(s))


_PH_SUBS = [("ph", "f"), ("ee", "i"), ("oo", "u"), ("aa", "a"), ("ai", "ay"), ("ei", "ay"), ("ey", "i"),
            ("ou", "u"), ("q", "k"), ("v", "w"), ("z", "j"), ("kh", "k"), ("gh", "g")]


def key_phonetic(s):  # phonetic-lite - REVIEW ONLY
    k = key_alnum(s)
    for a, b in _PH_SUBS:
        k = k.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", k)


# --------------------------------------------------------------------------- source loaders
def read_geonames(path):
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            c = line.split("\t")
            if len(c) < 9:
                continue
            c += [""] * (19 - len(c))
            rows.append({
                "id": c[0], "name": c[1], "ascii": c[2], "alt": c[3],
                "lat": float(c[4]) if c[4] else None, "lon": float(c[5]) if c[5] else None,
                "fclass": c[6], "fcode": c[7], "cc": c[8], "adm1": c[10],
            })
    return rows


def read_postal(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_additional():
    """Optional extra sources, described by original_data/additional_sources/manifest.json."""
    manifest = ADDL_DIR / "manifest.json"
    if not manifest.exists():
        return []
    return read_json(manifest)


def latin_name_from_osm_tags(tags):
    for k in ("name", "name:en", "int_name", "name:ur-Latn", "alt_name:en"):
        v = tags.get(k)
        if v and re.search(r"[A-Za-z]", v) and not re.search(r"[؀-ۿ]", v):
            return v
    return None


# --------------------------------------------------------------------------- profiling / inventory
def profile_names(names):
    names = list(names)
    blank = sum(1 for n in names if n is None or not str(n).strip())
    vals = [str(n) for n in names if n is not None and str(n).strip()]
    c = Counter(vals)
    return {
        "rows": len(names),
        "blank_or_null_names": blank,
        "exact_duplicate_names": len(vals) - len(c),
        "case_insensitive_duplicate_names": len(vals) - len({v.casefold() for v in vals}),
        "whitespace_issues": sum(1 for v in vals if v != v.strip() or "  " in v),
        "non_ascii_names": sum(1 for v in vals if re.search(r"[^\x00-\x7f]", v)),
        "no_letter_names": sum(1 for v in vals if not re.search(r"[A-Za-z]", v)),
        "all_upper_or_lower_names": sum(1 for v in vals if v.isupper() or v.islower()),
    }


def build_inventory(gn, postal, cities, combined, popmin, addl_info):
    gn_p = [r for r in gn if r["fclass"] == "P"]
    inv = []

    def add(path, **kw):
        row = {"path": str(path.relative_to(ROOT)).replace("\\", "/") if path.is_absolute() else path,
               "extension": "", "size_bytes": "", "role": "", "rows": "", "name_column": "",
               "place_types_contained": "", "blank_or_null_names": "", "exact_duplicate_names": "",
               "case_insensitive_duplicate_names": "", "whitespace_issues": "", "non_ascii_names": "",
               "no_letter_names": "", "all_upper_or_lower_names": "", "geographic_scope": "",
               "contains_pakistan_place_names": "", "used_for_master": "", "raw_records_used": "", "notes": ""}
        row.update(kw)
        inv.append(row)

    def size(p):
        return p.stat().st_size if p.exists() else ""

    # GeoNames
    pr = profile_names([r["name"] for r in gn])
    fc = Counter(r["fclass"] for r in gn)
    ccs = Counter(r["cc"] for r in gn)
    add(GEONAMES, extension=".txt", size_bytes=size(GEONAMES), role="raw source (GeoNames dump, tab-separated, no header)",
        name_column="col 2 (`name`; col 3 asciiname; col 4 alternatenames)",
        place_types_contained="all feature classes: " + ", ".join(f"{k}={v}" for k, v in sorted(fc.items()))
        + " (P = populated place)",
        geographic_scope=f"Pakistan only (country codes: {dict(ccs)}); no worldwide filtering required",
        contains_pakistan_place_names="yes", used_for_master="yes",
        raw_records_used=sum(1 for r in gn_p if r["fcode"] in GN_KEEP_FCODES),
        notes=f"Only class P with fcode in {sorted(GN_KEEP_FCODES)} used. {len(gn_p)} P rows; other classes "
              "(H hydro, T terrain, L area, S spot/building, R road/rail, V vegetation, A admin) are not settlements. "
              "Class A used only as a validation cross-check. Largest source but not automatically the best: "
              "sparse/missing for several northern towns (see reports/northern_areas_validation.csv).", **pr)
    # postal
    pr = profile_names([r["Area_Name"] for r in postal])
    add(POSTAL, extension=".csv", size_bytes=size(POSTAL), role="raw source (Pakistan Post area names)", name_column="Area_Name",
        place_types_contained="post-office / locality names: villages, towns, colonies, bazaars, cantonments, "
                              "plus noise (institutions, GPO/NPO offices, roads, factories)",
        geographic_scope="Pakistan only", contains_pakistan_place_names="yes", used_for_master="yes",
        raw_records_used=len(postal),
        notes="Columns _id, Area_Name, Postal_code (Postal_code and _id are NOT carried forward). "
              "Needs suffix/parenthetical cleanup and institution filtering.", **pr)
    # cities
    pr = profile_names([r.get("city") for r in cities])
    add(CITIES, extension=".json", size_bytes=size(CITIES), role="raw source (127 major cities)", name_column="city",
        place_types_contained="major cities", geographic_scope="Pakistan only", contains_pakistan_place_names="yes",
        used_for_master="yes", raw_records_used=len(cities),
        notes="Also has pop2026/growthRate (NOT carried forward).", **pr)
    # derived
    gn_p_names = {r["name"] for r in gn_p}
    src_names = {r["Area_Name"] for r in postal} | {r["city"] for r in cities}
    pr = profile_names(combined)
    add(DERIVED_COMBINED, extension=".json", size_bytes=size(DERIVED_COMBINED),
        role="DERIVED output of code.py (union of postal CSV + cities JSON)", name_column="(JSON array of strings)",
        place_types_contained="same as postal CSV + cities JSON", geographic_scope="Pakistan only",
        contains_pakistan_place_names="yes", used_for_master="no (redundant)", raw_records_used=0,
        notes=f"Verified: set equals postal CSV names ∪ cities JSON names -> {set(combined) == src_names}. "
              "Adds no information; re-deriving from originals instead.", **pr)
    pr = profile_names([r.get("name") for r in popmin])
    add(DERIVED_POPMIN, extension=".json", size_bytes=size(DERIVED_POPMIN),
        role="DERIVED output of code2.py (GeoNames class P, name+lat+lng)", name_column="name",
        place_types_contained="GeoNames class P (all fcodes incl. PPLX/PPLQ/PPLW)", geographic_scope="Pakistan only",
        contains_pakistan_place_names="yes", used_for_master="no (redundant)", raw_records_used=0,
        notes=f"Verified: {len(popmin)} rows vs {len(gn_p)} class-P rows in PK.txt; name sets equal -> "
              f"{ {r.get('name') for r in popmin} == gn_p_names }. Contains lat/lng (never carried forward).", **pr)
    # scripts / misc
    for name, role, note in [("code.py", "existing script", "Builds combined_places.json from postal CSV + cities JSON (no filtering/normalisation)."),
                             ("code2.py", "existing script", "Exports GeoNames class P name/lat/lng to populated_places_min.json (includes PPLX/PPLQ/PPLW, no dedup)."),
                             ("temp.ipynb", "empty notebook", "0 bytes - nothing to inspect.")]:
        p = ROOT / name
        if p.exists():
            add(p, extension=p.suffix, size_bytes=size(p), role=role, contains_pakistan_place_names="no",
                used_for_master="no", notes=note)
    add(ROOT / "venv", extension="(dir)", role="Python virtual environment", contains_pakistan_place_names="no",
        used_for_master="no", notes="Skipped (not project data).")
    for a in addl_info:
        add(a["path"], **{k: v for k, v in a.items() if k != "path"})
    return inv


# --------------------------------------------------------------------------- main
def main():
    OUT_DATA.mkdir(exist_ok=True)
    OUT_REP.mkdir(exist_ok=True)

    print("Loading sources ...")
    gn = read_geonames(GEONAMES)
    postal = read_postal(POSTAL)
    cities = read_json(CITIES)
    combined = read_json(DERIVED_COMBINED)
    popmin = read_json(DERIVED_POPMIN)

    # -------- collect raw candidate records: (raw_name, source_id, kind, lat, lon, adm1, source_rank)
    cands = []            # dicts
    excluded = []         # (name, source, reason)
    src_stats = defaultdict(lambda: Counter())
    SOURCE_RANK = {}

    def add_source(sid, rank):
        SOURCE_RANK[sid] = rank

    add_source("geonames_PK", 1)
    add_source("postal_areas_csv", 2)
    add_source("cities_json_127", 3)

    for r in gn:
        if r["fclass"] != "P":
            continue
        src_stats["geonames_PK"]["class_P_rows"] += 1
        if r["fcode"] in GN_DROP_FCODES:
            excluded.append((r["name"], "geonames_PK", GN_DROP_FCODES[r["fcode"]]))
            src_stats["geonames_PK"]["excluded_fcode"] += 1
        elif r["fcode"] in GN_KEEP_FCODES:
            cands.append({"raw": r["name"], "src": "geonames_PK", "kind": "geonames",
                          "lat": r["lat"], "lon": r["lon"], "adm1": r["adm1"]})
        else:
            excluded.append((r["name"], "geonames_PK", f"unexpected fcode {r['fcode']}"))
    for r in postal:
        cands.append({"raw": r["Area_Name"] or "", "src": "postal_areas_csv", "kind": "postal", "lat": None, "lon": None, "adm1": ""})
    for r in cities:
        cands.append({"raw": r.get("city") or "", "src": "cities_json_127", "kind": "cities", "lat": None, "lon": None, "adm1": ""})

    # -------- optional additional sources
    addl_info = []
    for spec in load_additional():
        sid, fmt, path = spec["id"], spec["format"], ADDL_DIR / spec["file"]
        if not path.exists():
            print(f"  ! additional source {sid}: file missing ({path}) - skipped")
            continue
        add_source(sid, spec.get("rank", 10))
        n_rows = n_used = 0
        if fmt == "osm_overpass_json":
            data = read_json(path)
            place_types = Counter()
            names_for_profile = []
            for el in data.get("elements", []):
                tags = el.get("tags", {})
                if "place" not in tags:
                    continue
                n_rows += 1
                place_types[tags["place"]] += 1
                names_for_profile.append(tags.get("name"))
                if tags["place"] not in OSM_KEEP:
                    excluded.append((latin_name_from_osm_tags(tags) or tags.get("name", ""), sid, f"OSM place={tags['place']} (not a populated settlement type we keep)"))
                    continue
                nm = latin_name_from_osm_tags(tags)
                if not nm:
                    excluded.append((tags.get("name", ""), sid, "no Latin-script name tag"))
                    continue
                lat = el.get("lat", (el.get("center") or {}).get("lat"))
                lon = el.get("lon", (el.get("center") or {}).get("lon"))
                cands.append({"raw": nm, "src": sid, "kind": "osm", "lat": lat, "lon": lon, "adm1": ""})
                n_used += 1
            prof = profile_names(names_for_profile)
            types_txt = ", ".join(f"place={k}:{v}" for k, v in place_types.most_common())
        elif fmt == "geonames_tsv":
            rows = read_geonames(path)
            n_rows = len(rows)
            types_txt = "GeoNames rows"
            prof = profile_names([r["name"] for r in rows])
            for r in rows:
                if r["fclass"] == "P" and r["fcode"] in GN_KEEP_FCODES:
                    cands.append({"raw": r["name"], "src": sid, "kind": "geonames", "lat": r["lat"], "lon": r["lon"], "adm1": r["adm1"]})
                    n_used += 1
        elif fmt == "csv_column":
            with open(path, encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            n_rows = len(rows)
            types_txt = spec.get("place_types", "")
            prof = profile_names([r.get(spec["column"]) for r in rows])
            for r in rows:
                if r.get(spec["column"]):
                    lat = r.get(spec.get("lat_column", "")) or None
                    lon = r.get(spec.get("lon_column", "")) or None
                    cands.append({"raw": r[spec["column"]], "src": sid, "kind": "csv", "lat": float(lat) if lat else None,
                                  "lon": float(lon) if lon else None, "adm1": ""})
                    n_used += 1
        else:
            raise SystemExit(f"unknown additional-source format {fmt}")
        prof.pop("rows", None)
        addl_info.append({
            "path": path, "extension": path.suffix, "size_bytes": path.stat().st_size,
            "role": f"ADDITIONAL public source: {spec.get('description', '')} [{spec.get('url', '')}]",
            "rows": n_rows, "name_column": spec.get("name_column", "tags.name"), "place_types_contained": types_txt,
            "geographic_scope": spec.get("scope", ""), "contains_pakistan_place_names": "yes", "used_for_master": "yes",
            "raw_records_used": n_used, "notes": spec.get("notes", ""), **prof})

    # -------- clean + filter
    print(f"Cleaning {len(cands):,} candidate records ...")
    kept = []
    norm_log = []
    for c in cands:
        src_stats[c["src"]]["candidates"] += 1
        raw = c["raw"]
        if raw is None or not str(raw).strip():
            excluded.append((str(raw), c["src"], "blank-or-null"))
            src_stats[c["src"]]["excluded"] += 1
            continue
        name, changes = clean_name(str(raw), c["kind"])
        reason = exclusion_reason(name, c["kind"]) if name else "blank-after-cleaning"
        if reason:
            excluded.append((raw, c["src"], reason))
            src_stats[c["src"]]["excluded"] += 1
            continue
        if changes:
            norm_log.append((c["src"], raw, name, ";".join(changes)))
        c["name"] = name
        c["k4"] = key_l4(name)
        kept.append(c)
        src_stats[c["src"]]["kept"] += 1

    # -------- dedup ladder statistics
    raw_names = [c["name"] for c in kept]
    ladder = {
        "L0 records after filtering": len(raw_names),
        "L1 distinct after exact-duplicate removal": len(set(raw_names)),
        "L2 distinct after case-insensitive": len({key_l2(n) for n in raw_names}),
        "L3 distinct after whitespace-normalised": len({key_l3(n) for n in raw_names}),
        "L4 distinct after obvious-format (diacritic/quote/dot) normalisation": len({c['k4'] for c in kept}),
    }

    # -------- group by L4 key, pick canonical spelling
    groups = defaultdict(list)
    for c in kept:
        groups[c["k4"]].append(c)

    def cap_penalty(n):
        toks = [t for t in re.split(r"[ \-]", n) if t and t[0].isalpha()]
        return sum(1 for t in toks if t[0].islower())

    master = {}   # k4 -> name
    sources_of = {}
    for k, recs in groups.items():
        cnt = Counter(r["name"] for r in recs)
        best = sorted(cnt, key=lambda n: (cap_penalty(n), min(SOURCE_RANK[r["src"]] for r in recs if r["name"] == n), -cnt[n], n))[0]
        master[k] = best
        sources_of[k] = sorted({r["src"] for r in recs}, key=lambda s: SOURCE_RANK[s])

    # -------- per-source contribution stats
    order = sorted(SOURCE_RANK, key=lambda s: SOURCE_RANK[s])
    seen = set()
    contrib_rows = []
    for sid in order:
        ks = {c["k4"] for c in kept if c["src"] == sid}
        exclusive = {k for k in ks if sources_of[k] == [sid]}
        new = ks - seen
        seen |= ks
        s = src_stats[sid]
        contrib_rows.append({
            "source": sid, "priority_order": SOURCE_RANK[sid],
            "raw_records_considered": s["candidates"], "excluded_by_filters": s["excluded"], "records_kept": s["kept"],
            "unique_names_offered": len(ks), "new_unique_names_added_in_priority_order": len(new),
            "unique_names_found_only_in_this_source": len(exclusive),
        })

    # -------- excluded-names report (+ flag whether name survives elsewhere)
    with open(OUT_REP / "excluded_names.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["name", "source", "reason", "same_name_kept_in_master"])
        seen_ex = set()
        for n, s, r in excluded:
            key = (n, s, r)
            if key in seen_ex:
                continue
            seen_ex.add(key)
            w.writerow([n, s, r, "yes" if key_l4(fold_ascii(str(n))) in master else "no"])
    ex_reason_counts = Counter(r.split(":")[0] if r.startswith("non-settlement") else r for _, _, r in excluded)

    with open(OUT_REP / "normalization_log.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["source", "raw_name", "cleaned_name", "changes"])
        w.writerows(norm_log)

    # -------- possible duplicates (review only, nothing removed)
    names = sorted(master.values(), key=lambda s: (s.casefold(), s))
    pairs = []
    by_alnum = defaultdict(list)
    for n in names:
        by_alnum[key_alnum(n)].append(n)
    for k, grp in by_alnum.items():
        if len(grp) > 1:
            for i in range(len(grp)):
                for j in range(i + 1, len(grp)):
                    pairs.append((grp[i], grp[j], "differs only by spaces/hyphens/slashes/punctuation"))
    by_ph = defaultdict(set)
    for n in names:
        if re.search(r"\d", n):
            continue  # chak/number names: too noisy for phonetic grouping
        by_ph[key_phonetic(n)].add(n)
    seen_pairs = {(a, b) for a, b, _ in pairs}
    for k, grp in by_ph.items():
        grp = sorted(grp)
        if len(grp) < 2 or len(grp) > 6:
            continue
        # only pairs that are not already reported by the alnum rule
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                if key_alnum(grp[i]) == key_alnum(grp[j]):
                    continue
                if (grp[i], grp[j]) not in seen_pairs:
                    pairs.append((grp[i], grp[j], "possible transliteration/spelling variant (same phonetic-lite key)"))
    pairs.sort(key=lambda p: (p[0].casefold(), p[1].casefold()))
    with open(OUT_REP / "possible_duplicates.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["name_1", "name_2", "reason"])
        w.writerows(pairs)

    # -------- final master files
    final = sorted(master.values(), key=lambda s: (s.casefold(), s))
    with open(OUT_DATA / "pakistan_places_master.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["name"])
        for n in final:
            w.writerow([n])
    with open(OUT_DATA / "pakistan_places_master.txt", "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(final) + "\n")

    # -------- Northern Pakistan validation
    print("Running Northern Pakistan validation ...")
    coords = defaultdict(list)   # k4 -> [(lat, lon, src)]
    for c in kept:
        if c["lat"] is not None and c["lon"] is not None:
            coords[c["k4"]].append((c["lat"], c["lon"], c["src"]))
    alnum_index = defaultdict(list)
    for k, n in master.items():
        alnum_index[key_alnum(n)].append(n)
    check_keys = {key_alnum(n) for reg in REGIONS for nm, vs in reg["anchors"] for n in [nm] + vs}
    alias_owner = defaultdict(set)     # checklist key -> primary GeoNames names that carry it as an alias
    other_types = defaultdict(set)     # checklist key -> non-settlement feature types carrying that name
    for r in gn:
        if r["fclass"] == "P" and r["alt"]:
            for a in r["alt"].split(","):
                k = key_alnum(a)
                if k in check_keys and key_alnum(r["name"]) != k:
                    alias_owner[k].add(fold_ascii(r["name"]))
        if r["fclass"] != "P":
            k = key_alnum(r["name"])
            if k in check_keys:
                other_types[k].add(f"GeoNames {r['fclass']}/{r['fcode']}")
    for n, sname, reason in excluded:
        k = key_alnum(str(n))
        if k in check_keys:
            other_types[k].add(f"{sname}: {reason.split(' (')[0].split(' =')[0]}")

    def in_box(lat, lon, b):
        return b[0] <= lat <= b[1] and b[2] <= lon <= b[3]

    pair_index = defaultdict(list)
    for a, b, _ in pairs:
        pair_index[key_l4(a)].append((a, b))
        pair_index[key_l4(b)].append((a, b))

    ADMIN_SUFFIX = re.compile(r"\s+(district|tehsil|tahsil|subdivision|sub-division|division|agency|province|taluka|tehsil)$", re.I)
    admin_units = [(ADMIN_SUFFIX.sub("", r["name"]), r) for r in gn if r["fclass"] == "A" and r["lat"] is not None]

    def anchor_status(name, variants, box):
        cand = [name] + variants
        hit = None
        status = "MISSING"
        for i, nm in enumerate(cand):
            k = key_l4(nm)
            if k in master:
                hit, status = k, ("FOUND" if i == 0 else "FOUND_VARIANT_SPELLING")
                break
        if hit is None:
            for nm in cand:
                ak = key_alnum(nm)
                if ak in alnum_index:
                    hit, status = key_l4(alnum_index[ak][0]), "FOUND_FORMAT_VARIANT"
                    break
        if hit is None:
            keys = [key_alnum(nm) for nm in cand]
            owners = sorted({o for k in keys for o in alias_owner.get(k, ())})
            others = sorted({o for k in keys for o in other_types.get(k, ())})
            extra = []
            if owners:
                extra.append("alias of GeoNames populated place(s): " + ", ".join(owners[:4]))
            if others:
                extra.append("exists only as non-settlement type: " + ", ".join(others[:4]))
            return ("ALIAS_ONLY_IN_GEONAMES_ALTNAMES" if owners else "MISSING"), "", "", "n/a", " | ".join(extra)
        recs = coords.get(hit, [])
        if not recs:
            loc = "unverified (name-only source, no coordinates)"
        elif any(in_box(la, lo, box) for la, lo, _ in recs):
            loc = "yes"
        else:
            loc = "no (name exists but only outside this area)"
        return status, master[hit], ", ".join(sources_of[hit]), loc, ""

    region_rows, anchor_rows = [], []
    for reg in REGIONS:
        box = reg["bbox"]
        in_keys = {k for k, recs in coords.items() if any(in_box(la, lo, box) for la, lo, _ in recs)}
        per_src = Counter()
        for k in in_keys:
            for s in {s for la, lo, s in coords[k] if in_box(la, lo, box)}:
                per_src[s] += 1
        gn_raw = sum(1 for r in gn if r["fclass"] == "P" and r["lat"] is not None and in_box(r["lat"], r["lon"], box))
        counts = Counter()
        missing = []
        names_in_box = sorted(master[k] for k in in_keys)
        for nm, variants in reg["anchors"]:
            st, found_as, srcs, loc, extra = anchor_status(nm, variants, box)
            close = ""
            if not st.startswith("FOUND") or loc.startswith("no"):
                close = "; ".join(difflib.get_close_matches(nm, names_in_box, n=4, cutoff=0.72))
            anchor_rows.append({"region": reg["region"], "checked_place": nm, "accepted_spellings": "; ".join(variants),
                                "status": st, "found_as": found_as, "sources": srcs, "located_in_region_bbox": loc,
                                "other_evidence": extra, "similar_names_located_in_area": close})
            if st.startswith("FOUND"):
                counts["verified" if loc == "yes" else ("name_only" if loc.startswith("unverified") else "elsewhere_only")] += 1
            else:
                counts["missing"] += 1
                missing.append(nm + (f" [{extra}]" if extra else ""))
        n_anch = len(reg["anchors"])
        flags = []
        if len(in_keys) < 25:
            flags.append(f"only {len(in_keys)} located names in bbox")
        if n_anch and (counts["missing"] + counts["elsewhere_only"]) / n_anch > 0.25:
            flags.append(f">25% of checklist places missing/not-found-in-area ({counts['missing']} missing, {counts['elsewhere_only']} only elsewhere)")
        admin_missing = sorted({nm for nm, r in admin_units if in_box(r["lat"], r["lon"], box) and key_l4(nm) not in master})
        dup_pairs = {p for k in in_keys for p in pair_index.get(k, [])}
        region_rows.append({
            "region": reg["region"], "area_type": reg["kind"], "bbox_lat_lon": "%.2f-%.2f N, %.2f-%.2f E" % box,
            "geonames_class_P_records_in_bbox_raw": gn_raw,
            "unique_master_names_with_coordinates_in_bbox": len(in_keys),
            "from_geonames": per_src.get("geonames_PK", 0),
            "from_additional_sources": sum(v for s, v in per_src.items() if s != "geonames_PK"),
            "checklist_places": n_anch, "checklist_found_and_located_in_area": counts["verified"],
            "checklist_found_name_only_location_unverified": counts["name_only"],
            "checklist_name_exists_only_outside_area": counts["elsewhere_only"],
            "checklist_missing": counts["missing"],
            "missing_checklist_places": "; ".join(missing),
            "geonames_admin_units_in_bbox_not_in_master": "; ".join(admin_missing[:15]),
            "possible_duplicate_pairs_touching_area": len(dup_pairs),
            "coverage_flag": "LOW/REVIEW: " + " | ".join(flags) if flags else "ok",
            "note": reg["note"],
        })
    # province level rows
    for code, label in PROVINCE_ROWS.items():
        ks = {c["k4"] for c in kept if c["src"] == "geonames_PK" and c["adm1"] == code}
        region_rows.append({
            "region": label, "area_type": "province-level (GeoNames adm1)", "bbox_lat_lon": "",
            "geonames_class_P_records_in_bbox_raw": sum(1 for r in gn if r["fclass"] == "P" and r["adm1"] == code),
            "unique_master_names_with_coordinates_in_bbox": len(ks), "from_geonames": len(ks),
            "from_additional_sources": "", "checklist_places": "", "checklist_found_and_located_in_area": "",
            "checklist_found_name_only_location_unverified": "", "checklist_name_exists_only_outside_area": "",
            "checklist_missing": "", "missing_checklist_places": "", "geonames_admin_units_in_bbox_not_in_master": "",
            "possible_duplicate_pairs_touching_area": "", "coverage_flag": "info", "note": "GeoNames records only (names carried by adm1 code)",
        })

    def write_dicts(path, rows, cols=None):
        cols = cols or list(rows[0].keys())
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)

    write_dicts(OUT_REP / "northern_areas_validation.csv", region_rows)
    write_dicts(OUT_REP / "northern_checklist_place_checks.csv", anchor_rows)
    write_dicts(OUT_REP / "source_contributions.csv", contrib_rows)
    inv = build_inventory(gn, postal, cities, combined, popmin, addl_info)
    write_dicts(OUT_REP / "source_inventory.csv", inv)

    # -------- quality checks on the final files
    print("Running quality checks ...")
    with open(OUT_DATA / "pakistan_places_master.csv", encoding="utf-8", newline="") as f:
        rd = list(csv.reader(f))
    assert rd[0] == ["name"], "CSV header must be exactly ['name']"
    assert all(len(r) == 1 for r in rd), "every CSV row must have exactly one column"
    vals = [r[0] for r in rd[1:]]
    assert all(isinstance(v, str) and v.strip() for v in vals), "blank/null names present"
    assert all(v == v.strip() and "  " not in v and "\n" not in v for v in vals), "whitespace problems"
    assert len({key_l4(v) for v in vals}) == len(vals), "duplicates remain after normalisation"
    assert len(set(vals)) == len(vals)
    txt = (OUT_DATA / "pakistan_places_master.txt").read_text(encoding="utf-8").split("\n")
    assert txt[-1] == "" and txt[:-1] == vals, "TXT must equal CSV names, one per line"
    assert not any(re.search(r"[^\x00-\x7f]", v) for v in vals), "non-ASCII remained"
    assert not any(re.fullmatch(r"[\d.\-]+", v) for v in vals), "numeric-only names present"
    assert not any(re.search(r"https?://|@", v) for v in vals), "URL/email-like names present"

    # -------- summary
    n_inspected = len(inv)
    used = [r for r in inv if str(r["used_for_master"]).startswith("yes")]
    n_raw = sum(s["candidates"] for s in src_stats.values())
    n_missing_anchor = sum(1 for a in anchor_rows if a["status"] in ("MISSING",))
    lines = [
        "Pakistan places master - build summary",
        "=" * 60,
        f"Sources inspected: {n_inspected}   (files/dirs in project inventory; see reports/source_inventory.csv)",
        f"Sources used: {len(used)}",
        f"Raw records collected: {n_raw}",
        f"Records after filtering: {len(kept)}",
        f"Unique final place names: {len(final)}",
        f"Potential duplicates for review: {len(pairs)}",
        f"Northern-area validation records: {len(anchor_rows)} place checks across {len(REGIONS)} regions "
        f"(+{len(PROVINCE_ROWS)} province rows)",
        "",
        "Deduplication ladder:",
    ] + [f"  {k}: {v}" for k, v in ladder.items()] + [
        "",
        "Per-source contribution:",
    ] + [f"  {r['source']}: considered={r['raw_records_considered']}, kept={r['records_kept']}, "
         f"unique={r['unique_names_offered']}, new_in_priority_order={r['new_unique_names_added_in_priority_order']}, "
         f"exclusive={r['unique_names_found_only_in_this_source']}" for r in contrib_rows] + [
        "",
        "Excluded records by reason:",
    ] + [f"  {k}: {v}" for k, v in ex_reason_counts.most_common()] + [
        "",
        "Northern checklist status counts: " + str(dict(Counter(a["status"] for a in anchor_rows))),
        f"Regions flagged LOW/REVIEW: {sum(1 for r in region_rows if str(r['coverage_flag']).startswith('LOW'))} of {len(REGIONS)}",
        "All quality checks passed.",
    ]
    (OUT_REP / "build_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
