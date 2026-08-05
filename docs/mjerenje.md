# Mjerenje

Brojke umjesto tvrdnji. Sve je izmjereno nad korpusom od **2439 odluka**
preuzetih s portala ANON, a postupak je opisan u [`metodologija.md`](metodologija.md).

---

## 1. Koliko vrijedi razlučivanje istoimenih odredaba

Naivna pretraga traži broj članka bilo gdje u tekstu. Klasifikator ga traži samo
u prozoru od 400 znakova oko naziva propisa.

| Mjera | Odluka |
|---|---|
| Naivno: `čl. 55` bilo gdje u tekstu | **148** |
| Od toga stvarno uz Zakon o šumama | **77** |
| Jasno drugi propis (Zakon o naknadi) | 24 |
| Ostalo (drugi propisi, sporedni spomeni) | 47 |
| **Preciznost naivne pretrage** | **52 %** |

Gotovo polovica pogodaka naivne pretrage odnosi se na čl. 55. nekog drugog
propisa. Bez razlučivanja bi svaka analiza tog članka krenula od skupa u kojem je
svaki drugi predmet nevezan.

Od onih 77 koje doista citiraju čl. 55. Zakona o šumama, broj onih koje ga vežu uz
zamjenu je **0**. Sve se odnose na raniji članak o zabrani stjecanja dosjelošću.

## 2. Kontrolne fraze uz nulti nalaz

Nula je vjerodostojna samo ako isti mehanizam nad istim korpusom nalazi srodne
pojmove. Mjereno nad tražilicom portala (1.173.225 odluka):

| Fraza | Pogodaka |
|---|---|
| `"Zakona o šumama"` | 1845 |
| `"šumskih zemljišta"` | 1680 |
| `"šuma i šumskih zemljišta"` | 1233 |
| `"gospodarske jedinice"` | 617 |
| `"zamjena šuma i šumskih zemljišta"` | **0** |
| `"zamjeni šuma i šumskih zemljišta"` | **0** |
| `"okrupnjivanja šuma"` | **0** |
| `"susjedne gospodarske jedinice"` | **0** |
| `"odluku o zamjeni šuma"` | **0** |

Pretraga po frazi radi. Nula nije artefakt.

## 3. Odabir pogodaka po strogosti

Za srodno pitanje (zamjena nekretnina u šumskom kontekstu) mjeren je učinak
sužavanja prozora u kojem se traži supojava:

| Kriterij | Odluka |
|---|---|
| `zamjena` i `šuma` bilo gdje u istom dokumentu | 160 |
| Zamjena **nekretnine** uz šumu u prozoru od 1600 znakova | 38 |
| Šuma u istoj rečenici sa zamjenom (prozor 360 znakova) | **20** |

Sužavanje sa 160 na 20 zadržalo je sve stvarno relevantne odluke i uklonilo
pogotke tipa "u zamjeni voditelja daktilobiroa" i "zamjena za plaćanje najamnine
8 m drva".

## 4. Segmentacija

Mjereno na uzorku od 150 odluka:

| Mjera | Vrijednost |
|---|---|
| Medijan duljine čanka | 1072 znaka |
| Medijan broja čanaka po odluci | 31 |
| Najveći čanak prije zaštite | 1798 znakova |
| Najveći čanak nakon zaštite | **1600 znakova** |
| Čanaka iznad granice nakon zaštite | **0** |

Granica od 1600 znakova nije proizvoljna: model prima 512 tokena, što je za
hrvatski oko 1800 znakova. Sve iznad toga model tiho odsijeca, pa bi rep čanka
bio indeksiran kao da ne postoji.

## 5. Brzina ugrađivanja

Mjereno na Intel Core i7 iz 2017., bez GPU-a, model `multilingual-e5-small`:

| Postavka | ms po čanku |
|---|---|
| 2 dretve, batch 16 | 263 |
| 4 dretve, batch 16 | 211 |
| 8 dretvi, batch 16 | **209** |
| 8 dretvi, batch 64 | 214 |

Veći batch ne pomaže na CPU-u. Ono što je pomoglo je grupiranje **preko odluka**
umjesto po odluci: odluka sa četiri čanka inače daje sitan batch i režija modela
pojede dobitak. Nakon te promjene propusnost je porasla s 3,4 na 5,0 čanaka u
sekundi, dakle oko 47 posto.

## 6. Metapodaci prije i poslije popravka

Izlučivanje po graničnicima gubilo je dva polja jer im nazivi nisu bili u popisu
oznaka (opisano u [`metodologija.md`](metodologija.md), dio 5):

| Metapodatak | Prije | Poslije |
|---|---|---|
| Zakonsko kazalo | 0 % | **94 %** (2289 od 2439) |
| EuroVoc | 0 % | **54 %** (1305 od 2439) |

Ponovno parsiranje je izvedeno **iz diskovnog keša**, bez ijednog novog zahtjeva
prema portalu.

## 7. Što je time dobiveno kao označen skup

| Oznaka | Opseg |
|---|---|
| Različitih EuroVoc pojmova | **525** |
| Različitih citiranih propisa | **338** |
| Odluka s izričito navedenim člancima | **2181** |
| Odluka s razlučivim ishodom iz izreke | 701 (457 odbijeno, 244 usvojeno) |

Najcitiraniji propisi u korpusu: Zakon o šumama (1297), Zakon o vlasništvu i
drugim stvarnim pravima (677), Zakon o zemljišnim knjigama (216), Zakon o
poljoprivrednom zemljištu (200).

Napomena o pristranosti: korpus je prikupljen ciljano oko šumarske tematike, pa
raspodjela oznaka odražava taj odabir, a ne raspodjelu u cijeloj bazi od 1,17
milijuna odluka. Za treniranje modela općenite namjene korpus treba proširiti
uzorkovanjem po upisniku i sudu.
