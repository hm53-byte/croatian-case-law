# Primjeri pretrage

Stvarni izlazi alata nad korpusom od 2437 preuzetih odluka.

## Puni tekst (FTS5)

Pretraga je neosjetljiva na dijakritiku, pa `sumsko zemljiste` nalazi
`šumsko zemljište`.

```bash
./venv/bin/python store.py
```

```
Baza: data/corpus.sqlite
Ukupno odluka: 2437
Raspon datuma: 1990-02-20 .. 2026-07-20
Najzastupljeniji sudovi:
   321  Vrhovni sud Republike Hrvatske
   181  Općinski sud u Bjelovaru
   168  Visoki prekršajni sud Republike Hrvatske
```

## Pretraga portala po točnoj frazi

```bash
./venv/bin/python anon.py search '"zamjena šumskog zemljišta"' --max 10
```

Fraze u navodnicima daju AND, bez njih tražilica radi OR i vraća do 10.000
pogodaka. Ta razlika je bila ključna za nalaz u `../analiza/NALAZ.md`.

| Upit | Pogodaka |
|---|---|
| `"Zakona o šumama"` | 1845 |
| `"šumskih zemljišta"` | 1680 |
| `"šuma i šumskih zemljišta"` | 1233 |
| `"zamjena šuma i šumskih zemljišta"` | **0** |
| `"okrupnjivanja šuma"` | **0** |

Kontrolne fraze pokazuju da tražilica radi, pa nula nije artefakt.

## Hibridna pretraga (BM25 uz embeddinge)

```bash
./venv/bin/python vektor.py query "zamjena šumskog zemljišta za drugu vrstu zemljišta" -k 3
```

```
#1  [0.0164]  Trgovački sud u Splitu, P-422/2025-19 (2026-07-01)
     "izdvojiti iz šumskogospodarskog područja i prenijeti prava u pogledu
     odnosnih šuma i šumskih zemljišta na drugu pravnu osobu, radi njihovog
     korištenja u druge namjene, ako za to postoji opći interes..."
```

Taj je isječak citat ranijeg zakona koji pretraga po frazi nije uhvatila, jer
odluka nigdje ne koristi riječ "zamjena". To je razlog zašto uz BM25 stoji i
semantički sloj.

Način rada bira se zastavicom:

```bash
./venv/bin/python vektor.py query "..." --nacin vektor   # samo semanticki
./venv/bin/python vektor.py query "..." --nacin bm25     # samo doslovno
```

## Domenska analiza

```bash
./venv/bin/python analiza_cl55.py --izvezi
```

Klasifikator traži broj članka isključivo u dosluhu s nazivom propisa, pa
razdvaja čl. 55. Zakona o šumama od čl. 55. Zakona o naknadi i od ranijeg
članka o zabrani dosjelosti. Bez toga je većina pogodaka lažna.

## Napomena o podacima

Odluke dolaze iz sustava ANON, gdje su objavljene **u anonimiziranom obliku**.
Osobni podaci su zamijenjeni oznakama, što se vidi i u priloženim primjerima:

```
tužiteljice ZKZ, [adresa], OIB: [osobni identifikacijski broj]
k. č. br. [katastarska čestica] k. o. [katastarska općina]
```

Alat ne uklanja i ne dodaje anonimizaciju; preuzima tekst kakav je objavljen.

## Uzorak korpusa: proba bez ijednog preuzimanja

Puni korpus (2437 odluka, 144 MB) nije u repozitoriju, ali jest mali uzorak od
25 odluka vezanih uz šume i zamjenu zemljišta: `data/uzorak.sqlite` (0,7 MB,
odluke od 2006. do 2026.). Ima istu shemu i isti FTS5 indeks kao puni korpus,
pa se pretraga može isprobati odmah nakon `git clone`, bez skidanja ijedne
odluke s portala:

```bash
./venv/bin/python uzorak.py --trazi "sumsko zemljiste"
```

```
5 pogodaka za 'sumsko zemljiste' u uzorak.sqlite

#1  Visoki upravni sud Republike Hrvatske, Us-4946/2005-8 (2006-05-16)
     ... pripada naknada za oduzeto poljoprivredno i građevinsko »zemljište«,
     lugarnice, šume i »šumsko« »zemljište« po propisima o konfiskaciji ...
```

Uzorak se gradi iz punog korpusa i izbor je determiniran, pa isto pokretanje
daje isti uzorak:

```bash
./venv/bin/python uzorak.py
```
