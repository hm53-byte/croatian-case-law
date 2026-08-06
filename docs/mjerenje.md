# Mjerenje

Brojke umjesto tvrdnji. Sve je izmjereno nad korpusom od **2439 odluka**
preuzetih s portala ANON, a postupak je opisan u [`metodologija.md`](metodologija.md).

## Kako čitati ovaj dokument

Dokument ima četiri dijela i svaki odgovara na drugo pitanje:

| Dio | Odjeljci | Pitanje |
|---|---|---|
| I. Korpus i njegova obrada | 1 do 7 | Što je u korpusu i koliko vrijedi obrada |
| II. Skaliranje | 8 | Isplati li se prikupiti više, i smije li se |
| III. Dohvat | 9 do 12 | Nalazi li cjevovod korisne presude |
| IV. Mjerodavna odredba | 13 | Je li se uopće tražio pravi članak |

Četiri napomene vrijede za cijeli dokument:

1. **Sve je stanje iz radne kopije na dan mjerenja, a ne konačna tvrdnja o
   projektu.** Gdje se brojka razlikuje od one u nekom starijem tekstu, mjerodavna
   je ova.
2. **Radni parametri dohvata prema portalu ne objavljuju se.** Ritam, broj veza,
   pragovi particioniranja, broj zahtjeva po fazi i URL obrasci nabrajanja
   izostavljeni su namjerno i to je na svakom mjestu izrijekom rečeno. Metoda
   ostaje opisana, brojke koje bi olakšale opterećivanje tuđeg poslužitelja ne.
   Iz istog razloga moduli `crawler.py`, `lov.py` i `zk.py` nisu u repozitoriju
   i ne pokreću se bez pisanog dopuštenja izvora (vidi 8.1).
3. **Baza nije bila mirna 6.8.2026.** Tog je dana u istu bazu tekao dohvat
   doktrine, pa je broj zapisa u `odluke_meta` rastao tijekom mjerenja (u tri
   sata sa 2444 na 2613 zapisa). Broj **sudskih odluka je cijelo vrijeme bio
   2439** i sva mjerenja tog dana izričito su ograničena na `gradivo='odluka'`.
   Gdje to ograničenje nije postavljeno, brojka je drukčija i to je zabilježeno
   (primjer u 11.).
4. **Ponovljena mjerenja prijavljuju se i kad se ne poklope.** Odjeljci 10.2 i
   11. sadrže brojke koje se razlikuju od onih izmjerenih ranije istog dana.
   Obje su ostavljene, uz uvjete pod kojima su dobivene.

---

# Dio I. Korpus i njegova obrada

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

Uzrok te nule razjašnjen je tek u odjeljku 13.: **čl. 55. Zakona o šumama u
različitim je verzijama zakona značio tri različite stvari**, pa razlučivanje po
nazivu propisa nije dovoljno. Treba razlučivati i po verziji.

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

Dvije ograde na ovu tablicu dolaze kasnije i obje su izmjerene:

- **Nula vrijedi za oblik riječi koji je upisan, ne za pojam.** FTS5 u ovom
  projektu nema hrvatski korjenovatelj, pa je svaki padež zaseban token
  (odjeljak 12.). Nad vlastitim korpusom od 2439 odluka fraza `"zamjena šuma"`
  ima 0 pogodaka, ali `"zamjenu šuma"` ima 1 (odjeljak 13.1).
- **Fraza je bila pogrešna.** Odredba koja korisnikov slučaj stvarno zatvara je
  čl. 56. Zakona o šumama, a ne čl. 55. (odjeljak 13.2).

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

---

# Dio II. Skaliranje

## 8. Skaliranje korpusa

Mjereno 5.8.2026. Cilj je bio provjeriti isplati li se puni crawl portala ANON
ili projekt treba ostati na uzorku.

### 8.1 Pilot uživo nije izveden, i to je nalaz

Zadatak je tražio ograničen pilot od 100 odluka uz mjerenje stvarne propusnosti.
**Pilot nije pokrenut.** Razlog nije tehnički nego pravni i provjeren je isti dan:

```
$ GET https://odluke.sudovi.hr/robots.txt        (5.8.2026. 17:19)
User-agent: *
Allow: /$
Allow: /Home/Privacy
Allow: /Home/About
Allow: /Home/Cookies
Allow: /Home/Accessibility
Allow: /Home/UserManual
Disallow: /
```

Dopuštene su samo informativne stranice. Parser `robots_dopusta()` nad tim
tekstom vraća `ZABRANJENO` za rutu koja nosi nabrajanje i dohvat teksta, jer ona
potpada pod `Disallow: /`.

Zaključak koji iz toga slijedi: nijedna faza koja dira tu rutu ne pokreće se bez
pisanog dopuštenja Ministarstva pravosuđa, uprave i digitalne transformacije.
Enumerator ima tvrdu zapreku koja to provodi i vraća izlazni kod 3 prije prvog
zahtjeva. Sam enumerator nije u ovom repozitoriju.

Zaobilaznica `--dopustenje` postoji, ali ona **upisuje oznaku dopuštenja u
tablicu `dopustenja`**. Takvo dopuštenje ne postoji, pa bi njezina uporaba
značila upisivanje neistinite pravne osnove u bazu. Nije korištena.

Posljedica za brojke niže: propusnost u odlukama u minuti **nije izmjerena nad
portalom**. Izmjereno je tempiranje vlastitog regulatora, što je gornja granica
koju si dopuštamo, a stvarna propusnost može biti samo niža (latencija portala,
429, 5xx). Sve projekcije treba čitati kao najbolji slučaj.

### 8.2 Particioniranje

Metoda: prostor se dijeli po sudu i godini, a ćelija koja bi prešla prag
rezultata dijeli se dalje po sve užem razdoblju, pa po upisniku. Prag postoji
jer tražilica odbija isporučiti rezultate iznad određenog broja, neovisno o
straničenju.

Nalaz koji opravdava složenost: od 11 sondiranih ćelija jedna već prelazi prag,
a još tri su blizu njega, i sve četiri pripadaju istom sudu. Dijeljenje po užem
razdoblju dakle nije rubni slučaj nego redovit posao za taj sud.

**Konkretne brojke ovog dijela (broj ćelija, prag, broj zahtjeva po fazi i
procijenjeno trajanje) namjerno nisu u repozitoriju.** To su radni parametri
prema tuđem poslužitelju, a ne domensko znanje, i objavom ne dobiva nitko osim
onoga tko bi portal htio opteretiti. Isto vrijedi za URL obrasce nabrajanja.

### 8.3 Otpornost na prekid (izvedeno, bez mreže)

Provjera je izvedena nad podmetnutim klijentom uz aktivnu mrežnu stražu, na
razini pilota (1 particija, 100 odluka, 10 po stranici). Prekid je ubačen nakon
6. zahtjeva.

| Provjera | Ishod |
|---|---|
| Zadnja potvrđena stranica prije prekida | 5 |
| UUID-a u redu čekanja nakon prekida | 50 |
| Nastavak kreće od stranice | 6 |
| UUID-a nakon nastavka | **100, bez gubitka** |
| Duplikata u redu čekanja | **0** |
| Ponovni dohvat potvrđenih stranica | **nijedan** |
| Ponovljenih nepotvrđenih stranica | 1 (stranica na kojoj je prekid pukao) |
| Zahtjeva ukupno (prekid + nastavak) | 11 |
| Zahtjeva bez prekida | 11 |
| **Cijena prekida** | **0 dodatnih zahtjeva** |

