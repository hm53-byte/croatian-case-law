# PRESUDE

Alat za izgradnju lokalnog, pretraživog korpusa hrvatske sudske prakse, i
primjer pravne analize provedene nad njim.

Autor: Hrvoje Matej, hrvoje.matej.l@gmail.com

## Zašto postoji

Portal sudske prakse na `sudskapraksa.csp.vsrh.hr` je ugašen; host danas odbija
TCP vezu. Zamijenila ga je tražilica sustava **ANON** na
[odluke.sudovi.hr](https://odluke.sudovi.hr) (Ministarstvo pravosuđa, uprave i
digitalne transformacije), koja sadrži preko 1,17 milijuna odluka i dopunjuje se
dnevno.

Tražilica je namijenjena pretrazi u pregledniku, jedan upit po jedan. Za
sustavnu analizu treba lokalni korpus: preuzeti jednom, pretraživati koliko god
puta, bez mrežnog zahtjeva po upitu.

## Što radi

```
odluke.sudovi.hr ─┐
narodne-novine.hr ┼─► scraperi ─► SQLite + FTS5 ─► analiza ─► Markdown / PDF
usud.hr ──────────┘                 + embeddingi
```

| Modul | Uloga |
|---|---|
| `common.py` | HTTP sloj: rate limit 1,5 s po hostu, disk keš, retry s backoffom |
| `anon.py` | Klijent za odluke.sudovi.hr (pretraga, metapodaci, puni tekst, PDF) |
| `store.py` | Korpus: SQLite + FTS5, inkrementalno, bez ponovnog preuzimanja |
| `vektor.py` | Semantička pretraga i hibrid BM25 uz kosinusnu sličnost |
| `zakoni.py` | Propisi u punom tekstu s Narodnih novina |
| `analiza_cl55.py` | Domenski klasifikator za čl. 55. Zakona o šumama |
| `u_pdf.py` | Pretvorba izvezenih odluka u PDF |

## Tehničke odluke koje nisu očite

**FTS5 uz `unicode61 remove_diacritics 2`.** Bez toga upit "sumsko zemljiste" ne
nalazi "šumsko zemljište", što u hrvatskom korpusu znači promašaj većine
pogodaka.

**Čankiranje po strukturi presude, ne po broju znakova.** Obrazloženja su
numerirana ("1.", "13.", "2.1."), pa se tekst lomi na tim granicama. Tvrda
granica je 1600 znakova jer model reže na 512 tokena, a preklop od 200 znakova
čuva kontekst na šavu.

**Hibrid umjesto same vektorske pretrage.** Semantička pretraga hvata značenje,
ali promašuje brojeve članaka i oznake predmeta, gdje je doslovno podudaranje
presudno. Rezultati BM25 i kosinusne sličnosti spajaju se RRF-om
(`1/(60+rang)`), koji ne traži da rezultati budu na istoj skali.

**Klasifikator koji razlikuje istoimene članke.** Čl. 55. postoji u Zakonu o
šumama, u Zakonu o naknadi za oduzetu imovinu, i u ranijim zakonima o šumama, uz
posve različit sadržaj. Pretraga po broju članka miješa sva tri, pa klasifikator
traži broj članka isključivo u dosluhu s nazivom propisa.

## Primjer analize: čl. 55. Zakona o šumama

Pitanje: postoji li objavljena praksa o zamjeni šuma i šumskih zemljišta u
vlasništvu RH?

Postupak i rezultat u `SUME55/analiza/`. Sažetak:

- Pretraga točnim frazama nad bazom od 1.173.225 odluka: **0 pogodaka** za
  `"zamjena šuma i šumskih zemljišta"`, `"okrupnjivanja šuma"`,
  `"susjedne gospodarske jedinice"`.
- Da nula nije posljedica pokvarene pretrage, provjereno kontrolnim frazama nad
  istom bazom: `"Zakona o šumama"` 1845, `"šumskih zemljišta"` 1680,
  `"šuma i šumskih zemljišta"` 1233.
- Preuzeto **2437 odluka** koje citiraju Zakon o šumama i provjereno strojno nad
  punim tekstovima: čl. 55. u dosluhu sa Zakonom o šumama pojavljuje se u **77**
  odluka, a **nijedna** ga ne veže uz zamjenu. Svih 77 odnosi se na raniji
  članak o zabrani dosjelosti.

Zaključak: institut zamjene iz čl. 55. nema objavljene sudske prakse. Razlog je
strukturni, ne slučajan: prema st. 2. to je odluka ministarstva i potom ugovor
koji sklapa ministar, pa uspješna zamjena završava uknjižbom i nikad ne proizvede
presudu.

Analiza je usput našla i da odredbu koja dopušta zamjenu šume za
**poljoprivredno** zemljište sadrži čl. 60. st. 3., a ne čl. 55., i to
istovjetnog teksta u zakonu iz 2005. i u važećem.

## Pokretanje

```bash
cd scrapers
python3 -m venv venv
./venv/bin/pip install requests beautifulsoup4 lxml
# za semantičku pretragu (povlači PyTorch):
./venv/bin/pip install "torch==2.2.2" "sentence-transformers>=2.7,<3" "numpy<2"
```

```bash
./venv/bin/python anon.py search "zamjena šumskog zemljišta" --max 30
./venv/bin/python anon.py harvest "okrupnjivanje šuma" --max 100
./venv/bin/python store.py                    # stanje korpusa
./venv/bin/python vektor.py index             # inkrementalno
./venv/bin/python vektor.py query "nesrazmjer vrijednosti kod zamjene" -k 8
./venv/bin/python analiza_cl55.py --izvezi
```

Detalji sučelja portala i granica tražilice: `scrapers/README.md`.

## Odnos prema izvoru

Jedna dretva, 1,5 s razmaka po hostu, keširanje da se isti URL ne traži dvaput,
retry s eksponencijalnim backoffom umjesto ponavljanja u petlji. Odluke sudova su
javno dobro i portal je besplatan bez registracije.

Korpus i bulk izvoz odluka nisu u repozitoriju (vidi `.gitignore`); repozitorij
je alat, ne arhiva. U `SUME55/primjeri/` stoji nekoliko primjera izlaza.

## Okolina

Razvijeno i testirano na macOS 13 (Intel). PyTorch je zaključan na 2.2.2 jer je
to posljednja verzija s wheelovima za x86 macOS.
