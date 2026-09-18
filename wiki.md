# 1. Konzultácia – Výber a potvrdenie projektu + dáta

## Opis projektu

Cieľom projektu je vyhľadávač živočíšnych druhov. Dáta získame crawlovaním Animal Diversity Web (animaldiversity.org), kde má každý z 2 150 druhov stránku s jednotnou šablónou. Z každej stránky regexom extrahujeme 5 atribútov (taxonómia, geografický rozsah, habitat, potrava, stav ohrozenia) a plný text opisu, nad tým postavíme vlastný invertovaný index a vyhľadávanie s TF-IDF. Používateľ zadá voľný text (napr. „nocturnal desert rodent") a dostane zoradený zoznam druhov s ich atribútmi. V druhej časti semestra záznamy spojíme cez vedecké meno s článkami z anglickej Wikipédie (Spark nad dumpom) a index prebudujeme v PyLucene.

Motivácia: dáta o druhoch sú roztrúsené v dlhých textoch a na stránke sa dajú prehľadávať len cez taxonómiu alebo presné meno. Chceme sa pýtať na vlastnosti („mäsožravec v Afrike, ohrozený") a dostať druhy, ktoré im zodpovedajú.

## Scrapované stránky

Doména: https://animaldiversity.org (Animal Diversity Web, University of Michigan).

Pre túto stránku sme sa rozhodli, pretože stránky jednotlivých živočíchov používajú čisté HTML s jednotnou šablónou sekcií (Geographic Range, Habitat, Food Habits, Conservation Status, ...), takže sa dajú spracovať regexom bez JavaScriptu. Stránka poskytuje 2 150 účtov druhov a 350 účtov vyšších taxónov (taxón = ľubovoľná pomenovaná skupina v klasifikácii, napr. trieda Mammalia, rad Carnivora, rod Panthera), pri ~114 KB na stránku je to približne 245 MB surového HTML. Živočíchy sú usporiadané do stromovej štruktúry, čo nám umožňuje vytvoriť celkom jednoduché pravidlá, ako sa k nim dostať. Stránka povoľuje scrapovanie v robots.txt (cesta `/accounts/` nie je zakázaná), avšak v pravidlách má napísané `Crawl-delay: 8`, čiže medzi požiadavkami budeme čakať 8 sekúnd. Bot ochranu (Cloudflare a pod.) stránka nemá.

**Ako sa dostaneme k stránkam druhov.** Najvyšší uzol stromu je https://animaldiversity.org/accounts/Animalia/classification/ . Každý uzol má klasifikačnú stránku `/accounts/<Taxón>/classification/`, na ktorej je cesta od koreňa až k danému uzlu (jeho predkovia) a zoznam jeho priamych potomkov. Každý odkaz v strome nesie v HTML triede svoj rank, napr. `class="taxon-link rank--Genus"`. Pri prechode stromom môžeme pri každom odkaze naraziť na tieto prípady:

  * odkaz je predok alebo uzol, ktorý sme už videli: preskočíme ho (zoznam navštívených URL), inak by sme sa točili dokola,
  * odkaz má triedu `rank--Species`: ide o konkrétneho živočícha, list stromu. Z URL `/accounts/Panthera_leo/classification/` odstránime `classification/` a dostaneme účet druhu `/accounts/Panthera_leo/`, ten stiahneme a uložíme ako dokument,
  * odkaz má akýkoľvek iný rank (Class, Order, Family, Genus, Unspecified, ...): ide o vnútorný uzol, jeho klasifikačnú stránku pridáme do fronty na prejdenie, HTML neukladáme.

Ostatné podstránky (`/pictures/`, `/specimens/`, `/sounds/`, `/search/`) ignorujeme.

Príklady:

  * vnútorný uzol s potomkami-druhmi: https://animaldiversity.org/accounts/Panthera/classification/ (predkovia Animalia ... Felidae, deti Panthera leo, onca, pardus, tigris),
  * účet druhu, teda dokument, ktorý indexujeme: https://animaldiversity.org/accounts/Panthera_leo/ ,
  * účet druhu z inej triedy s rovnakou šablónou: https://animaldiversity.org/accounts/Ornithorhynchus_anatinus/ .

**Zaujímavé dáta.** Z každého účtu druhu extrahujeme 5 atribútov a plný text. Okrem voľného textu má stránka aj štruktúrované štítky (Biogeographic Regions, Habitat Regions, Terrestrial Biomes, Primary Diet, IUCN Red List), ktoré sú pre atribúty presnejšie než text.

| Atribút | Odkiaľ na stránke | Príklad (Panthera leo, lev) |
|---|---|---|
| taxonómia (trieda / rad / čeľaď / rod) | strom Classification, `rank--Class` ... `rank--Genus` | Mammalia / Carnivora / Felidae / Panthera |
| geografický rozsah | štítky Biogeographic Regions + sekcia Geographic Range | ethiopian, palearctic; sub-Saharan Africa, Gir Forest (India) |
| habitat | štítky Terrestrial Biomes + sekcia Habitat | savanna or grassland, forest, scrub forest, mountains |
| potrava | štítok Primary Diet + sekcia Food Habits | carnivore; ungulates |
| stav ohrozenia | štítok IUCN Red List v sekcii Conservation Status | Vulnerable |
| bežný názov (navyše) | `<title>` a zátvorka v strome | lion |
| plný text | všetky sekcie účtu | ... |

## Wikipedia

K našim záznamom budeme pripájať články o druhoch z anglickej Wikipédie. V druhej časti semestra ich nebudeme sťahovať online, ale spracujeme offline dump `enwiki-latest-pages-articles.xml.bz2` (~22 GB) pomocou Apache Spark.

Príklady párov stránok, ktoré chceme spojiť:

| Animal Diversity Web | Wikipedia |
|---|---|
| https://animaldiversity.org/accounts/Panthera_leo/ | https://en.wikipedia.org/wiki/Panthera_leo (presmeruje na Lion) |
| https://animaldiversity.org/accounts/Melopsittacus_undulatus/ | https://en.wikipedia.org/wiki/Melopsittacus_undulatus (presmeruje na Budgerigar) |
| https://animaldiversity.org/accounts/Ornithorhynchus_anatinus/ | https://en.wikipedia.org/wiki/Ornithorhynchus_anatinus (presmeruje na Platypus) |

Kľúčom na spojenie je vedecké meno druhu. Wikipedia má článok pod bežným názvom (Lion), vedecké meno je len presmerovanie, preto budeme v dumpe párovať cez vedecké meno v infoboxe `{{Speciesbox}}` (pole `taxon`, prípadne `genus` + `species`). Overené na vzorke 18 druhov z ADW: všetkých 18 má článok na Wikipédii.

Dáta, ktoré nás z Wikipédie zaujímajú a ADW ich nemá alebo ich má menej presné:

| Atribút | Pole vo Speciesbox | Prečo je pre nás zaujímavý |
|---|---|---|
| stav ohrozenia IUCN | `status`, `status_system` | Wikipedia býva aktuálnejšia než ADW, môžeme porovnať a doplniť chýbajúce |
| autor a rok popisu druhu | `authority` | ADW nemá, nový atribút (dopyt „species described by Linnaeus") |
| poddruhy | `subdivision` | ADW nemá, dopyt „subspecies of lion" |
| alternatívne bežné názvy | `name` + tučné výrazy v prvej vete článku | „masked shrew" nájde Sorex cinereus, ADW pozná len jeden bežný názov |
| úvodný odsek článku | text pred prvým nadpisom `==` | ďalší text do indexu, iný štýl než ADW |
| dĺžka článku, počet odkazov | | štatistika pre report |

## Príklady dopytov a odpovedí

Dopyt je voľný text ako vo webovom vyhľadávači. Odpoveď je zoznam druhov zoradený podľa relevancie, pri každom druhu vedecké meno, bežný názov, taxonómia, geografický rozsah, habitat, potrava a stav ohrozenia. Dopyty sú vybrané tak, aby pokryli rôzne typy: presné meno, bežný názov, kombinácia atribútov, voľný text z opisu.

| # | Dopyt | Očakávaná odpoveď | Čo testuje |
|---|---|---|---|
| 1 | Panthera leo | na prvom mieste Panthera leo (lion), ďalej ostatné druhy rodu Panthera (tiger, leopard, jaguar) | presná zhoda vedeckého mena |
| 2 | yellow parrot australia | na prvom mieste Melopsittacus undulatus (budgerigar), ďalej iné austrálske papagáje (Cacatua, Nymphicus hollandicus) | voľný text z opisu + geografický rozsah |
| 3 | carnivore africa endangered | druhy so štítkom carnivore, rozsahom ethiopian a IUCN statusom Endangered alebo Vulnerable, napr. Lycaon pictus (African wild dog), Acinonyx jubatus (cheetah), Panthera leo | kombinácia troch atribútov |
| 4 | hibernates during winter | druhy, ktorých opis obsahuje hibernáciu, napr. Ursus americanus (American black bear), Marmota monax (groundhog), Tamias striatus (eastern chipmunk) | voľný text z opisu (Behavior), bez pomoci atribútov |
| 5 | nocturnal desert rodent | hlodavce (Rodentia) so štítkom desert a slovom nocturnal v opise, napr. Dipodomys (kangaroo rats), Chaetodipus | atribút (habitat, taxonómia) + voľný text |
| 6 | mammal that lays eggs | Ornithorhynchus anatinus (platypus) a Tachyglossus aculeatus (echidna) na prvých miestach pred ostatnými cicavcami | ranking: veľa dokumentov obsahuje „mammal", len dva aj „lays eggs" |
