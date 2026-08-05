# Metodologija

Kako se gradi korpus, kako se nad njim pretražuje, i kako se dokazuje da nečega
u njemu nema. Ovaj dokument opisuje odluke koje se iz koda ne vide same po sebi.

---

## 1. Dohvat

Portal ANON nema JSON API. Sučelje je server-rendered ASP.NET aplikacija, pa se
parsira HTML:

```
pretraga   GET /Document/DisplayList?q=<upit>&page=<n>      10 rezultata po stranici
odluka     GET /Document/View?id=<uuid>                     div.decision-text
PDF        GET /Document/DownloadPDF?id=<uuid>
```

Dvije granice tražilice određuju kako se planira dohvat:

**Zadana logika je OR, ne AND.** Upit od šest riječi vraća 10.000 pogodaka jer
traži bilo koju. Precizan rezultat traži navodnike. Ta razlika nije dokumentirana
i tiho iskrivljuje svaki nepažljiv upit.

**Tvrdi strop od 10.000 pogodaka** po upitu, odnosno 1000 stranica. Šire teme
treba razbiti na više užih upita, jer se iznad tog stropa rezultati jednostavno
ne isporučuju.

Dohvat je jednodretven, s 1,5 s razmaka po hostu, diskovnim kešom i retryjem uz
eksponencijalni backoff. Keš nije samo pristojnost prema izvoru: omogućio je da
se cijeli korpus kasnije **ponovno parsira bez ijednog mrežnog zahtjeva** kad je
otkrivena greška u izlučivanju metapodataka (dio 5).

## 2. Pohrana i punotekstno pretraživanje

SQLite s FTS5 virtualnom tablicom nad čancima, uz konfiguraciju:

```sql
tokenize='unicode61 remove_diacritics 2'
```

Bez `remove_diacritics 2` upit `sumsko zemljiste` ne nalazi `šumsko zemljište`.
U hrvatskom korpusu to nije rubni slučaj nego promašaj većine pogodaka, jer
korisnici i pravni tekstovi nedosljedno koriste dijakritiku.

Korpus je inkrementalan: odluka koja je već preuzeta preskače se po `id`, pa se
noćno osvježavanje svodi na razliku.

## 3. Segmentacija (čankiranje)

Presude su duge (medijan oko 33.000 znakova) i model za ugrađivanje prima 512
tokena. Naivno rezanje po broju znakova lomi rečenice nasred misli i uništava
kontekst upravo ondje gdje je pravno relevantan.

Iskorištena je struktura dokumenta. Obrazloženja hrvatskih presuda su
**numerirana** (`1.`, `13.`, `2.1.`), pa se lom radi na tim granicama:

```python
RE_TOCKA = re.compile(r"(?m)^\s*\d{1,3}(?:\.\d{1,2})*\.?\s")
```

Ako dokument ima manje od tri takve granice (starije presude često nemaju
numeraciju), pada se natrag na lom po odlomcima.

Parametri i razlozi:

| Parametar | Vrijednost | Razlog |
|---|---|---|
| ciljana veličina | 1100 znakova | oko 300 tokena za hrvatski, ostavlja zalihu |
| tvrda granica | 1600 znakova | iznad toga model tiho reže rep |
| preklop | 200 znakova | čuva kontekst na šavu između čanaka |
| najmanji čanak | 60 znakova | ispod toga je šum (potpisi, brojevi listova) |

Izmjereno na uzorku od 150 odluka: medijan 1072 znaka po čanku, oko 31 čanak po
odluci. Za korpus od 2437 odluka to je oko 75.000 čanaka.

Zamka koju je otkrilo mjerenje: preklop se dodaje **na** segment, pa je maksimum
ispadao 1798 znakova, dakle iznad tvrde granice i izvan dosega modela. Rješenje
nije bilo podešavanje konstanti napamet nego završna zaštita koja svaki čanak
iznad granice tvrdo razbija. Nakon nje je maksimum točno 1600, uz nula
prekoračenja.

## 4. Vektorizacija i hibridno pretraživanje

**Model:** `intfloat/multilingual-e5-small`, 384 dimenzije. Traži prefikse
`query: ` za upit i `passage: ` za dokument. Bez njih kvaliteta osjetno pada, jer
je model tako i treniran.

Embeddingi se čuvaju kao `float32` BLOB uz čanak, pa cijeli indeks stane u jednu
datoteku bez vanjske vektorske baze. Za 75.000 čanaka to je oko 110 MB, što se
učitava u memoriju i pretražuje brute force. Uz taj red veličine indeks poput
HNSW-a ne bi donio mjerljivu korist, a donio bi ovisnost.

**Zašto hibrid, a ne samo vektori.** Semantička pretraga hvata značenje, ali
sustavno promašuje ono što je u pravu presudno: brojeve članaka, oznake predmeta,
nazive propisa. Upit "čl. 55. Zakona o šumama" semantički je blizak svakoj
odredbi o šumama. Obrnuto, BM25 promašuje parafrazu: odluka koja opisuje zamjenu
riječima "prenijeti prava u pogledu odnosnih šuma na drugu pravnu osobu" ne
sadrži riječ "zamjena" i nijedan frazni upit je ne nalazi.

Rezultati se spajaju **Reciprocal Rank Fusion**:

```
score(d) = Σ  1 / (60 + rang_i(d))
```

RRF je odabran jer radi nad **rangovima, a ne nad ocjenama**. BM25 vraća
neomeđenu negativnu vrijednost, kosinusna sličnost vraća broj u rasponu od minus
jedan do jedan. Normalizacija između njih zahtijeva proizvoljne pragove koji se
raspadnu čim se promijeni korpus. RRF tu kalibraciju uopće ne traži. Konstanta 60
je uobičajena vrijednost iz literature i prigušuje utjecaj visokih rangova iz
jednog izvora.

