# 3. Konzultácia – Spracovanie veľkých dát (Spark, Wikipedia)

> Termín 11.11.2026. DokuWiki: `user:jozef.ziduliak:3.konzultacia`.
> Nadpisy = body zadania 1:1.

Kód: https://github.com/JozefZiduliak/vinf, branch `feat/spark`, adresár `src/spark/`.

## Rozšírenie kódu z prvého odovzdania na Spark

### Prostredie

Spark beží v Dockeri, obraz `apache/spark:4.2.1-python3` (Spark 4.2.1, Java 21, Python 3.10). Lokálne nemáme Javu v podporovanej verzii, preto Spark beží v kontajneri a prvá časť ostáva v `uv`. Jediný `docker-compose.yml`:

```yaml
services:
  spark:
    image: apache/spark:4.2.1-python3
    working_dir: /app
    volumes:
      - ./src:/app/src
      - ./data:/app/data
    ports:
      - "4040:4040"
    environment:
      PYSPARK_PYTHON: python3
      PYTHONPATH: /app
      PATH: /opt/spark/bin:/opt/java/openjdk/bin:/usr/local/bin:/usr/bin:/bin
    mem_limit: 5g
    cpus: 6
    command: sleep infinity
```

Kontajner stojí, joby sa spúšťajú cez `docker compose exec spark spark-submit --driver-memory 3g src/spark/<job>.py`. Mount `src` a `data` znamená, že úprava kódu nevyžaduje rebuild a výstupy pristanú na disku hostiteľa.

Stroj: MacBook, 16 GB RAM, 10 jadier. Prvé nastavenie bolo priveľké: OrbStack VM 11 GB, kontajner 10 GB, `--driver-memory 7g`. Prvý plný beh som omylom spustil dvakrát (prvý pokus ostal visieť na stdin, druhý ho mal nahradiť, ale proces v kontajneri bežal ďalej) a k tomu bol otvorený `pyspark` shell s 2 GB. Tri JVM si pýtali 16 GB na 16 GB stroji, macOS začal swapovať a zamrzol. Pritom jeden beh mal v tom čase len 2,8 GB RSS, XML reader číta stránku po stránke a dump nedrží v pamäti. V lokálnom režime je driver aj executor jeden proces, takže `--driver-memory` je celý heap Sparku. Nové nastavenie: VM 6 GB, kontajner `mem_limit: 5g` a `cpus: 6`, heap 3 GB, jedna úloha naraz. Zvyšné 2 GB kontajnera sú pre off-heap pamäť JVM, Python workery a OS. Menej jadier znamená menej súbežných taskov a každý task drží bz2 dekompresor, rozparsovanú stránku a bufer Parquet writera.

### Spoločná session (`src/spark/session.py`)

```python
def get_spark(app_name: str) -> SparkSession:
    return (
        SparkSession.builder.appName(app_name)
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", "16")
        .getOrCreate()
    )
```

`shuffle.partitions` znížené z 200 (hodnota pre klaster) na 16, pri lokálnom behu je 200 partícií len réžia. V klastri sa zmení iba `master`.

### Parser z prvej časti ako Spark job (`src/spark/parse_html.py`)

Tie isté regexy ako v `src/parser.py` (importované, `.pattern`), ale namiesto Python cyklu cez súbory beží `regexp_extract` nad DataFrame:

```python
pages = spark.read.text("data/raw/*.html", wholetext=True).select(
    F.input_file_name().alias("path"), F.col("value").alias("html")
)
animals = pages.select(
    slug.alias("slug"),
    F.regexp_extract(html, p.SCIENTIFIC_NAME_RE.pattern, 1).alias("scientific_name"),
    F.map_from_arrays(
        F.regexp_extract_all(html, F.lit(p.TAXONOMY_RE.pattern), 1),
        F.regexp_extract_all(html, F.lit(p.TAXONOMY_RE.pattern), 2),
    ).alias("taxonomy"),
    F.regexp_extract(html, "(?s)" + p.IUCN_RE.pattern, 1).alias("conservation_status"),
    ...
)
animals.write.mode("overwrite").parquet("data/spark/animals.parquet")
```

Rozdiely Java regex vs Python `re`, ktoré bolo treba riešiť: `re.DOTALL` je prefix `(?s)`, odkaz na skupinu v náhrade je `$1`, nie `\1`. Žiadne Python UDF ani `mapPartitions`: regex beží v JVM, dáta neprechádzajú cez socket do Pythonu.