Sondiranje se ne ponavlja jer `ocekivano` ide u bazu odmah nakon prve stranice.
Ponovno traženje stranice na kojoj je prekid pukao je ispravno: ona nikad nije
potvrđena, a upis u `red_cekanja` i pomak brojača `stranica` događaju se u istoj
transakciji. Mehanizam odgovara tvrdnji iz zaglavlja `crawler.py`: prekid gubi
najviše jednu stranicu rezultata.

### 8.4 Veličina po odluci (izmjereno nad 2439 stvarnih odluka)

| Mjera | Vrijednost |
|---|---:|
| Sirovi tekst, srednje | 18.833 B |
| Sirovi tekst, medijan | 12.038 B |
| Komprimirano (zlib 6), srednje | **6.143 B** |
| Komprimirano, medijan | 4.325 B |
| Komprimirano, p90 | 11.768 B |
| Omjer kompresije | **3,07x** |
| Cijela baza po odluci (tekst + FTS + čanci) | 46.702 B |
| Dolazni promet po odluci | 82,9 kB (portal nema gzip) |

Kompresija dobiva 3,07x na tekstu, ali cijela baza po odluci je 7,6 puta veća od
komprimiranog teksta. Trošak nose FTS indeks i čanci, ne tekst.

### 8.5 Tempiranje regulatora (izmjereno, bez mreže)

Provjereno je samo da regulator drži zadani tempo i da razmak ispravno dijeli
među paralelnim vezama; izmjereno se poklapa s teorijskim vrijednostima.

**Zadani tempo, broj veza i izmjerene vrijednosti nisu u repozitoriju**, iz
istog razloga kao u 8.2. Napomena koja ostaje jer je jedina koja nešto tvrdi:
ovo je tempiranje **vlastitog** regulatora bez mreže, dakle gornja granica koju
si dopuštamo, a ne izmjerena propusnost portala. Stvarna propusnost može biti
samo niža.

### 8.6 Projekcije

Projekcije trajanja i prometa za pune prolaze izračunate su, ali **ne objavljuju
se**, jer se iz njih rekonstruira ritam dohvata iz 8.5.

Ono što se iz njih smije prenijeti, jer je svojstvo podataka a ne dohvata:

| Odluka | Tekst GB | Baza GB |
|---:|---:|---:|
| 20.000 | 0,1 | 0,9 |
| 50.000 | 0,3 | 2,2 |
| 1.173.225 | 6,7 | **51,0** |

Puni prolaz stane na disk (51 GB naspram 379 GB slobodnih), pa disk nije razlog
protiv njega. Razlozi su u 8.8 i oni su pravni, ne tehnički.

### 8.7 Reprezentativnost uzorka od 20.000 (`uzorkovanje.py plan --n 20000`)

Rezultat je degeneriran, i to je najvažniji nalaz ovog dijela:

```
okvir  : 2439 odluka u 593 stratuma
uzorak : 2439 odluka (traženo 20000) u 593 stratuma, 100.0% okvira
```

Traženih 20.000 je veće od okvira, pa je uzorak **cijeli postojeći korpus**. TVD
je 0,0000 po sve tri dimenzije (sud, upisnik, godina), ali ta nula ne znači
reprezentativnost: uzorak je jednak okviru po definiciji, a okvir je i dalje onaj
pristrani skup prikupljen oko šumarske teme. Alat to sam prijavljuje.

Stvarna mjera pristranosti je manjak prema uravnoteženom cilju:

| Mjera | Vrijednost |
|---|---:|
| Manjak do uravnoteženog cilja | **17.561 odluka u 593 stratuma** |
| Ravnomjernost okvira, sud | 0,860 |
| Ravnomjernost okvira, upisnik | 0,629 |
| Ravnomjernost okvira, godina | 0,531 |

Najveći pojedinačni manjkovi su u prekršajnim i parničnim upisnicima za 2025. i
2026. (npr. OS Bjelovar / Pp / 2025: ima 97, cilj 199, manjak 102).

Zaključak: da bi se uopće moglo govoriti o uzorku od 20.000, treba prikupiti
oko 17.561 novu odluku. Uzorkovanje ne može izvući ono čega u okviru nema.

### 8.8 Preporuka

**Puni crawl se ne pokreće.** Razlozi, po težini:

1. `robots.txt` ga zabranjuje. To je blokada, a ne trošak koji se može otplatiti
   nekom brojkom.
2. Čak i s dopuštenjem, promet takvog reda veličine prema javnom državnom
   portalu traži dogovor s izvorom, ne jednostranu odluku.
3. Za dva pitanja iz dijela 1.1 arhitekture puni korpus je nužan samo za
   doslovno pitanje (potpun odziv). Za značenjsko pitanje uzorak radi.

Preporučeni redoslijed:

1. Poslati zahtjev Ministarstvu za bulk pristup ili službeni izvoz. Službeni
   izvoz čini cijeli crawl nepotrebnim.
2. Do odgovora ostati na uzorku. Ciljani dohvat od oko 17.500 odluka po popisu
   manjkova iz 8.7 zauzima 0,8 GB i ispravlja stvarnu pristranost korpusa
   umjesto da je povećava.
3. Faze sondiranja i nabrajanja ne dohvaćaju tekst, ali i dalje diraju rutu koju
   `robots.txt` zabranjuje, pa i one čekaju dopuštenje.

Ono što je izvedivo odmah i bez ijednog zahtjeva: shema, vektorizacija onoga što
je već u bazi, i analiza nad postojećih 2439 odluka.

---

# Dio III. Dohvat

Četiri odjeljka, jedan referentni slučaj i jedan zamrznut zlatni skup.
Odjeljak 9. uspoređuje stari i novi postupak, 10. traži uzrok slabog odziva,
11. mjeri stari klasifikator zasebno, 12. mjeri alat na kojem oba počivaju.

## 9. Lov na presude: staro naspram novo

Mjereno na referentnom slučaju iz `docs/lov-na-presude.md`: kuća iz 1920. unutar
šume, nije ozakonjena, bez pristupa javnoj prometnici, prilaz jedino preko
šumskog zemljišta u vlasništvu RH, nekad je sve bilo jedno imanje pa je
razdvojeno. Korisnikova formulacija: "kako otkupiti parcelu da dođem do kuće".

Zlatni skup: 19 zapisa u korpusu (9 JAKO KORISNIH, 4 protuprimjera, 6 zapisa u
skupini "slabije"; oznaka P-196/2024 pogađa tri različita suda pa su uzeta sva
tri). Odziv se računa **samo nad 9 JAKO KORISNIH**; protuprimjeri se prijavljuju
zasebno jer su korisni iz suprotnog razloga.

### 9.1 Priprema: vektorski indeks nad cijelim korpusom

Mjerenje bi bilo namješteno da je indeksiran samo zlatni skup i njegovi
kandidati: zlatne odluke bi tada bile jedine s ugradnjama, pa bi ih vektorska
grana nalazila bez konkurencije. Zato je indeksiran cijeli korpus.

| | |
|---|---|
| Prije | 1015 odluka (41,6 %), 30.872 čanka |
| `vektor.py index` | +1424 odluke, +26.581 čanak, 86,2 min, 4,5 do 5,5 čanaka/s |
| Poslije | **2439 / 2439 odluka (100 %)**, 57.453 čanka, oko 84 MB ugradnji |

Naredba za podskup provjerena je nad zlatnim skupom:

```
vektor.py index-skup --iz-datoteke zlatni_ids.txt --ponovno
  -> 19 odluka, 714 čankova, 2,2 min
```

