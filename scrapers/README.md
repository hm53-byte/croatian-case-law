# PRESUDE — scraperi za hrvatske pravne izvore

Alati za sustavnu izgradnju vlastite baze presuda u punom tekstu, lokalno na
tvom Macu. Zamišljeno kao "IUS-INFO kod kuće": jednom preuzeta odluka ostaje
zauvijek na disku, crawl je inkrementalan, a nad cijelim korpusom radi trenutna
full-text pretraga bez ijednog mrežnog zahtjeva.

## Instalacija (već napravljeno)

```bash
cd ~/Desktop/PRESUDE/scrapers
python3 -m venv venv
./venv/bin/pip install requests beautifulsoup4 lxml
```

Sve naredbe niže pokreći kroz `./venv/bin/python`.

## Arhitektura

```
odluke.sudovi.hr ─┐
narodne-novine.hr ┼─► scraperi ─► store.py (SQLite + FTS5) ─► analiza ─► SUME55/
usud.hr ──────────┘                  data/corpus.sqlite
```

| Datoteka | Uloga |
|---|---|
| `common.py` | HTTP sloj: rate-limit 1,5 s/host, disk cache, retry s backoffom |
| `store.py` | Korpus: SQLite + FTS5 (`unicode61 remove_diacritics 2`), dedupe, inkrementalnost |
| `anon.py` | **Glavni izvor** — Tražilica odluka sudova RH (odluke.sudovi.hr) |
| `nn_scraper.py` | Narodne novine — puni tekstovi propisa |
| `usud_scraper.py` | Ustavni sud RH |
| `zakoni.py` | Skida propise u `SUME55/zakoni/` |
| `analiza_cl55.py` | Domenski klasifikator za čl. 55. Zakona o šumama |
| `vektor.py` | **Vektorska + hibridna pretraga** (embeddingi, BM25, RRF fuzija) |
| `crawler.py` | Enumerator particija (sud x godina) za mjerilo punog korpusa; napredak u tablici `zadaci`, nastavak nakon prekida, provjera `robots.txt` |
| `semantic_search.py` | Stari stub — zamijenjen `vektor.py`, ostavljen radi povijesti |

## Zašto `anon.py`, a ne stari portal

Stari **Portal sudske prakse** (`sudskapraksa.csp.vsrh.hr`) je **ugašen** — host
danas odbija TCP vezu na 443. Zamijenila ga je tražilica sustava **ANON** na
`https://odluke.sudovi.hr` (Ministarstvo pravosuđa, uprave i digitalne
transformacije), koja sadrži sve javno objavljene odluke iz starog portala u
anonimiziranom obliku i dopunjuje se **dnevno**.

Reverse-engineerirano sučelje (obična ASP.NET aplikacija, nema JSON API-ja):

```
pretraga  GET /Document/DisplayList?q=<upit>&page=<n>     10 rezultata/stranici
filtri    &sk=<stvarno kazalo>   &zk=<zakon>   &prm=pravomocna
odluka    GET /Document/View?id=<uuid>                     div.decision-text
PDF       GET /Document/DownloadPDF?id=<uuid>
```

Metapodaci koji se izvlače: broj odluke, sud, datum, vrsta, upisnik, ECLI,
pravomoćnost, stvarno kazalo, prethodne/naknadne odluke.

### Dvije bitne granice tražilice

1. **Najviše 10.000 pogodaka po upitu** (1000 stranica). Šire teme treba
   razbiti na više užih upita.
2. **Zadana logika je OR, ne AND.** Upit od šest riječi vraća 10.000 pogodaka
   jer traži *bilo koju* od njih. Za precizan rezultat koristi navodnike:
   `"zamjena šuma i šumskih zemljišta"`.

## Uporaba

```bash
# pretraži i samo ispiši
./venv/bin/python anon.py search "zamjena šumskog zemljišta" --max 30

# pretraži + preuzmi puni tekst + spremi u korpus (inkrementalno)
./venv/bin/python anon.py harvest "okrupnjivanje šuma" --max 100

# jedna odluka po UUID-u
./venv/bin/python anon.py doc 05c6cdd3-1486-4903-b85f-eda703b4e5e0 --md

# stanje korpusa
./venv/bin/python store.py

# propisi u fulltext
./venv/bin/python zakoni.py

# domenska analiza čl. 55. + izvoz fulltexta
./venv/bin/python analiza_cl55.py --izvezi
```

## Vektorska pretraga (`vektor.py`)