Overenie: výstup sa spojí s `animals.jsonl` z prvej časti cez `slug` a porovnajú sa `scientific_name`, `conservation_status`, rád a diéta. Výsledok: 4 239 z 4 239 záznamov zhodných vo všetkých štyroch poliach, beh 13,2 s (prvá časť: 4 239 súborov v Python cykle ~40 s). Na 290 MB HTML to Spark nepotrebuje, ale ten istý kód by bežal nad 290 GB bez zmeny.

## Extrakcia a spracovanie dát (vrátane wiki dumpu) pomocou Sparku

### Dump

`enwiki-20261001-pages-articles` (aktuálna verzia každej stránky, bez histórie, bez diskusií): 27 logických častí rozdelených na 71 súborov bz2, spolu 24,0 GiB. Novší dump 20261101 ešte nebol dokončený. Oficiálny server škrtí na 3 spojenia a ~0,5 MB/s, stiahnuté z oficiálneho zrkadla `wikipedia.mirror.pdapps.org` (5 až 7 MB/s na spojenie) za 1 h 33 min cez `xargs -P3 curl -C - --retry-all-errors`. Integrita overená proti `enwiki-20261001-md5sums.txt`, 71/71 súborov sedí. Súbory sú pod `data/`, git ich nevidí.

### Čítanie dumpu (`src/spark/wiki_extract.py`)

Spark 4 má natívny XML zdroj. `rowTag = page` spraví z každého elementu `<page>` jeden riadok, vnorené elementy sú `struct`, atribúty dostanú prefix `_`:

```python
pages = spark.read.format("xml").option("rowTag", "page").load("data/wiki/dump/*.bz2")
articles = pages.filter(F.col("ns") == 0).select(
    F.col("title"),
    F.col("redirect._title").alias("redirect_to"),
    F.col("revision.text._VALUE").alias("text"),
)
redirects = articles.filter(F.col("redirect_to").isNotNull()).select("title", F.col("redirect_to").alias("target"))
species = articles.filter(F.col("redirect_to").isNull() & F.col("text").rlike(TAXOBOX_RE))
```

XML zdroj bz2 nedelí, jeden súbor = jeden task, paralelizmus je po súboroch (71 súborov na 6 jadier).

Výstup sú dve tabuľky v Parquete: `species.parquet` (stránky s taxonomickým infoboxom a extrahované polia) a `redirects.parquet` (title → target). Parquet preto, že si pamätá schému a typy, je stĺpcový (join číta len `title` a `taxon`, nie text) a číta sa v sekundách, kým dump v desiatkach minút. Všetko po extrakcii (join, štatistiky, ladenie) beží nad Parquetom.

### Štatistika plného behu

| | počet |
|---|---|
| stránky v dumpe (`<page>`) | 25 932 290 |
| z toho v mennom priestore článkov (`ns = 0`) | 19 314 502 |
| z toho redirecty | 12 065 403 (62 %) |
| z toho články s obsahom | 7 249 099 |
| stránky s taxonomickým infoboxom | 480 924 |
| z toho s binomickým menom (druhy) | 389 842 |
| z toho s trojslovným menom (poddruhy) | 1 539 |
| bez vedeckého mena (regex nenašiel) | 0 |
| čas behu (3 prechody: schéma, redirecty, druhy) | 37 min |

Čísla sú z tretieho plného behu. Výstup: `species.parquet` 24 MB, `redirects.parquet` 374 MB. Prvý plný beh bez `(?i)` našiel 445 994 taxónov, oprava veľkosti písmen pridala 35 tisíc stránok.

Pre porovnanie súbor 1 (najstaršie stránky, 286 MB): 27 352 stránok, 27 151 článkov, 6 233 redirectov (23 %), 310 taxónov, 97 druhov, 0 bez mena.

## Práca s wiki dátami pomocou regexov

Stránka druhu má v wikitexte šablónu infoboxu, napr. Lion:

```
{{Speciesbox
| name = Lion
| status = VU
| status_system = IUCN3.1
| taxon = Panthera leo<ref name=MSW3>{{MSW3 Carnivora |id=14000228 ...}}</ref>
| authority = ([[Carl Linnaeus|Linnaeus]], [[10th edition of Systema Naturae|1758]])<ref name="Linn1758" />
}}
The '''lion''' ('''''Panthera leo''''') is a large [[Felidae|cat]] of the genus ''[[Panthera]]''...
```