Usput je izmjeren i nalaz koji ruši jednu tvrdnju iz `docs/lov-na-presude.md`:
**nijedna od 19 zlatnih odluka nije bila u ranijem indeksu od 1015 odluka.**
Tvrdnja "postojeći hibrid daje 16/17 zlatnih u top 200" nije reproducibilna nad
ovom bazom, jer u trenutku kad je zapisana zlatne odluke nisu imale ugradnje.
Ispod su brojke izmjerene nad punim indeksom.

### 9.2 Staro: pet rekonstrukcija, sve velikodušne

Stari postupak je bio frazna pretraga plus bodovni klasifikator
`analiza_cl55.py`. Da usporedba ne bi bila namještena protiv njega, mjereno je
pet varijanti, i za svaku dubinu se uzima **najbolja**.

| Varijanta | Što radi |
|---|---|
| S1 | doslovna stara fraza `"zamjena šuma i šumskih zemljišta"` |
| S2 | korisnikove činjenice kao jedna fraza |
| S3 | korisnikove činjenice kao OR snop pojmova, poredak BM25 |
| S4 | prvih 500 iz S3, preslagano klasifikatorom `cl.55` |
| S5 | klasifikator `cl.55` nad cijelim korpusom |
| S6 | unija devet fraznih upita sastavljenih iz korisnikove kvalifikacije |

S1 i S2 vraćaju **nula dokumenata**. Vodeća fraza starog postupka nema nijedan
pogodak u korpusu od 2439 odluka; isto vrijedi za `"zamjena šumskog zemljišta"`,
`"otkup šumskog zemljišta"`, `"otkup državnog zemljišta"` i
`"pristup javnoj prometnici"`.

Klasifikator `cl.55` daje cjelobrojne bodove s golemim blokovima izjednačenih,
pa njegov poredak unutar bloka nije poredak nego redoslijed upisa u bazu:

| zlatna JAKO odluka | bodovi | strogo boljih | u istom bloku |
|---|---|---|---|
| OGS Zagreb P-5001/2025-16 | 4 | 90 | 5 |
| OS Zadar P-617/2025-10 | 3 | 95 | 35 |
| OS Makarska P-1150/2024-23 | 3 | 95 | 35 |
| ZS Slavonski Brod Gž-69/2023-4 | 3 | 95 | 35 |
| OS Bjelovar P-5/2025-24 | 1 | 130 | 480 |
| OS Crikvenica P-756/2024-31 | 1 | 130 | 480 |
| OS Rijeka P-88/2023-24 | 0 | 610 | 1770 |
| OS Bjelovar P-864/2022-77 | 0 | 610 | 1770 |
| OS Bjelovar P-444/2022-34 | 0 | 610 | 1770 |

Tri od devet JAKO odluka klasifikator boduje jednako kao 1770 drugih odluka,
dakle o njima ne kaže ništa. Zato se za S4 i S5 prijavljuje **očekivani odziv uz
slučajno razbijanje izjednačenih** (200 ponavljanja), a ne jedan sretan poredak.

### 9.3 Glavna tablica: odziv na 9 JAKO KORISNIH

`STARO` je najbolja od šest varijanti na toj dubini. `NOVO` je
`lov.py trazi` s punim opisom činjenica, zadanim `--k-grane 200`.

| k | STARO (najbolja varijanta) | NOVO (`lov.py`) | razlika |
|---:|---:|---:|---:|
| **10** | **0,00 / 9** (0 %) | **0,00 / 9** (0 %) | 0 |
| **20** | **1,00 / 9** (11 %) | **1,00 / 9** (11 %) | 0 |
| **50** | **2,83 / 9** (31 %) | **3,00 / 9** (33 %) | +0,17 |
| 100 | 3,96 / 9 (44 %) | 3,00 / 9 (33 %) | **-0,96** |
| 200 | 5,12 / 9 (57 %) | 5,00 / 9 (56 %) | -0,12 |

Po varijantama, radi provjere:

| | @10 | @20 | @50 | @100 | @200 |
|---|---:|---:|---:|---:|---:|
| S1 doslovna stara fraza | 0 | 0 | 0 | 0 | 0 |
| S2 činjenice kao fraza | 0 | 0 | 0 | 0 | 0 |
| S3 OR snop + BM25 | 0 | 1 | 1 | 2 | 5 |
| S4 pool 500 + cl.55 | 0,00 | 0,00 | 2,83 | 3,96 | 5,12 |
| S5 cl.55 nad korpusom | 0,00 | 0,00 | 0,00 | 1,39 | 4,23 |
| S6 unija starih fraza | 0 | 0 | 1 | 1 | 1 |
| **LOV sloj 3 (dohvat)** | 0 | 1 | 3 | 3 | 5 |
| **LOV sloj 4 (izlaz)** | 0 | 1 | 3 | 3 | 4 |

### 9.4 Zaključak o odzivu: novi cjevovod nije bolji

Na traženim dubinama razlika je **0, 0 i +0,17 presude od devet**. Jedna presuda
vrijedi 11,1 postotnih bodova odziva, pa je najveća izmjerena razlika manja od
petine jedne presude. To nije poboljšanje, to je izjednačenje unutar šuma.

Na @100 je stari postupak **bolji za jednu presudu**.

Tvrdnja "novi cjevovod bolje pronalazi korisne presude" nije potkrijepljena.

### 9.5 Gdje novi cjevovod stvarno pobjeđuje

Tri razlike su izvan šuma i sve tri su strukturne, ne rangirajuće.

**Protuprimjeri.** Novi cjevovod ih nalazi i **imenuje**; stari nema pojam
protuprimjera.

