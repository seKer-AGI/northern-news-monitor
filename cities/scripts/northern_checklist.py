"""Validation checklist for Northern Pakistan coverage.

IMPORTANT: this file is an *author-curated QC aid*, not an authoritative gazetteer and
it is NOT used to add names to the master list. Each region carries:

  bbox    : approximate (lat_min, lat_max, lon_min, lon_max) used to count records in
            sources that carry coordinates (GeoNames, OSM). Boxes overlap on purpose and
            are rough - counts are indicative, not administrative.
  kind    : 'settlement-region' or 'admin-area' (admin areas such as Ghizer / Diamer /
            Torghar are districts, not settlements; we validate the known settlements
            inside them instead of expecting the district name itself).
  anchors : known settlements in the region, as (canonical name, [alternate spellings]).
            A missing anchor means "potentially missing", never "definitely absent":
            the name may exist under a spelling not listed here.
"""

R = []


def region(name, bbox, kind, anchors, note=""):
    R.append({"region": name, "bbox": bbox, "kind": kind, "anchors": anchors, "note": note})


def A(name, *variants):
    return (name, list(variants))


# ---------------------------------------------------------------- Murree / Galiyat / Hazara
region("Murree", (33.75, 34.05, 73.30, 73.60), "settlement-region", [
    A("Murree"), A("Bhurban"), A("Patriata", "New Murree"), A("Ghora Gali", "Ghoragali"),
    A("Jhika Gali", "Jhikagali"), A("Kuldana"), A("Lower Topa", "Topa"), A("Sunny Bank"),
    A("Barian"), A("Kotli Sattian"), A("Numbal"), A("Satra Meel", "Satra Mil"),
])
region("Galiyat", (33.95, 34.25, 73.25, 73.55), "settlement-region", [
    A("Nathiagali", "Nathia Gali"), A("Ayubia"), A("Khanspur"), A("Dunga Gali", "Doonga Gali", "Dongagali"),
    A("Changla Gali", "Changlagali"), A("Thandiani"), A("Khaira Gali", "Khairagali"),
    A("Bara Gali", "Baragali"), A("Kuza Gali", "Kuzagali"), A("Ghora Dhaka", "Ghoradhaka"),
])
region("Abbottabad region", (33.95, 34.35, 73.00, 73.40), "settlement-region", [
    A("Abbottabad"), A("Havelian"), A("Nawanshehr", "Nawan Shehr", "Nawa Shehr"), A("Harnoi"),
    A("Kakul"), A("Sherwan"), A("Bagnotar"), A("Sarban"), A("Dhamtaur", "Dhamtour"), A("Lora"),
])
region("Mansehra region", (34.20, 34.60, 72.90, 73.40), "settlement-region", [
    A("Mansehra"), A("Oghi"), A("Shinkiari"), A("Garhi Habibullah"), A("Baffa"), A("Dhodial"),
    A("Battal"), A("Balakot"), A("Darband"),
])
region("Kaghan Valley", (34.45, 35.20, 73.25, 74.10), "settlement-region", [
    A("Kaghan"), A("Naran"), A("Kiwai"), A("Jared"), A("Batakundi"), A("Besal"), A("Shogran"),
    A("Sharan"), A("Jalkhad"), A("Lalazar"), A("Paras"), A("Mahandri"), A("Siri"), A("Burawai"),
    A("Balakot"),
])
region("Balakot area", (34.45, 34.65, 73.25, 73.45), "settlement-region", [
    A("Balakot"), A("Kawai"), A("Bhogarmang"), A("Ghanool"), A("Paras"),
])

