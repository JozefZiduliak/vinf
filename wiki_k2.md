# 2. Konzultácia – Návrh riešenia (K2a)

> Termín 14.10.2026 (idem 05.10.). DokuWiki: `user:jozef.ziduliak:2.konzultacia`.
> Nadpisy = body zadania 1:1.

## Frameworky a knižnice

Python 3.14 (projekt deklaruje `requires-python >= 3.11`, aby bežal aj v PyLucene Docker image v 2. časti), spravovaný cez `uv`. V prvej časti zámerne bez hotových vyhľadávacích knižníc (Lucene, Whoosh, scikit-learn TF-IDF), index a vyhľadávanie píšeme sami podľa zadania.

| Knižnica | Použitie |
|---|---|
| `requests` | HTTP GET s hlavičkami a timeoutom, bez automatického presmerovania (302 = druh bez účtu) |
| `re` (stdlib) | extrakcia odkazov z HTML, neskôr extrakcia atribútov; zadanie vyžaduje regex, nie BeautifulSoup/XPath |
| `urllib.robotparser` (stdlib) | robots.txt: `can_fetch()`, `crawl_delay()` |
| `collections.deque` (stdlib) | fronta BFS, `popleft()` je O(1) |
| `json`, `csv` (stdlib) | checkpoint (`crawler.json`), metadáta (`metadata.tsv`); textové súbory namiesto databázy |
| `pathlib`, `logging`, `time`, `datetime` (stdlib) | súbory, log, delay, časové značky |

Neskôr: `pydantic` pre záznamy (`Animal`), v 2. časti PySpark a PyLucene.

## Architektúra crawlera

{{user:jozef.ziduliak:crawler_hld.png?700}}

(zdroj: `docs/crawler_hld.mmd`, Mermaid; detailný flowchart jednej iterácie v `docs/crawler_flow.mmd`)

Crawler je BFS prechod taxonomického stromu Animal Diversity Web. Navigačné (klasifikačné) stránky sa spracúvajú do šírky, účty druhov (listy stromu) majú prednosť, sťahujú sa hneď po objavení. Stav drží v dvoch štruktúrach: fronta `deque` (URL na spracovanie) a množina `seen` (všetky URL, ktoré boli kedy zaradené, bráni duplicitám a cyklom cez odkazy na predkov). Jedna iterácia:

1. vyber URL z fronty, over `robots.txt` (`can_fetch`),
2. stiahni (GET, hlavičky, timeout 15 s, 3 pokusy, bez presmerovaní),
3. ak je to klasifikačná stránka: regexom vyber odkazy (cesta, rank, príznak `feature-less`); prázdne podstromy (`feature-less`) orež bez requestu; druhy preveď na URL účtu a zaraď na začiatok fronty; ostatné taxóny zaraď na koniec,
4. ak je to účet druhu (status 200): ulož HTML do `data/raw/<Genus_species>.html`,
5. každú URL zapíš do `metadata.tsv`, na konci iterácie ulož checkpoint (fronta + seen) atomicky cez dočasný súbor a `os.replace`.

Pri štarte sa checkpoint načíta, takže crawler pokračuje presne tam, kde skončil. Reálne bežal na Raspberry Pi 4 v `tmux` cez tri dni s viacerými prerušeniami.

Tri typy URL:

| URL | Čo s ňou |
|---|---|
| `/accounts/<Taxón>/classification/` | stiahnuť, extrahovať odkazy, HTML neukladať |
| `/accounts/<Genus_species>/` | stiahnuť, uložiť ako dokument |
| ostatné (`/pictures/`, `/specimens/`, `/search/`, …) | regex ich nikdy nevyberie |

### Kľúčové zistenie: strom je oveľa väčší než počet účtov

Druh bez účtu vráti pre `/accounts/<Genus_species>/` presmerovanie 302 na klasifikačnú stránku. Preto `allow_redirects=False`: 200 = účet, 302 = nič. Strom navyše označuje uzly bez akéhokoľvek obsahu triedou `<div class="feature-less">`, a to na každej úrovni (druh, rod, čeľaď). Prvý beh bez orezávania prešiel za 14 h 6 000 klasifikačných stránok a našiel 120 účtov. Po pridaní orezávania `feature-less` podstromov sa ~195 000 uzlov preskočilo bez requestu a celý strom sa prešiel za ~30 h.

