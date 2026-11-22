# Konzultácia 4: Lucene index

Kód: https://github.com/JozefZiduliak/vinf

## Hotový Spark kód

Spark časť je uzavretá jedným novým jobom `src/spark/export_lucene.py`. Spojí `data/animals.jsonl` (4 239 druhov z ADW, všetky atribúty a plný text) s `data/wiki/joined.parquet` (wiki atribúty pre 4 180 druhov) cez `slug` a zapíše jeden JSON súbor pre Lucene.

- Left join: každý ADW druh ostáva v indexe, 59 druhov bez wiki stránky má wiki polia prázdne.
- Nový stĺpec `status`: IUCN kód z Wikipédie, ak chýba, kód z ADW cez tú istú mapu ako v `join.py`. Wikipédia je novšia, ADW dopĺňa medzery.
- Výstup `data/lucene/input.json`, 4 239 riadkov, 18 kľúčov na riadok, 83 MB.

```python
animals = spark.read.json(ANIMALS)
wiki = spark.read.parquet(JOINED).select("slug", *WIKI_COLS, "match")
out = animals.join(wiki, "slug", "left")

adw_code = F.create_map(*[F.lit(x) for kv in ADW_STATUS_CODE.items() for x in kv])
out = out.withColumn(
    "status",
    F.coalesce(F.nullif("wiki_status", F.lit("")), adw_code[F.col("conservation_status")]),
)
out.coalesce(1).write.mode("overwrite").option("ignoreNullFields", False).json(OUTPUT)
```

## Prostredie

PyLucene beží v kontajneri `lucene` (obraz `coady/pylucene:10.0`, Lucene 10.0.0), služba v tom istom `docker-compose.yml` ako Spark. Kontajner má namountované `src/` a `data/`, skripty sa spúšťajú cez `docker compose exec`. Lucene kontajner nemá Spark ani pyarrow, preto je vstup JSON a nie parquet.

```
docker compose up -d lucene
docker compose exec lucene python3 src/lucene/build_index.py
docker compose exec lucene python3 src/lucene/search.py "diet:carnivore AND status:EN"
```

## Návrh indexu: polia a odôvodnenie

Lucene nemá schému v súbore, schéma je zoznam polí, ktoré pridáme do každého dokumentu. Tri typy polí:

- `StringField`: hodnota je jeden presný token, bez analyzéra. Filter, nie ranking.
- `TextField`: hodnota ide cez analyzér (tokenizácia, lowercase, stop slová, stemming), hľadá sa po slovách, skóruje BM25.
- `IntPoint`: číslo v štruktúre pre rozsahové dopyty.

Každé pole má aj príznak stored: uložená hodnota sa vráti vo výsledku, neuložená sa dá len prehľadávať.

| pole | typ | stored | zdroj | prečo |
|---|---|---|---|---|
| `slug` | StringField | áno | ADW | identifikátor dokumentu, presný lookup |
| `scientific_name` | StringField | áno | ADW | presný dopyt `scientific_name:"Panthera leo"` |
| `scientific_name_text` | TextField | nie | ADW | tá istá hodnota po slovách, `panthera` samostatne |
| `common_name` | TextField | áno | ADW | ľudia hľadajú „chinchilla“, nie celé meno |
| `class`, `order`, `family`, `genus` | StringField | áno | ADW taxonómia | filter `family:Felidae`; jedno textové pole by nerozlíšilo rad od čeľade |
| `status` | StringField | áno | wiki, inak ADW | IUCN kód, filter `status:EN` |
| `range`, `habitat`, `diet` | StringField, viac hodnôt | áno | ADW | pevný slovník, jeden dokument má viac hodnôt, každá je samostatný token |
| `text` | TextField | nie | ADW | plný text, hlavné pole pre bežný dopyt; neuložené, 60 MB by zdvojnásobilo index |
| `wiki_title` | TextField | áno | wiki | názov wiki stránky, bežné meno |
| `authority` | TextField | áno | wiki | kto a kedy druh popísal |
| `year` | IntPoint + StoredField | áno | wiki `authority` | rok popisu regexom `\b(1[5-9]\d\d\|20\d\d)\b`, rozsahový dopyt |
| `lead` | TextField | áno | wiki | prvý odsek článku, druhý text na ranking |

Vynechané: `sections` (už sú v `text`), `taxon` (duplikát `scientific_name`), `status_system` (vždy IUCN), `match` (interné z joinu).

Zvažovaná alternatíva: taxonómia ako jedno `TextField` „Mammalia Carnivora Felidae“. Zavrhnuté, lebo dopyt `family:Felidae` potrebuje presný filter a text by matchol aj slovo Felidae v próze.

## Analyzér

