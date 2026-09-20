[out:json][timeout:900];
area["ISO3166-1"="PK"][admin_level=2]->.pk;
nwr(area.pk)["place"~"^(city|town|village|hamlet|suburb|neighbourhood|quarter|locality|isolated_dwelling)$"]["name"];
out tags center;