| | protuprimjera @200 |
|---|---|
| S3 OR snop + BM25 | 1 / 4 |
| S5 cl.55 nad korpusom | 1 / 4 (uvijek isti, TS Split P-422, i to na #1) |
| **LOV sloj 4** | **3 / 4**, razvrstani kao `PROTUPRIMJER` |

Da je korisnik gledao izlaz starog klasifikatora, prva odluka na popisu bila bi
predmet u kojem je stranka izgubila, bez ikakve oznake da je izgubila.

**Dohvatljivost.** U skup kandidata novog cjevovoda ulazi **9/9 JAKO odluka**
(od 2030 kandidata). Kod starog postupka je S6 nedostižnim ostavio 8 od 9, a
S3 tri od devet. Novi cjevovod dakle ima problem s **poretkom**, ne s dosegom;
stari je imao oba.

**Nulti pogodak se prijavljuje.** S1 i S2 vraćaju praznu listu bez ikakve
poruke. `lov.py` na nula pogodaka po institutu ispisuje da je to greška
formulacije, a ne dokaz da teme nema.

### 9.6 Osjetljivost na formulaciju: najveća slabost

Isti problem, šest formulacija, isti korpus i indeks. Odziv JAKO / 9:

| formulacija | instituta okinuto | @10 | @20 | @50 | protu @50 |
|---|---:|---:|---:|---:|---:|
| P0 puni opis činjenica | 12 | 0 | 1 | **3** | 0 |
| P1 "nemam pristup kući" | 4 | 0 | 0 | **0** | 1 |
| P2 "kuća u šumi bez puta" | 8 | 0 | 0 | 1 | 2 |
| P3 "otkup državnog zemljišta oko kuće" | 6 | 0 | 0 | 1 | 1 |
| P4 "kako otkupiti parcelu da dođem do kuće" | 5 | **1** | **2** | 2 | 0 |
| P5 činjenice bez kvalifikacije | 11 | 0 | 0 | 2 | 2 |

Raspon odziva@50 je **0 do 3 od 9**, dakle 33 postotna boda, a mijenja se samo
način na koji je isti problem izrečen. Uzrok je vidljiv u sloju 1: okidači
instituta `dosjelost` traže godinu, obitelj ili posjed
(`192\d`, `djed|otac|obitelj`, `nekad.{0,30}jedno`, `posjed`, `oduvijek`).
Nijedna kratka formulacija ih ne sadrži, pa `dosjelost` uopće ne uđe u P1, P3 i
P4, a to je institut koji nosi većinu zlatnog skupa.

Cjevovod dakle ne rekonstruira činjenice iz kratkog opisa, nego ih **prepisuje
iz onoga što je korisnik već sam napisao**. Ako korisnik ne spomene 1920. i
"nekad je sve bilo jedno", cjevovod na dosjelost ne pomisli.

Drugi nalaz iz iste tablice: P4, gola korisnikova kvalifikacija koju cijeli
dokument proglašava pogrešnim putem, daje **najbolji odziv@10 i @20** od svih
šest. Teza da korisnikova formulacija truje dohvat nije potvrđena.

### 9.7 Ablacije

| | @10 | @20 | @50 |
|---|---:|---:|---:|
| LOV P0, puni cjevovod | 0 | 1 | 3 |
| LOV P0, bez vektorske grane | 0 | 0 | 2 |
| Goli hibrid `vektor.py` nad P0 | 1 | 1 | 2 |
| Goli hibrid `vektor.py` nad P4 | 0 | 0 | 2 |
| Goli hibrid, upit "kako doći do kuće preko šumskog zemljišta" | **2** | **2** | 2 |

Jedan ručno pogođen upit u `vektor.py` daje @10 od 2/9, što je bolje od cijelog
cjevovoda s dvanaest instituta, HyDE ulomcima i strukturnim preslagivanjem.
Katalog instituta zasad ne otplaćuje svoju složenost.

**Sloj 4 ne pomaže.** Uspoređeno na istim kandidatima:

| | @20 | @50 | @100 | @200 |
|---|---:|---:|---:|---:|
| sloj 3, sirovi dohvat | 1 | 3 | 3 | **5** |
| sloj 4, nakon preslagivanja | 1 | 3 | 3 | 4 |

Preslagivanje gubi jednu presudu na @200 i ne dobiva nijednu igdje. To potvrđuje
mjerenje koje je već zapisano u `lov.py`: unutar liste koju je sloj 3 izdvojio
nijedan strukturni signal ne razlikuje zlatne od ostalih. Ono što sloj 4 daje je
razvrstavanje na potpore i protuprimjere, a to s poretkom nema veze.

**Veći dohvat šteti.** `--k-grane 600` umjesto 200 spušta odziv@50 s 3 na 1.

**Najbolji pojedinačni institut nadmašuje njihovu uniju.** Na @200:
`razvrgnuce_dioba` sam nalazi **7/9**, dok ih unija svih dvanaest nalazi 5/9.
Institut `otkup_od_rh`, koji odgovara korisnikovoj vlastitoj kvalifikaciji,
nalazi **0/9** i time potvrđuje da otkup nije pravi put, ali ga cjevovod svejedno
vuče kroz cijeli dohvat.

### 9.8 Zašto ove brojke treba čitati s rezervom

1. **Mjerenje je unutar uzorka.** Katalog od dvanaest instituta, njihove fraze i
   HyDE ulomci pisani su uz uvid u ovih 19 odluka. Komentari u `lov.py` izrijekom
   spominju TS Split P-422/2025-19 i ZS Rijeka Gž-1989/2017-3. Prava mjera
   generalizacije traži zlatni skup za drugi činjenični sklop, koji ne postoji.
   Stari postupak takvu prednost nije imao, pa je usporedba ako išta naklonjena
   novom cjevovodu, a on je svejedno izjednačen.
2. **Uzorak od 9 odluka.** Jedna presuda vrijedi 11,1 postotnih bodova. Nijedna
   razlika u 9.3 nije veća od jedne presude, pa se nijedna ne smije zvati
   poboljšanjem.
3. **Korpus je pristran.** 2439 odluka prikupljenih ciljano oko šumarske
   tematike nije uzorak prakse.
4. **Cijena.** Stari postupak je jedan FTS upit, ispod sekunde. `lov.py` traje
   46 do 82 s po upitu, uglavnom na ugrađivanju HyDE ulomaka i množenju matrice
   57.453 x 384. To je oko sto puta skuplje za isti odziv.

### 9.9 Što slijedi iz mjerenja

- Ne tvrditi da je novi cjevovod bolji u pronalaženju korisnih presuda. Nije.
- Zadržati ga zbog razvrstavanja na potpore i protuprimjere i zbog straže nultog
  pogotka, jer to stari postupak nije radio.
- Sloj 4 postaviti na težinu 0 za poredak i koristiti ga samo za razvrstavanje,
  ili ga popraviti signalima koji razlikuju unutar uže liste.
- Napraviti sloj koji činjenice **dopunjuje**, a ne samo prepisuje, jer je
  osjetljivost na formulaciju (0 do 3 od 9) veća od cijele razlike prema starom
  postupku.
- Prije daljnjeg podešavanja pribaviti drugi zlatni skup. Bez njega se svako
  poboljšanje mjeri na podacima na kojima je i osmišljeno.

Skripte mjerenja za odjeljak 9.: `staro_eval.py`, `staro_dubina.py`,
`novo_eval.py`, `dubina_eval.py`, `strop_eval.py`, `finale.py` (radni direktorij
mjerenja, nisu dio repozitorija).

## 10. Lov na presude: tri oborene hipoteze

Odjeljak 9. je pokazao da novi cjevovod nije bolji od starog postupka. Ovaj
odjeljak traži uzrok. Postavljene su tri hipoteze i sve tri su mjerene. Dvije su
pale, treća je potvrđena i ona je jedina koja objašnjava brojke iz 9.3.

Zajednički uvjeti, ako uz pojedini redak ne piše drukčije:

| | |
|---|---|
| Korpus | 2439 sudskih odluka (`gradivo='odluka'`) |
| Zlatni skup | 9 JAKO KORISNIH, isti kao u 9. |
| Upit | `kako doci do kuce preko sumskog zemljista` |
| Dubina | k = 60 |
| Datum | 6.8.2026. |

### 10.1 Hipoteza 1: uzrok je nepotpun vektorski indeks. OBORENA

Pretpostavka je bila da cjevovod ne nalazi zlatne presude zato što one nemaju
ugradnje, pa vektorska grana o njima ne zna ništa. Ta je pretpostavka bila
utemeljena: prije popravka indeks je pokrivao **1015 od 2439 odluka (41,6 %)**, a
mjerenje iz 9.1 pokazalo je da **nijedna od 19 zlatnih odluka nije bila u njemu**.

Indeks je zatim dignut na **2439 / 2439 (100 %)**, 57.453 čanka (postupak i
trajanje u 9.1).

| | odziv na 9 JAKO, k = 60 |
|---|---|
| Indeks na 41,6 % | 2 / 9 |
| Indeks na 100 % | **2 / 9** |

Odziv se nije pomaknuo. Puni indeks kupuje **doseg**, ne **poredak**: nakon
popravka svih 9 zlatnih ulazi u kandidatski skup (9.5), ali nijedna nova ne uđe
u prvih 60.

Ograda na reproducibilnost: stanje "prije" više ne postoji, jer je indeks
prepisan na mjestu. Brojka 2/9 za indeks na 41,6 % zapisana je kako je
izmjerena tog dana i danas se ne može ponoviti. Brojka 2/9 za puni indeks
ponovljena je i reproducirana (tablica u 10.3).

### 10.2 Hipoteza 2: bodovanje mjeri formu umjesto sadržaja. OBORENA

Pretpostavka je bila da postojeći signali sloja 4 mjere formu odluke (institut
imenovan u izreci, vrsta stranaka, upisnik), pa na vrh izlaze odluke koje
institut samo **spominju**, a ne one koje rješavaju isti činjenični sklop.

Zato je u sloj 4 dodano treće rangiranje: kosinusna sličnost odluke s
**činjeničnim opisom**, izložena kao `TEZINA_CINJENICA` odnosno
`--tezina-cinjenica`. Zadana vrijednost je 0,0, dakle staro ponašanje, a
podiže se radi mjerenja.

**Mjerenje izvedeno ranije istog dana** (puni opis činjenica P0, k = 60):

| težina činjenica | 0 | 0,5 | 1,0 | 2,0 |
|---|---:|---:|---:|---:|
| odziv na 9 JAKO | 2 | 2 | 2 | **1** |

Zaključak tog mjerenja: veće težine ne pomažu, a na 2,0 štete.

**Ponovljeno mjerenje istog dana, nakon što je u istu bazu ušla doktrina**,
dalo je drukčije brojke i obje se ovdje prijavljuju:

| upit | težina 0 | 0,5 | 1,0 | 2,0 | kandidata |
|---|---:|---:|---:|---:|---:|
| P0, puni opis činjenica | 3 | 3 | 3 | **2** | 2027 |
| kratki upit `kako doci do kuce preko sumskog zemljista` | **1** | 3 | 3 | **4** | 1895 |

Što od toga stoji, a što ne:

- **Stoji:** nijedna težina ni u jednom uvjetu ne diže odziv iznad 4 od 9.
  Sličnost s činjeničnim opisom nije poluga koja nedostaje. U tom smislu je
  hipoteza oborena.
- **Stoji:** oblik krivulje uz puni opis P0 isti je u oba mjerenja, ravno pa pad
  na težini 2,0. Ponovljeno mjerenje daje po jednu presudu više na svakoj točki,
  što je unutar jedne presude, a jedna presuda ovdje vrijedi 11,1 postotnih
  bodova.
- **Ne stoji tvrdnja da veće težine uvijek štete.** Uz kratki upit odziv raste
  jednolično, 1, 3, 3, 4. Smjer učinka ovisi o formulaciji upita, što je ista
  slabost koju mjeri 9.6, a ne svojstvo same težine.

Zadana vrijednost ostaje 0,0. Ne zato što je izmjereno da je najbolja, nego zato
što nijedna druga nije izmjereno bolja, a podešavanje na 9 primjera nad kojima je
katalog i pisan nije mjerenje nego prilagodba (9.8, točka 1).

### 10.3 Hipoteza 3: kandidatski skup je prevelik i preslagivanje kvari dobar dohvat. POTVRĐENA

Isti upit, isti indeks, isti dan. Uspoređena je čista vektorska pretraga
(`vektor.py query --nacin vektor`) s punim cjevovodom (`lov.py`).

| | Zadar P-617/2025-10 | Crikvenica P-756/2024-31 | Zagreb P-5001/2025-16 | odziv na 9 JAKO |
|---|---:|---:|---:|---:|
| Čista vektorska pretraga, k = 60 čanaka | **3.** | 8. (čanak 9.) | nema | **2 / 9** |
| `lov.py` sloj 3, 1905 kandidata | 138. | 109. | 24. | (dohvat, ne izlaz) |
| `lov.py` sloj 4, izlaz k = 50 | **ne vraća** | ne vraća | 26. | **1 / 9** |

Ostali rangovi sloja 3, radi potpunosti: Bjelovar P-444/2022-34 na 110.,
Slavonski Brod Gž-69/2023-4 na 279., Rijeka P-88/2023-24 na 282., Bjelovar
P-5/2025-24 na 435., Makarska P-1150/2024-23 na 460., Bjelovar P-864/2022-77 na
618. mjestu. **Svih 9 zlatnih je u kandidatskom skupu**, dakle problem doista
nije doseg.

Čista vektorska pretraga s tih 60 čanaka pokriva 45 različitih odluka i Zadar
stavlja na treće mjesto i po čanku i po dokumentu. Isti taj Zadar cjevovod s
dvanaest instituta gura na 138. mjesto i zatim ga uopće ne isporuči.

To je potvrda hipoteze i najoštriji nalaz cijelog dijela III: **cjevovod uništava
dobar rezultat koji jednostavniji postupak već ima.** Nije riječ o tome da mu
nedostaje signal, nego da 1900 kandidata razrijedi ono malo signala što ga ima.

Nalaz se poklapa s dva već zapisana mjerenja iz 9.7, koja su dobivena drugim
putem: `--k-grane 600` umjesto 200 spušta odziv@50 s 3 na 1, a goli hibrid nad
istim upitom daje odziv@10 od 2/9, bolje od cijelog cjevovoda.

### 10.4 Što slijedi iz tri hipoteze

Dvije pale hipoteze isključuju dva popravka koja su djelovala očito: dopuniti
indeks (učinjeno, ne pomaže poretku) i dodati sadržajni signal (dodano, ne diže
odziv iznad 4/9). Potvrđena hipoteza upućuje na suprotan smjer od dosadašnjeg
rada: **suziti kandidatski skup, a ne proširivati katalog instituta.**

Ograde iz 9.8 vrijede i ovdje bez ublažavanja: uzorak je 9 odluka, mjerenje je
unutar uzorka, a jedna presuda vrijedi 11,1 postotnih bodova. Nijedna razlika u
ovom odjeljku osim one u 10.3 nije veća od jedne presude.

Skripte: `mjeri.py`, `h2_tezine.py` (radni direktorij mjerenja, nisu dio
repozitorija).

## 11. Stari klasifikator `analiza_cl55.py` mjeren protiv zlatnog skupa

Odjeljak 9.2 mjerio je klasifikator kao jednu od šest rekonstrukcija starog
postupka. Ovdje je mjeren sam, u zadanim postavkama, jer je to alat koji je
stvarno korišten prije cijelog projekta.

Postavke: `analiza_cl55.ocijeni` nad svim odlukama, zadani prag 6, korpus
ograničen na `gradivo='odluka'` (2439 odluka), 6.8.2026.

| Mjera | Vrijednost |
|---|---:|
| Kandidata iznad praga 6 | **88** |
| Od toga zapisa iz zlatnog skupa (19 zapisa) | **1** |
| Preciznost prema zlatnom skupu | **1/88 = 0,011** |
| Od toga JAKO KORISNIH (9) | **0** |
| Preciznost prema JAKO KORISNIMA | **0/88 = 0,000** |
| Odziv na 19 zapisa današnjeg zlatnog skupa | 1/19 = 0,053 |
| Odziv na 17 zapisa ranijeg zlatnog skupa iz `lov-na-presude.md` | **1/17 = 0,059** |
| Odziv na 9 JAKO KORISNIH | **0/9** |

Dvije brojke odziva stoje jedna do druge namjerno. Zlatni skup je u
`docs/lov-na-presude.md` imao 17 zapisa, a u 9. je narastao na 19 (oznaka
P-196/2024 pogađa tri suda). Nazivnik se promijenio, brojnik nije. Obje su
točne, ovisno o tome protiv kojeg se skupa mjeri, i nijedna se ne prešućuje.

**Jedini zapis iz zlatnog skupa koji klasifikator uopće vrati je protuprimjer, i
stavlja ga na prvo mjesto od 2439 odluka.**

| bodovi | odluka | u zlatnom skupu |
|---:|---|---|
| **9** | Trgovački sud u Splitu P-422/2025-19 | **PROTUPRIMJER** |
| 7 | Trgovački sud u Pazinu P-151/2023-100 | |
| 7 | Općinski sud u Splitu P-4187/2025-21 | |
| 7 | Općinski sud u Bjelovaru Pp-2880/2024-13 | |
| 7 | Županijski sud u Dubrovniku Gž-1665/2012-2 | |

Devet bodova je najviši rezultat u cijelom korpusu, dakle nema izjednačenja na
vrhu i nije riječ o sretnom poretku unutar bloka. Korisnik koji bi otvorio prvi
rezultat pročitao bi predmet u kojem je stranka izgubila, bez ijedne oznake da je
izgubila. To je isti nalaz koji je 9.5 zabilježio za varijantu S5, ovdje potvrđen
u zadanim postavkama alata.

Zašto klasifikator promašuje, vidi se iz njegovih signala: `okrupnjivanje šuma`,
`iste ili susjedne gospodarske jedinice`, `odluka o zamjeni šuma`, `srazmjerna
vrijednost`, `ministar sklapa ugovor`. To su doslovne riječi čl. 55. Zakona o
šumama u verziji iz 2018. Odluke o pristupu kući tim se riječima ne služe, a
odluke koje se njima služe nisu o pristupu kući. Klasifikator dakle radi točno
ono za što je napisan i baš zato ne odgovara na ovo pitanje. Puni razlog je u
odjeljku 13.

Napomena o bazi koja se mijenjala: isti je izračun ranije istog dana, bez
ograničenja na `gradivo='odluka'`, dao **89** kandidata umjesto 88, jer je u
`odluke` pogled tada ulazilo i 174 zapisa doktrine. Preciznost je time
1/89 = 0,011, praktički ista, ali brojka bez naznačene osnovice ne vrijedi ništa,
pa je ovdje zabilježeno oboje.

## 12. FTS5 bez hrvatskog korjenovatelja

Obje pune tekstualne tablice u bazi deklarirane su ovako:

```sql
CREATE VIRTUAL TABLE odluke_fts USING fts5(
    broj, sud, kazalo, naslov, autori, casopis, tekst,
    content='v_odluke', content_rowid='rid',
    tokenize='unicode61 remove_diacritics 2'
)
```

`unicode61` dijeli tekst na nizove slova i uklanja dijakritike. **Korjenovatelja
ni lematizatora za hrvatski u lancu nema.** Posljedica je da je svaki padež
zaseban token, pa upit pogađa samo onaj oblik riječi koji je doslovno upisan.

Mjereno nad 2439 sudskih odluka, 6.8.2026., broj **dokumenata** po upitu:

| upit | dokumenata |
|---|---:|
| `dosjelost` | 279 |
| `dosjelosti` | 359 |
| `dosjeloscu` (dosjelošću) | 485 |
| `dosjelost OR dosjelosti OR dosjeloscu` | 508 |
| `dosjelo*` | **508** |
| `dosjel*` | 509 |
| `okucnica` (okućnica) | 49 |
| `okucnice` | 53 |
| `okucnicu` | 59 |
| `okucnica OR okucnice OR okucnicu` | 110 |
| `okucnic` (okućnic) | **0** |
| `okucnic*` | **143** |

Tri stvari koje iz toga slijede:

1. **Goli korijen nije token.** `okućnic` bez zvjezdice daje **nula** pogodaka,
   jer u korpusu nijedan oblik riječi nije doslovno "okućnic". Upit tiho vraća
   praznu listu. `dosjelost` slučajno jest oblik riječi, pa vraća 279, ali to je
   **55 %** od 508 koliko doseže `dosjelo*`. Izostanak zvjezdice ne prijavljuje
   se kao greška ni u jednom od ta dva slučaja.
2. **Nabrajanje padeža ne zamjenjuje prefiks.** Tri najčešća oblika riječi
   okućnica daju 110 dokumenata, a `okucnic*` daje 143. **33 dokumenta, dakle
   23 %, leži u oblicima koje nitko nije nabrojio** (okućnicom, okućnici,
   okućnicama i tako dalje). Kod dosjelosti je nabrajanje slučajno bilo dovoljno,
   508 naspram 508, i baš zato se na nabrajanje ne smije osloniti: uspije ili ne
   uspije ovisno o riječi, a mjerenje to ne pokaže dok se ne usporedi s
   prefiksom.
3. **Dijakritici ne smetaju.** `remove_diacritics 2` znači da `okucnic*` i
   `okućnic*` vraćaju istih 143 dokumenta. Jedini problem su nastavci, ne kvačice.

Posljedica za sve ostale brojke u ovom dokumentu: svaka mjera odziva koja dolazi
iz FTS grane ovisi o tome je li upit imao zvjezdicu. To je svojstvo alata, ne
korpusa. Isti je nalaz već zapisan u `docs/lov-na-presude.md`: izostanak jedne
zvjezdice ondje je stajao pet zlatnih presuda.

Negativan nalaz koji ide uz ovo: **hrvatski korjenovatelj nije ugrađen i nije
mjeren.** Ne postoji brojka koja kaže koliko bi donio. Sve što je izmjereno je
cijena njegova izostanka na dvije riječi.

---

# Dio IV. Mjerodavna odredba

## 13. "Zamjena šuma" nema nijedan pogodak, a mjerodavan je čl. 56.

### 13.1 Nulti nalaz nad vlastitim korpusom

Odjeljak 2. mjerio je frazu nad tražilicom portala (1.173.225 odluka). Ovdje je
mjerena nad vlastitim korpusom od 2439 odluka, FTS frazna pretraga, 6.8.2026.:

| fraza | pogodaka |
|---|---:|
| `"zamjena šuma"` | **0** |
| `"zamjene šuma"` | 0 |
| `"zamjeni šuma"` | 0 |
| `"zamjenom šuma"` | 0 |
| `"zamjena šume"` | 0 |
| `"zamjena šumskog zemljišta"` | 0 |
| `"zamjeni šumskog zemljišta"` | 0 |
| `"zamjenu šumskog zemljišta"` | 0 |
| `"zamjena šuma i šumskih zemljišta"` | 0 |
| `"okrupnjivanja šuma"` | 0 |
| `"odluku o zamjeni šuma"` | 0 |
| `"zamjenu šuma"` | **1** |

Fraza `"zamjena šuma"` ima **nula pojavljivanja u cijelom korpusu**. To je nalaz
koji stoji.

Taj jedan pogodak ne smije se progutati zbrajanjem, pa je pročitan. Riječ je o
predmetu Općinskog suda u Sesvetama Pn-52/2022-46 od 8.1.2025., a niz
"zamjenu šuma" pojavljuje se u iskazu svjedoka:
"prosjeka prema šumi prije MA, a sada u njegovom vlasništvu, s istim je izvršio
zamjenu šuma". To je privatna zamjena između susjeda u parnici za naknadu štete.
Nema veze s čl. 55. Zakona o šumama, nema ministarske odluke, nema okrupnjivanja
državnih šuma. Institut se u korpusu ne pojavljuje ni jednom, a niz znakova se
pojavljuje jednom i to ne kao institut.

Bez korjenovatelja (odjeljak 12.) ta razlika između nominativa i akuzativa mijenja
odgovor iz 0 u 1, pa se oblici koji su mjereni ovdje nabrajaju izrijekom umjesto
da se piše "fraza ima nula pogodaka" bez daljnjega.

### 13.2 Mjerodavna odredba je čl. 56., a ne čl. 55.

Doslovno iz pročišćenog teksta Zakona o šumama (NN 68/18, 36/24), preslika u
`SUME55/zakoni/PROCISCENI_zakon_o_sumama.md`:

> **Članak 55.** Zamjena šuma i šumskih zemljišta
> (1) Šume i šumska zemljišta u vlasništvu Republike Hrvatske mogu se zamijeniti
> sa šumama u vlasništvu drugih osoba, ako su na području iste ili susjedne
> gospodarske jedinice, u svrhu okrupnjivanja šuma i šumskih zemljišta u
> vlasništvu Republike Hrvatske.

> **Članak 56.** Stjecanje prava vlasništva na šumama i šumskim zemljištima
> (1) Šume i šumska zemljišta u vlasništvu Republike Hrvatske **ne mogu se
> otuđivati** iz vlasništva Republike Hrvatske, osim u slučajevima predviđenim
> ovim Zakonom.

Korisnikovo pitanje glasi "kako otkupiti parcelu da dođem do kuće". Na to
odgovara **čl. 56. st. 1.**, i odgovor je zabrana. Čl. 55. nije put do te kuće iz
tri razloga koja su u tekstu odredbe:

1. To je **zamjena, ne kupnja.** Tražitelj mora dati šumu, ne novac.
2. Šuma koju daje mora biti **u istoj ili susjednoj gospodarskoj jedinici**.
3. Svrha mora biti **okrupnjivanje državnih šuma**, ne rješavanje tuđeg pristupa.

Vlasnik kuće bez pristupa u pravilu ne ispunjava nijedan od ta tri uvjeta. Cijeli
je projekt dakle mjerio odsutnost fraze koja ni da je bila prisutna ne bi vodila
do odgovora.

### 13.3 Zašto je čl. 55. u sudskoj praksi značio nešto treće

Ovo objašnjava nulu iz odjeljka 1. (od 77 odluka koje doista citiraju čl. 55.
Zakona o šumama, **0** ga veže uz zamjenu). Provjereno je nad preslikama svih
verzija zakona u `SUME55/zakoni/`:

| verzija | što je čl. 55. |
|---|---|
| NN 52/90 | zabrana otuđenja državnih šuma **i** zabrana stjecanja dosjelošću |
| NN 140/05, NN 94/14 | naknada za izdvojene šume i prenesena prava |
| NN 68/18, NN 36/24 | **zamjena** šuma i šumskih zemljišta |

Doslovno iz NN 52/90, član 55.:

> Šume i šumska zemljišta u državnom vlasništvu nemogu se otuđivati iz državnog
> vlasništva. osim u slučajevima predviđenim ovim zakonom (arondacija,
> komasacija).
> Na šumama i šumskim zemljištima u državnom vlasništvu ne može se steći pravo
> vlasništva dosjelošću.

Drugi stavak ukinut je odlukom Ustavnog suda U-I-374/1998 od 12.1.2000. (NN 8/00),
preslika u `SUME55/zakoni/NN_2000_01_8_89.md`.

Iz toga slijedi troje:

1. **Odredba o zabrani otuđenja nije nestala, nego je preseljena.** Ono što je u
   zakonu iz 1990. bio čl. 55. st. 1., u zakonu iz 2018. je čl. 56. st. 1.,
   gotovo doslovno isti tekst. Broj članka se pomaknuo za jedan.
2. **Odluke koje citiraju "čl. 55. Zakona o šumama" uz dosjelost citiraju zakon
   iz 1990.**, ne onaj iz 2018. Riječ "dosjelost" u pročišćenom tekstu na snazi
   ne postoji ni jednom. Provjereno nad svih dvanaest preslika verzija: pojavljuje
   se samo u NN 52/90 i u odluci Ustavnog suda koja je ukida.
3. **Razlučivanje po nazivu propisa nije dovoljno.** Klasifikator iz odjeljka 1.
   traži broj članka u prozoru od 400 znakova oko naziva propisa i time diže
   preciznost sa 52 % na razinu na kojoj su svi pogoci doista o Zakonu o šumama.
   Ali unutar tih 77 pogodaka i dalje se miješaju tri različite odredbe, jer je
   isti broj članka u tri verzije zakona nosio tri različita sadržaja. Za to
   razlučivanje treba datum odluke i verzija propisa, a to nije izmjereno i nije
   napravljeno.

### 13.4 Što je od projekta ostalo valjano

Negativan nalaz se iskazuje, pa i kad pogađa polazište:

- Fraza `"zamjena šuma i šumskih zemljišta"` ima 0 pogodaka i nad portalom od
  1,17 milijuna odluka (odjeljak 2.) i nad vlastitim korpusom (13.1). To je
  točno izmjereno i ostaje točno.
- Ali nula nije bila zanimljiva zato što je institut nekorišten, nego zato što
  je **od početka tražen pogrešan članak**. Mjerodavan je čl. 56., a on je
  zabrana i o njemu nema što tražiti.
- Sve ostalo izmjereno u ovom dokumentu, od segmentacije preko brzine ugrađivanja
  do usporedbe starog i novog postupka, ne ovisi o tome koji je članak
  mjerodavan i vrijedi neovisno o ovom nalazu.

Izvori za odjeljak 13.: `SUME55/zakoni/PROCISCENI_zakon_o_sumama.md`,
`SUME55/zakoni/NN_1990_12_52_969.md`, `SUME55/zakoni/NN_2000_01_8_89.md`,
`SUME55/zakoni/NN_2005_11_140_2642.md`, `SUME55/zakoni/NN_2014_07_94_1884.md`,
`SUME55/zakoni/NN_2018_07_68_1392.md`.

---

# Dio V. Korpus doktrine

## 14. HRČAK preko OAI-PMH: 341 članak, 174 s tekstom

Mjereno 2026-08-06 nad `data/doktrina.sqlite` i `data/corpus.sqlite`. Sve brojke
u ovom odjeljku su ispisane iz baza, nijedna nije procijenjena.

### 14.1 Zašto se ovaj izvor smije dohvaćati, a portal odluka nije

Razlika prema Dijelu III. je pravna, ne tehnička. `odluke.sudovi.hr` ima
`robots.txt` s `Disallow: /`, pa se sustavno nabrajanje ondje ne radi. HRČAK je
suprotan slučaj i to je provjereno na živom poslužitelju istog dana:

```
User-agent: *
Disallow: /pretraga*
Disallow: /en/pretraga*
Disallow: /index.php/pretraga*
Disallow: /index.php/en/pretraga*
```

Zabranjena je samo pretraga. Uz to portal nudi OAI-PMH na
`https://hrcak.srce.hr/oai/`, protokol napravljen upravo za masovno preuzimanje
metapodataka. Dohvaćene putanje, ispisane iz baze, ostaju unutar dopuštenog:

| putanja | zapisa |
|---|---|
| `/oai/?verb=...` | svi zahtjevi za metapodacima |
| `/file/N` | 340 (poveznice koje sam OAI objavljuje) |
| `/N` (stranica članka) | 252 |
| `/pretraga*` | **0** |

Ritam: 1,5 s po zahtjevu iz `common.get`, uz dodatnu pauzu za `/file/` jer
HRČAK na rafal vraća HTTP 418. Jedna dretva, resumption tokeni se poštuju.

### 14.2 Opseg

| veličina | vrijednost |
|---|---|
| setova u katalogu (`ListSets`) | 581 |
| setova stvarno požnjeveno | 8 |
| članaka ukupno | **341** |
| godišta | 2006 do 2026 |

341 članak je oko 3,6 % od procijenjenih 9.360 članaka u pravnim setovima.
Ovo je uzorak, ne korpus. Puno preuzimanje nije pokretano.

### 14.3 Puni tekst naspram samih metapodataka

| stanje | članaka |
|---|---|
| s upotrebljivim punim tekstom (`ima_tekst=1`) | **174** |
| samo metapodaci | **167** |

Razlog izostanka teksta, po `tekst_status`:

| status | članaka | značenje |
|---|---|---|
| `ok` | 174 | tekst izvučen i pohranjen |
| `bez-unicode` | 8 | PDF bez ToUnicode CMap-a, pypdf vraća imena glifova |
| `sken` | **0** | nijedan sken bez tekstualnog sloja nije naiđen |
| nije ni pokušano | 159 | licenca ne dopušta dohvat, ili prolaz s `--tekst` nije pokrenut |

Nula skenova vrijedi samo za 182 članka nad kojima je izvlačenje pokušano. Za
preostalih 159 se o kvaliteti PDF-a ne zna ništa i to se ne smije čitati kao
da su u redu.

Osam `bez-unicode` zapisa je cijeli set Policije i sigurnosti, časopisa s
najslobodnijom licencom u uzorku (CC BY). Najotvorenije licencirani časopis
dakle daje 0 upotrebljivog teksta. Takav se tekst namjerno ne rekonstruira:
preslikavanje glifa u znak radi za ASCII, ali hrvatski dijakritici su izvan tog
raspona, pa bi pogođeno preslikavanje dalo tiho pokvaren korpus.

Veličina pohranjenog teksta:

| mjera | vrijednost |
|---|---|
| znakova | 14.120.543 |
| bajtova UTF-8 (nesažeto) | 14.529.588 |
| bajtova u bazi (zlib-6) | 4.857.153 |
| omjer sažimanja | 2,99x |

### 14.4 Licence: 341 od 341 ima zabilježenu licencu

Ovo je bila glavna obveza i ispunjena je bez iznimke:

| provjera | rezultat |
|---|---|
| članaka bez `licenca_kod` | **0** |
| članaka bez `licenca_tekst` (doslovni `dc:rights`) | **0** |
| članaka bez URL-a izvora | **0** |

Razdioba, uz broj onih koji imaju pohranjen puni tekst:

| kod | članaka | smije se širiti | s tekstom |
|---|---|---|---|
| `cc-by-nc-nd` | 274 | da (uvjetno) | 172 |
| `proza-ogranicena` | 30 | ne | 0 |
| `proza-otvorena` | 12 | da | 0 |
| `nepoznata` | 12 | ne | 0 |
| `cc-by` | 8 | da | 0 |
| `osobno` | 5 | ne | 2 |
| **ukupno** | **341** | 294 da / 47 ne | **174** |

Po časopisu:

| časopis | kod | članaka | s tekstom |
|---|---|---|---|
| Hrvatska i komparativna javna uprava | `cc-by-nc-nd` | 106 | 12 |
| Zbornik PF Sveučilišta u Rijeci | `cc-by-nc-nd` | 90 | 90 |
| Zbornik radova PF u Splitu | `cc-by-nc-nd` | 78 | 70 |
| Zbornik PF u Zagrebu | `proza-ogranicena` | 30 | 0 |
| Godišnjak Akademije pravnih znanosti | `proza-otvorena` | 12 | 0 |
| Zagrebačka pravna revija | `nepoznata` | 12 | 0 |
| Policija i sigurnost | `cc-by` | 8 | 0 |
| Pravni vjesnik | `osobno` | 5 | 2 |

Licenca je kod svih 341 zapisa utvrđena na razini časopisa
(`licenca_razina='casopis'` za 341 od 341), jer je `dc:rights` istovjetan za
sve zapise unutar seta. Kod 90 zapisa tekst licence spominje više CC oznaka
(`licenca_nejasno=1`) i tada je uzeta najstroža. Iz OAI-ja se licenca
pojedinog članka ne može pouzdano utvrditi i modul to ne skriva.

Straža klasifikatora nad 14 doslovnih `dc:rights` tekstova: **14/14 prošlo**.

### 14.5 PDF-ovi se doista ne zadržavaju

Tvrdnja iz modula je provjerena, ne samo napisana:

| provjera | rezultat |
|---|---|
| PDF-ova s HRČKA na disku | **0** |
| datoteka u kešu sa zaglavljem `%PDF` | **0** |
| zapisa u kešu koji spominju hrcak | 44, svi OAI-PMH XML |

31 PDF u `SUME55/odluke` i 1 u `SUME55/primjeri` su sudske odluke iz ranijeg
dijela projekta i nemaju veze s HRČKOM.

### 14.6 Prelijevanje u glavni korpus

U `corpus.sqlite` je 174 članka doktrine uz 2.439 odluka.

| `redistribucija` u korpusu | zapisa |
|---|---|
| `uvjetna` (CC BY-NC-ND) | 172 |
| `NULL` | 2 |

Dva zapisa s `NULL` su članci Pravnog vjesnika (`hrcak:293353`,
`hrcak:293354`), čija licenca glasi "full texts may be used and reproduced for
personal or educational purposes". `store.procijeni_redistribuciju` ih ne
prepoznaje i vraća `None`, što je po vlastitom docstringu istoznačno sa
`zabranjena`: ne izlazi s ovog računala.

**Nesuglasje koje treba zabilježiti.** Docstring modula `doktrina.py` kaže da
zapisi s `samo_lokalno=1` "NE izlaze iz ove baze". Izašli su: `u_korpus` ima
`samo_slobodne=False` kao zadano, pa su ta dva članka prelivena u
`corpus.sqlite`. Posljedica je zadržana, jer je `corpus.sqlite` lokalan i
isključen iz gita, a oznaka `redistribucija IS NULL` ih zaustavlja na svakom
budućem izvozu. Ali dokumentacija i ponašanje se ne slažu i jedno od toga treba
ispraviti prije nego što uzorak naraste.

### 14.7 Što može ući u javni repozitorij

Ništa od punih tekstova doktrine:

| datoteka | u gitu? |
|---|---|
| `data/doktrina.sqlite` (341 članak, 174 teksta) | ne |
| `data/corpus.sqlite` (174 doktrine) | ne |
| `data/corpus.sqlite.shema2.bak` | ne |
| `scrapers/sets.xml`, `oai.xml`, `id.xml` | ne (dodano 2026-08-06) |
| `data/uzorak.sqlite` | **da**, jedina praćena baza |

`data/uzorak.sqlite` je provjeren posebno, jer je jedini izuzet od pravila
`data/*`: 25 zapisa, svi `izvor='anon'`, nema stupca `gradivo`, 0 zapisa s
identifikatorom `hrcak:`. Nijedan članak doktrine nije u njemu.

Pravila u `.gitignore` za doktrinu su 2026-08-06 napisana izričito, a ne
oslonjena samo na šire pravilo `data/*`, da premještanje baze ili labavljenje
tog pravila ne otvori rupu.

### 14.8 Testovi

`python -m unittest discover -s tests`: **338 testova, sve prolazi.**

### 14.9 Što ovo mjerenje ne pokazuje

- Ponašanje na punom setu od oko 9.360 članaka. Najveći pojedinačni žetveni
  prolaz bio je 111 zapisa.
- Je li doktrina uopće poboljšala dohvat. Članci su preliveni u korpus, ali
  nijedno mjerenje odziva s doktrinom naspram bez nje nije napravljeno.
- Kvalitetu OCR-a, jer OCR nije pokretan ni na jednom zapisu.