# ---------------------------------------------------------------- Malakand division
region("Swat", (34.55, 35.75, 72.10, 72.95), "settlement-region", [
    A("Mingora"), A("Saidu Sharif"), A("Kalam"), A("Madyan"), A("Bahrain", "Behrain"), A("Matta"),
    A("Khwazakhela", "Khwaza Khela"), A("Fatehpur"), A("Mankial", "Mankyal"), A("Charbagh"),
    A("Barikot"), A("Kabal"), A("Manglawar"), A("Malam Jabba", "Malamjabba"), A("Utror"),
    A("Ushu"), A("Gabral"), A("Miandam"), A("Kanju"), A("Odigram"), A("Sangota"), A("Peochar"),
    A("Shamozai"),
])
region("Malam Jabba area", (34.75, 34.90, 72.45, 72.65), "settlement-region", [
    A("Malam Jabba", "Malamjabba"), A("Kanju"), A("Shamozai"),
])
region("Upper Dir", (35.00, 35.65, 71.60, 72.30), "admin-area", [
    A("Dir"), A("Sheringal"), A("Kalkot"), A("Wari"), A("Barawal"), A("Thal"),
])
region("Lower Dir", (34.55, 35.05, 71.60, 72.30), "admin-area", [
    A("Timergara", "Timargara"), A("Chakdara"), A("Balambat"), A("Munda"), A("Samarbagh"),
    A("Maidan"), A("Jandool", "Jandol"), A("Ouch", "Uch"), A("Lal Qila", "Lal Qilla"), A("Talash"),
    A("Khall"),
])
region("Shangla", (34.70, 35.15, 72.50, 73.00), "admin-area", [
    A("Alpuri"), A("Besham"), A("Chakesar"), A("Puran"), A("Karora"), A("Martung"), A("Kana"),
])
region("Buner", (34.30, 34.70, 72.30, 72.80), "admin-area", [
    A("Daggar"), A("Chamla"), A("Gagra"), A("Totalai"), A("Pir Baba"), A("Chagharzai"),
    A("Gokand"), A("Ambela"), A("Sowari", "Sawari"), A("Elai"),
])
region("Malakand / Bajaur / Mohmand", (34.30, 34.95, 71.20, 72.20), "settlement-region", [
    A("Batkhela"), A("Dargai"), A("Thana"), A("Malakand"), A("Khar"), A("Nawagai"), A("Ghalanai"),
])

# ---------------------------------------------------------------- Chitral / Kohistan / Battagram
region("Lower Chitral", (35.30, 36.00, 71.40, 72.30), "admin-area", [
    A("Chitral"), A("Drosh"), A("Ayun"), A("Arandu"), A("Ashret"), A("Kosht"), A("Ursoon", "Ursun"),
    A("Gahirat"),
])
region("Upper Chitral", (35.90, 36.90, 71.80, 73.10), "admin-area", [
    A("Booni", "Buni"), A("Mastuj"), A("Reshun"), A("Garam Chashma"), A("Mori"), A("Laspur", "Sor Laspur"),
    A("Kuragh"), A("Torkhow"), A("Mulkhow"), A("Broghil"), A("Shoghor"), A("Parwak"), A("Harchin"),
])
region("Kalash Valleys", (35.55, 35.90, 71.55, 71.90), "settlement-region", [
    A("Bumburet", "Bomboret", "Bumboret", "Bumburait"), A("Rumbur", "Rambur"), A("Birir", "Biriu"),
])
region("Kohistan (Upper, Lower, Kolai-Palas)", (34.85, 35.95, 72.60, 73.45), "admin-area", [
    A("Dassu", "Dasu"), A("Pattan"), A("Komila", "Kumila"), A("Kandia"), A("Palas"), A("Jalkot"), A("Duber"),
    A("Seo"), A("Kolai"),
])
region("Battagram", (34.55, 34.95, 72.85, 73.30), "admin-area", [
    A("Battagram"), A("Thakot"), A("Banna"), A("Bateela"), A("Chapargram"),
])
region("Torghar", (34.55, 34.85, 72.85, 73.10), "admin-area", [
    A("Judba", "Judbay", "Judbai"), A("Kandar"),
], note="Torghar is a district; few settlements are named in public gazetteers - low counts expected.")