## Hlavičky, timeout, sleep

```python
CONTACT_EMAIL = "xziduliak@stuba.sk"
USER_AGENT = f"vinf-crawler/0.1 (FIIT STU student project; {CONTACT_EMAIL})"
HEADERS = {"User-Agent": USER_AGENT, "From": CONTACT_EMAIL, "Accept": "text/html"}
TIMEOUT = 15
DELAY_SECONDS = 8      # fallback, reálne sa číta z robots.txt
MAX_RETRIES = 3
```

- **User-Agent** identifikuje bota, projekt a kontakt, aby správca stránky vedel, kto a prečo, a mohol napísať namiesto blokovania. `From` to isté v štandardnej hlavičke. `Accept: text/html` hovorí, že nechceme obrázky ani JSON.
- **Sleep 8 s** nie je naša voľba, je to `Crawl-delay: 8` z `https://animaldiversity.org/robots.txt`, načítané cez `RobotFileParser.crawl_delay()`. Spí sa po každom requeste, aj neúspešnom. Pri ~17 000 requestoch to znamená ~38 h čistého behu, preto checkpoint a Raspberry Pi.
- **Timeout 15 s**: bežná odpoveď servera je pod 1 s, 15 s je jednoznačne porucha, nie pomalosť. Bez timeoutu by `requests.get` pri výpadku visel donekonečna.
- **Retry 3×** len pri sieťovej chybe alebo 5xx. Pri 404 a 302 sa neopakuje, výsledok sa nezmení.
- **`robots.txt`**: `/accounts/` nie je zakázaný; zakázané sú `/mousetrap/`, `/workspaces/`, `/quaardvark/search/` a pod. Každá URL ide pred requestom cez `can_fetch()`.

## Implementácia crawlera + stiahnuté stránky

Kód: `src/crawler.py` (GitHub: <!-- link -->). Spúšťanie `uv run dev crawl`, resume automaticky z `checkpoints/crawler.json`.

Extrakcia URL z HTML (regex, reálny kód):

```python
LINK_RE = re.compile(
    r'<div ?(class="feature-less")?>\s*(?:<span>\w+</span>)?\s*'
    r'<a href="(/accounts/[A-Za-z_]+/classification/)" class="taxon-link rank--(\w+)"'
)

def extract_links(html: str) -> list[tuple[str, str, str]]:
    return list(dict.fromkeys(LINK_RE.findall(html)))
```

Stav crawlu k 03.10.2026 (celý strom prejdený, fronta prázdna):

| | |
|---|---|
| requestov spolu | 16 551 |
| klasifikačné stránky (navigácia) | 7 597 |
| **účty druhov uložené (200)** | **4 239** |
| druhy len s fotografiami, bez účtu (302) | 4 715 |
| uzly orezané bez requestu (`feature-less`) | 194 800 (132k druhov, 60k rodov, 2,6k čeľadí, …) |
| veľkosť `data/raw/` | 295 MB, priemer 70 KB / súbor |
| čistý text po odstránení HTML | 58 MB, 9,0 M slov, medián 2 045 slov / dokument |
| trvanie | 26.09. – 28.09. + retry 03.10., Raspberry Pi 4 |

Oficiálna stránka ADW uvádza 2 150 účtov; údaj je nezmenený od roku 2014. Reálny počet je 4 239.

Ukážka `metadata.tsv` (posledné riadky):

```
url	type	status	timestamp	size	file
/accounts/Lycorma_meliae/classification/	pruned_species		2026-10-03T13:02:07	0	
/accounts/Lycorma_delicatula/	species	200	2026-10-03T13:02:16	64162	data/raw/Lycorma_delicatula.html
/accounts/Panthera_leo/	species	200	2026-09-27T21:22:27	114255	data/raw/Panthera_leo.html
/accounts/Panthera/classification/	classification	200	2026-09-27T21:21:53	15569	
```

Ukážky stiahnutých stránok: `data/raw/Panthera_leo.html` (114 KB, 18 sekcií), `data/raw/Ornithorhynchus_anatinus.html`, `data/raw/Thelotornis_kirtlandii.html` (22 KB, najkratší účet, 12 sekcií).

<!-- TODO pred publikovaním: GitHub link, obrázok diagramu -->
