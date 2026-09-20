import json

populated_places = []

with open("PK.txt", "r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        cols = line.strip().split("\t")

        # Column index 6 is feature class ('P' = Populated Place)
        if len(cols) > 6 and cols[6] == "P":
            populated_places.append(
                {
                    "name": cols[1],
                    "lat": float(cols[4]) if cols[4] else None,
                    "lng": float(cols[5]) if cols[5] else None,
                }
            )

# Write to a minified JSON file (using separators to strip all spaces)
with open("populated_places_min.json", "w", encoding="utf-8") as out_file:
    json.dump(
        populated_places, out_file, separators=(",", ":"), ensure_ascii=False
    )

print(
    f"Successfully exported {len(populated_places)} minified records to populated_places_min.json"
)