# ---------------------------------------------------------------- Gilgit-Baltistan
region("Astore", (34.70, 35.65, 74.30, 75.30), "admin-area", [
    A("Astore", "Astor"), A("Gorikot", "Gurikot"), A("Rama"), A("Rattu"), A("Chilim", "Chilam"),
    A("Dashkin"), A("Tarashing", "Tarshing"), A("Minimarg"), A("Bunji"),
])
region("Diamer", (35.10, 36.10, 73.60, 74.80), "admin-area", [
    A("Chilas"), A("Thalpan"), A("Darel"), A("Tangir"), A("Gor"), A("Harban"), A("Thor"), A("Sazin"),
    A("Shatial"), A("Khanbari"), A("Ramghat"), A("Gonar Farm"), A("Babusar"), A("Hodar", "Hodur"),
    A("Raikot"), A("Fairy Meadows", "Fairy Meadow"), A("Tato"),
])
region("Gilgit", (35.60, 36.20, 74.00, 74.80), "settlement-region", [
    A("Gilgit"), A("Jutial"), A("Danyore", "Danyor"), A("Kargah"), A("Bargo"), A("Sultanabad"), A("Juglot"),
    A("Minawar"), A("Naltar"), A("Nomal"), A("Bagrote", "Bagrot"), A("Haramosh"),
    A("Oshikhandas"), A("Sonikot"), A("Barmas"), A("Konodas"), A("Jalalabad"), A("Rahimabad"),
])
region("Hunza", (36.15, 37.10, 74.40, 75.60), "settlement-region", [
    A("Karimabad"), A("Aliabad"), A("Altit"), A("Ganish"), A("Sost"), A("Passu", "Pasu"), A("Gulmit"),
    A("Hussaini"), A("Shishkat"), A("Gojal"), A("Murtazaabad", "Murtazabad"), A("Nasirabad"),
    A("Sikandarabad"), A("Shimshal"), A("Misgar"), A("Ghulkin"), A("Hassanabad"), A("Khyber"),
    A("Gircha"), A("Dorkhan"), A("Ahmadabad"),
])
region("Nagar", (36.10, 36.60, 74.50, 75.20), "settlement-region", [
    A("Nagar"), A("Chalt"), A("Pisan"), A("Hopar", "Hoper"), A("Miar"), A("Sumayar"), A("Nilt"),
    A("Minapin"), A("Ghulmet"), A("Askurdas"), A("Hispar"), A("Garmasai"), A("Shayar"), A("Thol"),
])
region("Ghizer (incl. Gupis-Yasin, Ishkoman, Punial)", (35.80, 37.00, 72.30, 74.20), "admin-area", [
    A("Gahkuch", "Gakuch", "Ghakuch"), A("Gupis"), A("Yasin"), A("Ishkoman"), A("Phander", "Pandar"),
    A("Chatorkhand"), A("Immit"), A("Punial"), A("Sher Qilla", "Sher Qila"), A("Hundrap", "Handrap"),
    A("Barsat"), A("Darkut"), A("Chashi"), A("Singal"), A("Teru"), A("Khalti"), A("Pingal"),
])
region("Skardu", (35.00, 35.60, 75.30, 76.00), "settlement-region", [
    A("Skardu"), A("Kachura"), A("Sadpara", "Satpara"), A("Kuardu"),
])
region("Shigar", (35.30, 36.00, 75.30, 76.30), "admin-area", [
    A("Shigar"), A("Askole", "Askoley"), A("Hoto"), A("Chutron"), A("Basha"), A("Dassu Shigar", "Dusso"),
])
region("Kharmang", (34.60, 35.30, 75.80, 76.70), "admin-area", [
    A("Kharmang"), A("Tolti"), A("Mehdiabad"), A("Olding"), A("Kharkoo", "Kharku"),
])
region("Ghanche (Khaplu valley)", (34.90, 35.70, 76.00, 77.20), "admin-area", [
    A("Khaplu"), A("Hushe"), A("Machulo"), A("Thalay", "Thaley"), A("Saling"), A("Daghoni"), A("Kandey", "Kandi"),
])
region("Roundu (Rondu)", (35.30, 35.90, 74.90, 75.60), "admin-area", [
    A("Rondu", "Roundu"), A("Harchu"), A("Stak"), A("Thurgo"), A("Mendi"),
])
region("Deosai-related settlements", (34.85, 35.30, 75.10, 75.80), "settlement-region", [
    A("Sadpara", "Satpara"), A("Chilim", "Chilam"), A("Astore", "Astor"), A("Skardu"),
], note="Deosai plateau itself is uninhabited; only fringe settlements are expected.")
region("China border belt (Khunjerab-Sost)", (36.40, 37.10, 74.50, 75.60), "settlement-region", [
    A("Sost"), A("Passu", "Pasu"), A("Misgar"), A("Shimshal"), A("Gulmit"), A("Ghulkin"),
    A("Hussaini"), A("Khunjerab"),
])