Provjereno na stvarnom slučaju: hibrid je izvukao citat starijeg zakona o
prijenosu šume "radi korištenja u druge namjene", koji frazna pretraga nije
mogla naći jer se riječ "zamjena" u toj odluci ne pojavljuje.

## 5. Izlučivanje metapodataka i tiha greška

Metapodaci se izlučuju iz spljoštenog teksta stranice, tako da se traži naziv
oznake pa sadržaj do **sljedeće poznate oznake**. Taj pristup ima jednu opasnu
osobinu: ako u popisu nedostaje makar jedna oznaka koju portal koristi, prethodna
oznaka **proguta njezin sadržaj** i greška je potpuno tiha.

Upravo se to dogodilo. Polje `Vrsta odluke` gutalo je `Zakonsko kazalo` i
`EuroVoc`, pa je korpus mjesecima imao 0 posto popunjenih predmetnih oznaka, a da
nijedan zahtjev nije pao niti je ijedan test crvenio.

Otkriveno je usporedbom svježeg dohvata s onim što je u bazi. Nakon dopune popisa
oznaka i ponovnog parsiranja **iz keša**, dakle bez ijednog novog zahtjeva prema
portalu:

| Metapodatak | Popunjeno |
|---|---|
| Zakonsko kazalo (citirani propisi s člancima) | 2289 od 2439 (94 %) |
| EuroVoc (hijerarhijske predmetne oznake) | 1305 od 2439 (54 %) |

Pouka je općenitija od ovog slučaja: kod parsiranja po graničnicima treba
**provjeravati potpunost popisa graničnika**, jer se nepotpun popis ne očituje
kao pad nego kao tiho osiromašen podatak.

## 6. Dokazivanje da nečega nema

Tvrdnja "nema sudske prakse o X" je jaka i lako je pogrešna. Nula pogodaka
najčešće znači da je upit loš, a ne da pojava ne postoji. Postupak koji je ovdje
korišten ima četiri koraka.

**Korak 1: točne fraze umjesto slobodnih riječi.** Zbog OR logike tražilice,
slobodne riječi daju lažnu obilnost. Navodnici daju provjerljivu nulu.

**Korak 2: kontrolne fraze.** Nula je vjerodostojna tek ako se pokaže da isti
mehanizam nad istim korpusom nalazi srodne pojmove:

| Fraza | Pogodaka |
|---|---|
| `"Zakona o šumama"` | 1845 |
| `"šumskih zemljišta"` | 1680 |
| `"šuma i šumskih zemljišta"` | 1233 |
| `"zamjena šuma i šumskih zemljišta"` | **0** |
| `"okrupnjivanja šuma"` | **0** |

**Korak 3: strojna provjera nad punim tekstovima.** Tražilica je crna kutija, pa
se zaključak ne smije osloniti samo na nju. Preuzeto je 2437 odluka koje citiraju
Zakon o šumama i provjereno lokalno: čl. 55. u dosluhu s nazivom tog zakona
pojavljuje se u **77** odluka, a **nijedna** ga ne veže uz zamjenu.

**Korak 4: objašnjenje odsutnosti.** Nalaz je uvjerljiv tek kad postoji razlog
zašto je prazan. Ovdje je strukturni: prema čl. 55. st. 2. zamjena je odluka
ministarstva i potom ugovor koji sklapa ministar. Uspješna zamjena završava
uknjižbom i **nikad ne proizvede presudu**, jer nema spora. Odsutnost prakse dakle
nije dokaz da institut ne prolazi, nego da se ne rješava pred sudom.

## 7. Razlučivanje istoimenih odredaba

Broj članka sam po sebi nije identifikator. U korpusu se čl. 55. pojavljuje u
najmanje tri različita propisa, s posve nevezanim sadržajem:

| Propis | Sadržaj čl. 55. |
|---|---|
| Zakon o šumama (NN 68/18) | zamjena šuma i šumskih zemljišta |
| Zakon o šumama (raniji, NN 52/90) | zabrana stjecanja dosjelošću, ukinuta odlukom USUD-a U-I-374/1998 |
| Zakon o naknadi za oduzetu imovinu | imovina koja se ne vraća zbog prostorne cjelovitosti |

Klasifikator zato ne traži broj članka izolirano, nego **u prozoru od 400 znakova
oko naziva propisa**, i odvojeno boduje materijalne signale instituta
(okrupnjivanje, gospodarska jedinica, ugovor o zamjeni, srazmjerna vrijednost).
Pogotku koji spominje drugi propis oduzimaju se bodovi.

Učinak je mjerljiv i naveden u `docs/mjerenje.md`.

## 8. Što ovaj korpus omogućuje dalje

Nakon popravka iz dijela 5, korpus više nije samo tekst nego **označen skup**:

- **525 različitih EuroVoc oznaka**, hijerarhijskih (`OKOLIŠ > POLITIKA OKOLIŠA >
  Zaštita okoliša > Zaštićeno područje`). To je ista taksonomija koju koristi
  MULTI-EURLEX, pa je usporediva s postojećim europskim skupovima.
- **338 različitih citiranih propisa**, a 2181 odluka navodi izričite članke.
- **Ishod postupka**, izvediv iz izreke (`odbija se` naspram `poništava se`,
  `usvaja se`, `preinačuje se`).

Time su otvorena tri nadzirana zadatka nad hrvatskim pravnim tekstom, za koja
javno dostupan skup koliko je poznato ne postoji: višeoznačna predmetna
klasifikacija, predviđanje pravne osnove (koji propis i članak), i klasifikacija
ishoda.