Pravidlo relevancie: stránka je taxón, ak obsahuje jednu zo štyroch šablón (`Template:Speciesbox` a sesterské šablóny podľa dokumentácie na Wikipédii). Druh, ak jej meno je binomické (dve slová, prvé veľkým).

```python
TAXOBOX_RE = r"(?i)\{\{\s*(Speciesbox|Taxobox|Automatic taxobox|Subspeciesbox)"

def field_re(name: str) -> str:
    """Value of an infobox line '| <name> = ...', up to the first <, {, | or end of line."""
    return rf"(?m)^\s*\|\s*{name}\s*=\s*([^<{{|\n]+)"

TAXON_RE = field_re("taxon")
BINOMIAL_RE = field_re("binomial")
TRINOMIAL_RE = field_re("trinomial")
GENUS_RE = field_re("genus")
SPECIES_FIELD_RE = field_re("species")
SUBSPECIES_RE = field_re("subspecies")
STATUS_RE = field_re("status")
STATUS_SYSTEM_RE = field_re("status_system")
AUTHORITY_RE = r"(?m)^\s*\|\s*authority\s*=\s*(.*)$"
LEAD_RE = r"(?m)^([A-Za-z][^\n]*'''[^\n]*)$"
```

`TAXOBOX_RE` je filter relevancie: stránka bez jednej zo štyroch šablón ide preč. `field_re` je továreň na regexy: polia infoboxu majú rovnaký tvar `| pole = hodnota`, líšia sa len názvom, tak jedna šablóna s dosadeným názvom nahradí osem ručne písaných regexov. `(?m)^` kotví na začiatok riadku, `\s*\|\s*taxon\s*=\s*` je rúra, názov a rovná sa s ľubovoľnými medzerami, skupina 1 je hodnota. Čo vráti na typických riadkoch:

| riadok infoboxu | skupina 1 | prečo |
|---|---|---|
| `\| taxon = Panthera leo<ref>...</ref>` | `Panthera leo` | zastaví na `<` |
| `\| genus = ''[[Panthera]]''` | `''[[Panthera]]''` | `'` a `[` nie sú hranice, dočistí `clean_name` |
| `\| status = EX {{extinct\|1955}}` | `EX ` | zastaví na `{`, medzeru zoberie `trim` |
| `\| status_system = IUCN3.1` pre `field_re("status")` | nič | po `status` nasleduje `_`, nie `=` |
| `\| taxon = ` | `""` | `+` chce aspoň jeden znak, `regexp_extract` dá prázdny reťazec |

`AUTHORITY_RE` berie celý zvyšok riadku `(.*)$`, lebo autorita `([[Carl Linnaeus|Linnaeus]], [[...|1758]])` obsahuje `|` a `[` uprostred odkazov a hranice z `field_re` by ju odsekli; odkazy a `<ref>` odstráni až `clean_wikitext`. `LEAD_RE` chytí prvý riadok, ktorý začína písmenom a má tučné písmo `'''`: riadky infoboxu začínajú `|` alebo `{`, prvý odsek článku začína písmenom a má tučný názov.

Negovaná trieda `[^<{|\n]+` zastaví hodnotu pred `<ref>`, vnorenou šablónou alebo ďalším poľom, takže `taxon` leva dá `Panthera leo` a nie `Panthera leo<ref name=MSW3>...`. Vedecké meno je v infoboxe zapísané štyrmi spôsobmi: `taxon = Panthera leo` (Speciesbox), `trinomial = ''Alces alces caucasicus''` (starý Taxobox, poddruh), `binomial = ''Panthera leo''` (starý Taxobox, druh), alebo `genus = Orycteropus` + `species = afer` + prípadne `subspecies` (Aardvark, Subspeciesbox). Berie sa prvý neprázdny v tomto poradí, `trinomial` pred `binomial`, lebo stránka poddruhu má často obe a potrebujeme trojslovné meno. `trim` odstráni medzeru na konci, keď je `subspecies` prázdne (`concat_ws` preskakuje NULL, nie prázdny reťazec):

```python
species = species.withColumn(
    "taxon",
    F.when(F.col("taxon") != "", F.col("taxon"))
    .when(F.col("trinomial") != "", F.col("trinomial"))
    .when(F.col("binomial") != "", F.col("binomial"))
    .otherwise(F.trim(F.concat_ws(" ", "genus", "species_epithet", "subspecies"))),
)
```