# ---------------------------------------------------------------- Azad Jammu & Kashmir
region("Neelum Valley", (34.50, 35.15, 73.70, 74.60), "settlement-region", [
    A("Athmuqam", "Athmaqam", "Ath Muqam"), A("Sharda"), A("Keran"), A("Kel"), A("Dawarian"), A("Taobat"),
    A("Kundal Shahi"), A("Nagdar"), A("Lawat"), A("Halmat"), A("Arang Kel", "Arangkel"), A("Jagran"),
    A("Salkhala", "Salkhalla"),
])
region("Muzaffarabad", (34.20, 34.60, 73.20, 73.70), "settlement-region", [
    A("Muzaffarabad"), A("Garhi Dupatta", "Garhi Dopatta"), A("Chakothi"), A("Pattika", "Patika"),
    A("Kohala"), A("Naseerabad"), A("Domel"), A("Chattar"), A("Naluchi"), A("Langarpura"),
    A("Bararkot"), A("Chikar"), A("Ranjata"),
])
region("Hattian Bala / Jhelum Valley", (34.00, 34.40, 73.60, 74.30), "settlement-region", [
    A("Hattian Bala", "Hattian"), A("Leepa"), A("Chinari"), A("Chakothi"),
])
region("Bagh", (33.80, 34.10, 73.60, 74.10), "admin-area", [
    A("Bagh"), A("Dhirkot"), A("Harighel"), A("Arja"), A("Sudhan Gali", "Sudhangali"),
])
region("Rawalakot / Poonch", (33.70, 34.00, 73.60, 74.05), "admin-area", [
    A("Rawalakot"), A("Hajira"), A("Abbaspur"), A("Banjosa"), A("Toli Pir"), A("Khaigala"),
])
region("Haveli", (33.50, 33.85, 73.80, 74.20), "admin-area", [
    A("Forward Kahuta"),
])
region("Sudhanoti", (33.50, 33.85, 73.50, 73.90), "admin-area", [
    A("Pallandri"), A("Trarkhal", "Tarar Khal"), A("Mong"), A("Baloch"),
])
region("Kotli", (33.20, 33.70, 73.70, 74.15), "admin-area", [
    A("Kotli"), A("Fatehpur Thakiala"), A("Nakyal"), A("Sehnsa"), A("Charhoi"), A("Khuiratta"),
    A("Tatta Pani", "Tattapani"), A("Gulpur"),
])
region("Mirpur", (32.90, 33.30, 73.30, 74.05), "admin-area", [
    A("Mirpur"), A("Dadyal"), A("Islamgarh"), A("Chaksawari", "Chak Sawari"), A("Jatlan"),
])
region("Bhimber", (32.75, 33.00, 74.00, 74.35), "admin-area", [
    A("Bhimber"), A("Barnala"), A("Samahni"),
])

# ---------------------------------------------------------------- Hazara plains and NE / India border
region("Haripur / Swabi / Mardan belt", (33.70, 34.40, 72.00, 73.00), "settlement-region", [
    A("Haripur"), A("Tarbela"), A("Ghazi"), A("Khanpur"), A("Swabi"), A("Topi"), A("Mardan"),
    A("Takht Bhai", "Takht-i-Bahi"), A("Katlang"),
])
region("NE border belt (Sialkot-Narowal-Shakargarh)", (32.00, 32.75, 74.00, 75.00), "settlement-region", [
    A("Sialkot"), A("Narowal"), A("Shakargarh"), A("Zafarwal"), A("Pasrur"), A("Daska"), A("Sambrial"),
    A("Chawinda"), A("Kartarpur"),
])
region("Lahore-Kasur border belt", (30.90, 31.70, 74.00, 74.90), "settlement-region", [
    A("Lahore"), A("Wagah"), A("Kasur"), A("Ganda Singh Wala"), A("Raiwind"), A("Chunian"), A("Pattoki"),
])

# Province-level rows are computed in the build script from the GeoNames admin1 code
# (07 = Gilgit-Baltistan, 06 = Azad Jammu and Kashmir, 03 = Khyber Pakhtunkhwa, 08 = Islamabad).
PROVINCE_ROWS = {
    "07": "Gilgit-Baltistan (GeoNames adm1=07)",
    "06": "Azad Jammu and Kashmir (GeoNames adm1=06)",
    "03": "Khyber Pakhtunkhwa (GeoNames adm1=03)",
    "08": "Islamabad Capital Territory (GeoNames adm1=08)",
}

REGIONS = R