Lucene spracúva každé `TextField` cez analyzér, čo je to isté, čo v prvej časti robil náš `tokenizer.py`, zoznam stop slov a voliteľný stemming, len zabalené do jednej triedy. Zvolili sme `EnglishAnalyzer`: tokenizácia, lowercase, anglický zoznam stop slov a Porterov stemmer, takže „lions“ a „lion“ sú jeden term. Zodpovedá to variantu `--stem` nášho indexu z prvej časti, preto je porovnanie starého a nového indexu férové. Analyzér je nastavený v `IndexWriterConfig` pri budovaní a ten istý musí byť použitý pri parsovaní dopytu, inak by sa dopyt „lions“ nestemoval a nenašiel postings pre „lion“. `StringField` cez analyzér nejdú vôbec, ukladajú sa ako jeden presný token.

Na strane dopytu preto používame `PerFieldAnalyzerWrapper`: `EnglishAnalyzer` pre textové polia, `KeywordAnalyzer` (bez zmeny) pre `StringField`. Bez toho by sa `status:EN` zmenilo na `status:en` a nenašlo nič.

## Implementácia indexu (src/lucene/build_index.py)

Schéma je päť zoznamov, `to_document` ich prejde a z jedného JSON riadku vyrobí `Document`.

```python
KEYWORDS = ["slug", "scientific_name", "status"]
RANKS = ["Class", "Order", "Family", "Genus"]
LISTS = ["range", "habitat", "diet"]
TEXTS = ["scientific_name_text", "common_name", "wiki_title", "authority", "lead", "text"]
NOT_STORED = {"text"}

def to_document(row: dict) -> Document:
    doc = Document()
    row["scientific_name_text"] = row["scientific_name"]
    for name in KEYWORDS:
        if row.get(name):
            doc.add(StringField(name, row[name], Field.Store.YES))
    for rank in RANKS:
        if row["taxonomy"].get(rank):
            doc.add(StringField(rank.lower(), row["taxonomy"][rank], Field.Store.YES))
    for name in LISTS:
        for value in row[name] or []:
            doc.add(StringField(name, value, Field.Store.YES))
    for name in TEXTS:
        if row.get(name):
            store = Field.Store.NO if name in NOT_STORED else Field.Store.YES
            doc.add(TextField(name, row[name], store))
    m = YEAR_RE.search(row.get("authority") or "")
    if m:
        year = int(m.group(1))
        doc.add(IntPoint("year", year))
        doc.add(StoredField("year", year))
    return doc
```

```python
config = IndexWriterConfig(EnglishAnalyzer())
config.setOpenMode(IndexWriterConfig.OpenMode.CREATE)
writer = IndexWriter(FSDirectory.open(Paths.get(INDEX)), config)
for line in f:
    writer.addDocument(to_document(json.loads(line)))
writer.commit()
```

`OpenMode.CREATE` prepíše starý index, beh je idempotentný ako ostatné stupne.

| | |
|---|---|
| dokumentov | 4 239 |
| čas budovania | 6 s |
| veľkosť indexu | 11 MB (vstup 83 MB, `text` nie je uložený) |
| `status` vyplnený | 3 986 (253 má v ADW „No special status“, bez IUCN kódu) |
| `year` vyplnený | 4 176 |
| `lead` vyplnený | 3 252 |

## Zapojenie do aplikácie

Starý index: `uv run dev search "<dopyt>" --stem`, beží lokálne v `uv`. Nový index: `docker compose exec lucene python3 src/lucene/search.py "<dopyt>"`, beží v kontajneri, lebo PyLucene potrebuje JVM. Oba vypisujú rovnaký tvar riadku (skóre, slug, bežné meno, rad/čeľaď, status), aby sa dali porovnať vedľa seba. Postup je v `README.md`.

Vyhľadávanie: `QueryParser` prevedie reťazec na strom dopytov, predvolené pole je `text`. Rozsah na `year` sa pridáva prepínačom `--year`, lebo klasický parser nevie, že pole je číselné, a `BooleanQuery` ho spojí s textovým dopytom cez `MUST`.

```python
def build_query(text: str, year: str | None):
    query = QueryParser(DEFAULT_FIELD, query_analyzer()).parse(text)
    if year is None:
        return query
    lo, hi = (int(y) for y in year.split("-"))
    both = BooleanQuery.Builder()
    both.add(query, BooleanClause.Occur.MUST)
    both.add(IntPoint.newRangeQuery("year", lo, hi), BooleanClause.Occur.MUST)
    return both.build()
```

`IndexSearcher` skóruje BM25, `storedFields().document(id)` vráti uložené hodnoty pre výpis.

## Typy dopytov

Spustenie, jeden dopyt na typ:

```
docker compose exec lucene python3 src/lucene/search.py "lions in africa"
docker compose exec lucene python3 src/lucene/search.py "diet:carnivore AND status:EN"
docker compose exec lucene python3 src/lucene/search.py "family:Felidae NOT status:LC"
docker compose exec lucene python3 src/lucene/search.py '"tropical rainforest"'
docker compose exec lucene python3 src/lucene/search.py "cheeta~1"
docker compose exec lucene python3 src/lucene/search.py "family:Felidae" --year 1750-1800
```

| typ | dopyt | ako to Lucene rozparsuje |
|---|---|---|
| Boolean AND | `diet:carnivore AND status:EN` | `+diet:carnivore +status:EN` |
| Boolean OR | `lions in africa` | `text:lion text:africa` (stop slovo `in` vypadlo, `lions` stemované) |
| Boolean NOT | `family:Felidae NOT status:LC` | `+family:Felidae -status:LC` |
| Phrase | `"tropical rainforest"` | `text:"tropic rainforest"`, slová musia byť vedľa seba |
| Fuzzy | `cheeta~1` | `text:cheeta~1`, editačná vzdialenosť 1 |
| Range | `family:Felidae --year 1750-1800` | `+family:Felidae +year:[1750 TO 1800]` |

Fuzzy s predvolenou vzdialenosťou 2 (`cheeta~`) vráti na prvých miestach „red-cheeked“ vtáky, lebo `cheek` je od `cheeta` rovnako ďaleko ako `cheetah`. S `~1` je gepard prvý. Fuzzy zvyšuje recall, nie presnosť.

## Porovnanie: starý index vs. nový index

Starý index: vlastný invertovaný index z prvej časti, TF-IDF, jedno textové pole, `--stem`. Nový: Lucene, BM25, polia. Rovnaké dopyty, prvých päť výsledkov.

**1. `lions in africa`**

| starý index | nový index |
|---|---|
| lion | lion |
| Steller sea lion | African buffalo |
| New Zealand sea lion | leopard |
| Galapagos sealion | spotted hyena |
| cougar | roan antelope |

Starý index váži slovo „lion“ a vracia uškatce (sea lion). BM25 v Lucene má saturáciu TF, dokumenty s oboma slovami vyhrávajú, výsledok je africká savana.

**2. `carnivore endangered`, v Lucene `diet:carnivore AND status:EN`**

| starý index | nový index |
|---|---|
| Snail Darter (Vulnerable) | Bishop ray (EN) |
| Atelopus varius (Critically Endangered) | Flatwoods Salamander (EN) |
| bay cat (Endangered) | Nelson's antelope squirrel (EN) |
| vaquita (Critically Endangered) | Galápagos fur seal (EN) |
| Oophaga lehmanni (Critically Endangered) | Antarctic fur seal (EN) |

Starý index hľadá slovo „endangered“ v texte, prvý výsledok má status Vulnerable. Nový filtruje presne po poliach, všetkých 283 výsledkov má `status:EN` a `diet:carnivore`. Skóre je pre všetky rovnaké, filter nerankuje.

**3. `tropical rainforest` ako fráza**

| starý index | nový index |
|---|---|
| tropical ground squirrel | Indian Cobra |
| Indian Cobra | silvery gibbon |
| silvery gibbon | Oophaga histrionica |
| Green Vine Snake (len rainforest) | Jerdon's palm civet |
| Rhinoderma darwinii (len rainforest) | Amboina Box Turtle |

Starý index nepozná frázu, stačí mu jedno zo slov. Lucene vyžaduje obe slová vedľa seba v tomto poradí, používa pozície v postings.

**4. `cheeta` s preklepom**

| starý index | nový index (`cheeta~1`) |
|---|---|
| žiadny výsledok | cheetah |
| | Thomson's gazelle |
| | Dioctophyma renale |
| | Grant's gazelle |
| | southern reedbuck |

Starý index nájde len presný term. Fuzzy dopyt nájde gepard a ďalej dokumenty, kde sa gepard spomína.

**5. `Felidae`, v Lucene `family:Felidae`**

| starý index | nový index |
|---|---|
| king vulture | cheetah |
| Indian giant squirrel | caracal |
| Diphyllobothrium mansonoides | domestic cat |
| Lagochilascaris minor | jungle cat |
| scarlet ibis | Pallas' cat |

Starý index nájde dokumenty, kde sa slovo Felidae vyskytuje v texte (predátor, hostiteľ parazita), ani jedna mačka v prvej päťke. Nový index vráti presne 41 druhov čeľade Felidae a nič iné.

Zhrnutie: pri bežnom textovom dopyte dávajú oba indexy podobné výsledky, BM25 je o niečo lepší pri viacslovných dopytoch. Rozdiel robia polia: filter, fráza, fuzzy a rozsah starý index nevie vôbec.