`authority` a úvodná veta obsahujú wiki značky, čistia sa reťazcom `regexp_replace` (ref, šablóny, `[[cieľ|text]]` → text, `[[cieľ]]` → cieľ, kurzíva):

```python
def clean_wikitext(col):
    col = F.regexp_replace(col, r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "")
    col = F.regexp_replace(col, r"\{\{[^{}]*\}\}", "")
    col = F.regexp_replace(col, r"\[\[[^\]|]*\|([^\]]*)\]\]", "$1")
    col = F.regexp_replace(col, r"\[\[([^\]]*)\]\]", "$1")
    col = F.regexp_replace(col, r"'{2,}", "")
    return F.trim(col)
```

Výsledok pre leva: `taxon = Panthera leo`, `status = VU`, `status_system = IUCN3.1`, `authority = (Linnaeus, 1758)`, `lead = The lion (Panthera leo) is a large cat of the genus Panthera, currently ranging only in Sub-Saharan Africa and India...`.

Regexy sa ladili iteratívne podľa čísel, nie podľa pocitu. Dve opravy, každú odhalil iný typ kontroly:

1. `Asparagales` mal prázdne meno, lebo riadok začína medzerou (` | taxon = Asparagales`). Odhalil to zoznam prázdnych mien. Oprava `^\|` → `^\s*\|`.
2. Po prvom plnom behu chýbali v tabuľke taxónov známe druhy (American alligator, Addax, Great reed warbler), hoci redirecty na ne existovali. Odhalil to zoznam nespárovaných po joine. V dumpe majú `{{speciesbox` malým písmenom, Wikipédia nerozlišuje veľkosť prvého písmena šablóny. Oprava: `(?i)` na začiatku `TAXOBOX_RE`.

Ručná kontrola (gold): Lion, Tiger, Aardvark, Aardwolf proti Wikipédii, 4/4 správne vo všetkých poliach. Vzorky wikitextu sú v `data/wiki/samples/`.

## Join: logika a zdôvodnenie (`src/spark/join.py`)

Kľúč je vedecké meno, normalizované (`lower`, `trim`). Je to jediný identifikátor spoločný pre ADW a Wikipédiu: bežné mená sú nejednoznačné (ADW „lion“, wiki „Lion“, ale aj „Mountain lion“), URL slug ADW (`Panthera_leo`) je odvodený z vedeckého mena. Prečo join: obe strany sú tabuľky s tým istým kľúčom, Spark ich spojí v jednom kroku. Cyklus „pre každé zviera hľadaj v dumpe“ by bol 4 239 prechodov cez 24 GB. Join má dva stupne:

```python
def join_direct(animals: DataFrame, species: DataFrame) -> DataFrame:
    # one_page_per_name: jedna wiki stránka na meno
    return animals.join(one_page_per_name(species), "key", "inner").withColumn(
        "match", F.lit("direct")
    )


def join_via_redirect(
    animals: DataFrame, species: DataFrame, redirects: DataFrame
) -> DataFrame:
    redirects = redirects.select(
        norm("title").alias("key"), F.col("target").alias("wiki_title")
    )
    by_title = species.drop("key")
    return (
        animals.join(redirects, "key", "inner")
        .join(by_title, "wiki_title", "inner")
        .withColumn("match", F.lit("redirect"))
    )


def join_all(animals: DataFrame, species: DataFrame, redirects: DataFrame) -> DataFrame:
    direct = join_direct(animals, species)
    rest = animals.join(direct.select("slug"), "slug", "left_anti")
    via = join_via_redirect(rest, species, redirects)
    cols = [
        "slug",
        "scientific_name",
        "common_name",
        "adw_status",
        "adw_status_code",
        *WIKI_COLS,
        "match",
    ]
    return direct.select(cols).unionByName(via.select(cols)).dropDuplicates(["slug"])
```

1. **Priamo**: `animals.scientific_name == species.taxon`. Stránka Lion má v infoboxe `taxon = Panthera leo`, to je väčšina zhôd.
2. **Cez redirect**, len pre zvieratá bez priamej zhody: ADW používa staršie meno (`Nyctea scandiaca`), wiki stránka Snowy owl má po preradení rodu `taxon = Bubo scandiacus`, ale existuje redirect `Nyctea scandiaca → Snowy owl`. Join `animals.scientific_name == redirects.title`, potom `redirects.target == species.title`.
3. **Spojenie stupňov** (`join_all`): `left_anti` join zvierat so zoznamom slugov z priameho stupňa vráti zvieratá, ktoré priamo nenašli nič (ako `NOT IN`, nepridáva stĺpce). Len tie idú do redirect stupňa, takže zviera nedostane dve stránky. Výsledky oboch stupňov sa spoja cez `unionByName` (stĺpce podľa mena, nie poradia) a `dropDuplicates(["slug"])` je poistka, keby zviera malo viac redirectov na tú istú stránku.