Pretraga po točnoj frazi je krhka: hrvatski pravni jezik isti pojam izriče na
više načina („zamjena", „razmjena", „ustupanje uz protučinidbu", „prijenos uz
naknadu u zemljištu"). Vektorska pretraga hvata **značenje**, ali promašuje
brojeve članaka i oznake predmeta, gdje je doslovno podudaranje presudno. Zato
je zadani način rada **hibrid**.

```bash
./venv/bin/python vektor.py index                  # inkrementalno, preskače indeksirano
./venv/bin/python vektor.py index-skup ID1 ID2     # SAMO te odluke (zlatni skup)
./venv/bin/python vektor.py index-skup --iz-datoteke zlatni.txt --ponovno
./venv/bin/python vektor.py query "zamjena škart zemljišta za građevinsko" -k 8
./venv/bin/python vektor.py query "..." --nacin vektor   # samo semantički
./venv/bin/python vektor.py query "..." --nacin bm25     # samo doslovno
./venv/bin/python vektor.py query "..." --upit "drugi kut" --hyde "ulomak..."
./venv/bin/python vektor.py query "..." --objasni        # iz kojeg upita je pogodak
./venv/bin/python vektor.py stat
```

**Kako radi**

1. **Čankiranje po strukturi presude.** Obrazloženja su numerirana („1.", „13.",
   „2.1."), pa se lomi na tim granicama umjesto nasred rečenice. Ciljano ~1100
   znakova, tvrda granica 1600 (iznad toga model tiho reže tekst), preklop 200
   znakova da se ne izgubi kontekst na šavu. Medijan izlazi ~1070 znakova,
   ~31 čanak po odluci.
2. **Embeddingi.** `intfloat/multilingual-e5-small`, 384 dimenzije. Model traži
   prefikse `query: ` / `passage: ` — bez njih kvaliteta osjetno pada.
   Za ~1400 odluka to je ~43.000 čankova i ~64 MB vektora.
3. **Hibrid.** BM25 (FTS5) i kosinusna sličnost rade neovisno, a rezultati se
   spajaju **RRF-om** (`1/(60+rang)`). RRF ne traži da rezultati budu na istoj
   skali, pa ne treba normalizacija koja bi unijela proizvoljne pragove.
4. **Inkrementalno.** Već indeksirane odluke se preskaču, kao i kod harvesta.
   `index-skup` gleda samo zadane id-eve, pa se zlatni skup i kandidati jednog
   instituta indeksiraju u minutama umjesto da se čeka cijeli korpus.
5. **Snop upita.** `pretrazi()` prima više upita odjednom i spaja ih istim
   RRF-om kojim spaja grane, pa je jedan upit samo poseban slučaj snopa.
   `Upit(tekst, prefiks="passage")` ugrađuje proizvoljan tekst kao
   pseudodokument (HyDE) i ide isključivo u vektorsku granu: ulomak je
   izmišljen, pa bi pogrešan broj članka u BM25 bio lažni pogodak s visokim
   rangom. Svaki `Pogodak` nosi `podrijetlo` (koji upit, koja grana, koji
   rang), a `objasni()` to vraća u obliku spremnom za mjerne tablice.

**Napomena o hardveru:** ovo je Intel Mac bez GPU-a; zadnji PyTorch s x86 macOS
wheelovima je **2.2.2**, zato je verzija u instalaciji zaključana. Nema MPS-a —
sve ide na CPU. Indeksiranje je jednokratan trošak, pretraga je poslije trenutna.

**Što vektorizacija ne rješava:** ne stvara presude kojih u bazi nema. Ako je
tema slabo zastupljena, prvo treba proširiti korpus harvestom, pa indeksirati.

## Način uporabe: ad hoc, ne trajni crawl

Alat je namijenjen **pojedinačnim, ručno pokrenutim upitima**, a ne neprekidnom
prikupljanju. Nema rasporeda, nema pozadinske službe, nema LaunchAgenta.

Razlog nije samo pristojnost. `robots.txt` portala glasi:

```
User-agent: *
Allow: /$
Allow: /Home/Privacy, /Home/About, /Home/Cookies,
       /Home/Accessibility, /Home/UserManual
Disallow: /
```

Rute `/Document/DisplayList` i `/Document/View` potpadaju pod `Disallow: /`.
Ciljani upit za nekoliko odluka i sustavno nabrajanje cijele baze nisu ista
stvar ni po opsegu ni po učinku, ali granica je ista i treba je znati.

`crawler.py` zato ima tvrdu zapreku: bez izričitog dopuštenja odbija se pokrenuti
i vraća izlazni kod 3 prije prvog zahtjeva. Za sustavno preuzimanje treba
dogovor s Ministarstvom pravosuđa, uprave i digitalne transformacije, koje za
sustav ANON ima servise za kontroliranu razmjenu podataka.

Preporučeni redoslijed: pretraga postojećeg lokalnog korpusa (`lov.py`, `store.py`,
`vektor.py`) bez ijednog mrežnog zahtjeva, pa tek po potrebi ciljana dopuna.

## Pristojnost prema izvoru

- 1,5 s razmaka po hostu (`RATE_LIMIT_S` u `common.py`), jedna dretva
- sve dohvaćeno se kešira (`scrapers/cache/`) pa se isti URL ne traži dvaput
- retry s eksponencijalnim backoffom umjesto ponavljanja u petlji

Korištenje je privatno i nekomercijalno. Odluke sudova su javno dobro i portal
je besplatan bez registracije; svejedno nema smisla opterećivati javni servis.

## Ostali izvori

- **IUS-INFO / Ius Novum** — najbogatija baza, ali iza paywalla; ako imaš
  pretplatu, koristi njihov izvoz umjesto scrapinga.
- **Sudreg** (`sudreg-data.gov.hr/api-docs`) — službeni otvoreni API sudskog
  registra; nije izvor presuda, ali služi za provjeru stranaka iz odluka.
- **e-Oglasna ploča** (`e-oglasna.pravosudje.hr`) — sudska pismena, ne presude.
