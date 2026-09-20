import pandas as pd
import json

# 1. Load the 127 major cities JSON
with open('pakistan-cities-by-population-2026.json', 'r', encoding='utf-8') as f:
    json_data = json.load(f)
json_cities = [item['city'] for item in json_data]

# 2. Load the 6,444 places CSV
df = pd.read_csv('6a80b80c-ecd2-4594-829c-d75c6509259e.csv')
csv_cities = df['Area_Name'].dropna().astype(str).tolist()

# 3. Deduplicate and sort alphabetically
combined_cities = sorted(list(set(json_cities + csv_cities)))

# 4. Export clean JSON array
with open('combined_places.json', 'w', encoding='utf-8') as f:
    json.dump(combined_cities, f, ensure_ascii=False, indent=2)

print(f"Successfully generated {len(combined_cities)} unique places!")