Druhý stupeň na snežnej sove, len stĺpce, ktoré join použije. Vstup: zviera bez priamej zhody (`nyctea scandiaca` sa nerovná žiadnemu `taxon`, wiki má `Bubo scandiacus`), tabuľka redirectov (`title` → `key`, `target` → `wiki_title`) a tabuľka taxónov bez kľúča.

| animals: slug | scientific_name | key |
|---|---|---|
| Nyctea_scandiaca | Nyctea scandiaca | nyctea scandiaca |

| redirects: key | wiki_title |
|---|---|
| nyctea scandiaca | Snowy owl |
| alces americanus | Moose |

| species: wiki_title | taxon | wiki_status | authority |
|---|---|---|---|
| Snowy owl | Bubo scandiacus | VU | (Linnaeus, 1758) |
| Moose | Alces alces | LC | (Linnaeus, 1758) |

Krok 1, `animals ⋈ redirects` na `key`: sova dostane `wiki_title = Snowy owl`, čiže názov článku, na ktorý jej meno presmeruje. Krok 2, výsledok `⋈ species` na `wiki_title`: článok Snowy owl sa nájde v tabuľke taxónov a sova dostane `wiki_status`, `authority`, `lead`. Kľúč sa medzi krokmi mení: prvý porovnáva ADW meno s Wikipédiou (preto `norm` na oboch stranách), druhý porovnáva Wikipédiu s Wikipédiou (presný titul, bez normalizácie).

| výsledok: slug | key | wiki_title | taxon | wiki_status | authority | match |
|---|---|---|---|---|---|---|
| Nyctea_scandiaca | nyctea scandiaca | Snowy owl | Bubo scandiacus | VU | (Linnaeus, 1758) | redirect |

## Koľko unikátnych wiki stránok sme pripojili

| | počet |
|---|---|
| druhov z ADW | 4 239 |
| spojených priamo cez `taxon` | 3 716 |
| spojených cez redirect | 464 |
| spolu (podiel) | 4 180 (98,6 %) |
| unikátnych wiki stránok | 4 173 |
| nespárovaných | 59 |

Nie všetko sa podarilo spojiť: 59 zvierat ostalo bez wiki stránky, väčšinou bezstavovce a parazity bez bežného mena, ktoré na Wikipédii stránku nemajú. Sedem ADW druhov zdieľa wiki stránku s iným druhom (wiki ich zlúčila), preto je unikátnych stránok 4 173 a nie 4 180.

## Aké atribúty z wiki sú pre nás zaujímavé

| atribút | pole v infoboxe | prečo |
|---|---|---|
| vedecké meno | `taxon`, alebo `genus` + `species` | kľúč joinu, bez neho nič |
| IUCN status | `status`, `status_system` | často novší než ADW, dá sa porovnať a vyhľadávať (`status:EN`) |
| autorita | `authority` | kto a kedy druh opísal, ADW nemá, nové fieldové pole v Lucene (`authority:Linnaeus`) |
| úvodná veta | prvý riadok s `'''` | ďalší fulltext a alternatívne bežné mená (`aardvark`, `ant bear`) |
| titul stránky | `title` | bežné meno podľa Wikipédie, odkaz na stránku |

## Poznámky k behu

- Plný beh: 37 až 38 min, 6 jadier, driver 3 GB, pamäť kontajnera pri meraní 0,7 až 1,1 GB z limitu 5 GB. Join nad Parquetom 13 s, parse HTML 13 s.
- Spark UI (`localhost:4040`), záložka Stages počas plného behu: jeden task na súbor dumpu, 6 bežia naraz.
- Kontajner: `docker/spark/Dockerfile` = oficiálny obraz + `pydantic`, lebo `parse_html.py` importuje regexy z `src/parser.py`, ktorý ho potrebuje pre model `Animal`.
- Ďalej (K4): schéma dumpu natvrdo (ušetrí jeden prechod), export `joined.parquet` do JSONL pre Lucene.
