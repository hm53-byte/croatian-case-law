# Lov na presude

Arhitektura cjevovoda koji od **činjeničnog stanja** dolazi do **korisnih presuda**.

Referentni slučaj kroz cijeli dokument: kuća iz 1920. unutar šume, nije
ozakonjena, bez pristupa javnoj prometnici, prilaz jedino preko šumskog
zemljišta u vlasništvu RH, nekad je sve bilo jedno imanje pa je razdvojeno.
Korisnik pita "kako otkupiti parcelu da dođem do kuće".

Zlatni skup od 17 odluka (9 jako korisnih, 4 protuprimjera, 4 slabije) opisan je
u dijagnozi promašaja; svih 17 je u korpusu od 2439 odluka.

---

## 0. Što je zapravo zakazalo

Stari postupak je bio dvodijelan: frazna pretraga po `"zamjena šuma i šumskih
zemljišta"` i bodovni klasifikator `analiza_cl55.py`. Izmjereno:

| Komponenta | Rezultat |
|---|---|
| Vodeća fraza nad korpusom od 2439 odluka | **0 pogodaka** |
| 15 od 17 zlatnih nedostižno ijednom varijantom fraze | recall 2/17 |
| `analiza_cl55.py`, prag 6 | 88 kandidata, **preciznost 0,011**, odziv 0,059 |
| Najbolja JAKO presuda u poretku klasifikatora | **#91 od 2439** |
| #1 u poretku klasifikatora | protuprimjer TS Split P-422/2025-19 |
| Bodovi 9 JAKO presuda | `4, 3, 3, 3, 1, 1, 0, 0, 0`, medijan 1 |

Nasuprot tome, postojeći hibrid iz `vektor.py`, s upitom **na razini pristupa**
umjesto otkupa, na dokumentnoj razini daje **16/17 zlatnih u top 200**, s
Zadrom na #1 i Zagrebom na #2.

Iz toga slijedi jedina dijagnoza koja objašnjava sve brojke odjednom:

> **Dohvat nije bio pokvaren. Bila je pokvarena formulacija upita.**

Isti stroj, isti korpus, isti indeks:

| upit | JAKIH u prvih 8 čanaka |
|---|---|
| `kako doci do kuce preko sumskog zemljista` | **3** |
| `kako otkupiti parcelu da dodem do kuce` | 2 |
| `otkup parcele od drzave` | **0** |

Korisnikova vlastita formulacija daje nulu. Cijela poluga sustava je u sloju
koji **prepisuje pitanje**, a taj sloj u starom postupku nije postojao. Umjesto
njega stajala je jedna ručno pogođena fraza, i sve nizvodno je naslijedilo njezinu
pogrešku.

Drugi nalaz iste težine, i mnogo jeftiniji: FTS5 je konfiguriran s
`unicode61 remove_diacritics 2`, dakle **bez hrvatskog korjenovatelja**.

| oblik | dokumenata | zlatnih |
|---|---|---|
| `dosjelost` | 279 | 8 |
| `dosjelost*` | 410 | 11 |
| `dosjelo*` | 508 | **13** |
| `okućnic` | **0** | 0 |
| `okućnic*` | 143 | 4 |

Izostanak jedne zvjezdice košta 5 zlatnih presuda. To nije problem modela, to je
problem znaka.

---

## Pregled cjevovoda

```
činjenično stanje (laički jezik)
        │
   ┌────┴──────────────────────────────────────────────────────┐
   │ 1. FORMULACIJA        panel od 3 neovisna kuta            │  jezični model
   │    činjenice -> kandidati instituta + što bi ih oborilo   │
   └────┬──────────────────────────────────────────────────────┘
        │  8-15 instituta, svaki sa svojim dosjeom
   ┌────┴──────────────────────────────────────────────────────┐
   │ 2. ŠIRENJE UPITA      po institutu:                       │  model + tablice
   │    a) leksički snop iz izreke i obrazloženja              │
   │    b) morfološki prefiksi za FTS5 (dosjelo*)              │
   │    c) HyDE: hipotetski ulomak obrazloženja -> vektor      │
   └────┬──────────────────────────────────────────────────────┘
        │  5-15 upita po institutu
   ┌────┴──────────────────────────────────────────────────────┐
   │ 3. DOHVAT             BM25 + vektor, RRF, po institutu    │  SQLite + e5
   │    agregacija čanak -> dokument, unija s podrijetlom      │
   └────┬──────────────────────────────────────────────────────┘
        │  200-400 dokumenata kandidata
   ┌────┴──────────────────────────────────────────────────────┐
   │ 4. PRESLAGIVANJE      SPOMINJE vs ODLUČUJE                │  struktura + model
   │    suprotstavljenost stranaka, vrsta zahtjeva, upisnik    │
   └────┬──────────────────────────────────────────────────────┘
        │  40-80 dokumenata
   ┌────┴──────────────────────────────────────────────────────┐
   │ 5. PROVJERA           protivnički prolaz, lažni prijatelji│  model + citati
   │    dvije izlazne klase: potpore i PROTUPRIMJERI           │
   └────┬──────────────────────────────────────────────────────┘
        │
   ┌────┴──────────────────────────────────────────────────────┐
   │ 6. MJERENJE           recall@k na zlatnom skupu, ablacije │  skripta
   └───────────────────────────────────────────────────────────┘
```

Arhitektonsko načelo koje drži cijeli dizajn:

> **Jezični model se troši po problemu, nikad po dokumentu.**

Model radi na strani upita (slojevi 1, 2) i na nekoliko desetaka kandidata
(slojevi 4, 5). Nikad ne prelazi preko korpusa. Zato cjevovod koji danas radi nad
2439 odluka radi jednako nad 1,17 milijuna, uz isti trošak modela.

---

## Sloj 1: FORMULACIJA (činjenice -> kandidati instituta)

### Što radi

Uzima činjenice, ne korisnikovu pravnu kvalifikaciju, i vraća popis kandidata
instituta. Svaki kandidat je zapis s pet obveznih polja:

```
institut          nužni prolaz
pravna osnova     čl. 224.-229. ZV; izvanparnični postupak (ZIP NN 59/23)
zašto pristaje    nekretnina bez ikakve veze s javnom cestom; enklava u šumi;
                  dioba prethodno jedinstvene nekretnine -> prolaz se osniva
                  prvenstveno preko otuđenog dijela
što bi ga oborilo postoji druga prikladna veza; šteta > korist; gruba nepažnja
                  prednika; prigovor da je zgrada bespravna pa nema redovite
                  uporabe; prigovor nenadležnosti suda zbog dobra od interesa za RH
vokabular         "osniva se nužni prolaz u korist svakodobnog vlasnika",
                  "poslužna/povlasna nekretnina", "nema nikakve ni prikladne
                  veze s javnom cestom", "predlagatelj"/"protustranka",
                  "u širini od 3 m", "trasom označenom u geodetskom elaboratu"
očekivani upisnik R1 (izvanparnica), ne P
protustranka      Republika Hrvatska, zastupana po ODO; ne Hrvatske šume d.o.o.
```

Polje **"što bi ga oborilo"** nije ukras. Ono je ulaz u sloj 5: to je popis
tvrdnji koje protivnički prolaz mora provjeriti, i istovremeno popis onoga što
protuprimjeri dokazuju. Bez tog polja sloj 5 nema kriterij.

### Zašto to ne može BM25

Očito: BM25 traži preklapanje niza znakova. Između `nema pristup javnoj
prometnici` i `nužni prolaz, čl. 224. ZV` preklapanja nema. Mjerenje to i
potvrđuje: ista pretraga kroz `--nacin bm25` na laičkom upitu vraća **ukupno 17
dokumenata** i 4 zlatna, jer se doslovno podudaranje na laičkom jeziku raspada.

### Zašto to ne može ni embedding

Ovo je manje očito i važnije. `multilingual-e5-small` je treniran za
**semantičku sličnost i parafrazu**. Preslikavanje činjenice u institut nije
sličnost, nego **zaključak**: iz "nema pristup" plus "nekad jedno imanje" slijedi
"nužni prolaz, i to prvenstveno preko otuđenog dijela" tek uz poznavanje pravila
koje u tekstu pitanja nigdje ne piše. Vektorski prostor ne sadrži tu implikaciju
jer je nikad nije vidio kao par.

Postoji i drugi razlog, specifičan za ovaj korpus. Presude **pretpostavljaju**
institut kao već odabran: tužbeni zahtjev ga imenuje prije nego što sud počne
pisati. Zato u korpusu praktički ne postoji tekst oblika "činjenice X znače
institut Y"; postoji samo "traži se Y, evo činjenica X". Preslikavanje koje nam
treba nije zapisano u dohvatljivom obliku ni u jednom dokumentu, pa ga nikakav
dohvat ne može pronaći. Mora ga netko **proizvesti**.

Djelomično ga ipak može zaobići: mjerenje pokazuje da laički upit o pristupu
kući izvuče 16/17 zlatnih u top 200, jer riječi "kuća", "šumsko zemljište" i
"doći do" dijele površinsku semantiku s presudama. To je sreća pojedinog
slučaja, ne mehanizam. Kod formulacije "otkup parcele" ista sreća nestaje i
rezultat je nula. Sloj 1 postoji da rezultat ne ovisi o tome je li korisnik
slučajno upotrijebio riječ koja se nalazi i u presudama.

### Kako se izbjegava usidravanje

Usidravanje je bio konkretan uzrok promašaja: institut zamjene iz čl. 55. ZoŠ
odabran je unaprijed i sve dalje ga je nasljeđivalo. Četiri strukturne mjere:

**a) Panel od tri neovisna kuta.** Stvarnopravni, upravnopravni, procesni. Svaki
dobiva **iste činjenice i ne vidi izlaz ostalih**. Kutovi su birani tako da imaju
različite ulazne kategorije: stvarnopravni misli u služnostima i vlasništvu,
upravnopravni u nadležnim tijelima i upravnim aktima, procesni u vrsti postupka i
teretu dokaza. Kod referentnog slučaja to je odmah dalo tri različita nalaza koja
se ne bi pojavila iz jednog prolaza: fikcija zakonitosti zgrade iz čl. 175.
Zakona o gradnji (upravni kut), pogrešno označena protustranka HŠ d.o.o. umjesto
RH (procesni kut), i pravilo o prolazu prvenstveno preko otuđenog dijela
(stvarnopravni kut).

**b) Unija, ne presjek.** Kandidati se spajaju unijom. Institut koji je imenovao
samo jedan kut ulazi u dohvat jednako kao onaj kojeg su imenovala sva tri. Broj
kutova koji su ga imenovali je samo početna težina za redoslijed, nikad filtar.
Odziv se brani ovdje, preciznost se brani u slojevima 4 i 5.

**c) Korisnikova pravna kvalifikacija se briše iz ulaza.** Panel dobiva
činjenice, ne rečenicu "kako otkupiti parcelu". "Otkup" ulazi kao **hipoteza koju
treba testirati**, u vlastitom zapisu instituta, s poljem "što bi ga oborilo"
popunjenim (šumsko zemljište RH nije u redovnom prometu; čl. 56. ZoŠ). Ako panel
vidi korisnikovu kvalifikaciju u preambuli, sva tri kuta se sruše na nju i panel
prestaje biti panel.

**d) Straža nultog pogotka.** Ako upit izveden iz instituta nad cijelim korpusom
vrati **0**, to se tretira kao pogreška formulacije, a ne kao dokaz da tema ne
postoji. Stari postupak je učinio suprotno: `"zamjena šuma i šumskih zemljišta"`
= 0/2439 protumačeno je kao rijetkost teme. Provjera nad sirovim tekstom
(`LIKE '%zamjena šuma%'` = 0) pokazuje da niz **nikad nije postojao**. Ovo je
petnaest redaka koda i hvata najskuplju grešku u projektu.

### Čime je izvedeno

Jezični model, tri poziva, temperatura iznad nule, izlaz u strogom obliku
(JSON po gornjoj shemi). Trošak: 3 poziva po problemu. Nema treninga, nema
podataka za trening, nema ničega za održavanje osim uputa.

---

## Sloj 2: ŠIRENJE UPITA (institut -> stvarni sudski vokabular)

Institut je pojam. Dohvat treba **nizove znakova koji stvarno stoje u
presudama**. Tri različita generatora, jer tri različita mehanizma dohvata trebaju
tri različita ulaza.

### 2a. Leksički snop

Iz dosjea instituta izvlače se doslovni izrazi, razvrstani po mjestu na kojem se
pojavljuju:

- **izreka**: `"osniva se nužni prolaz"`, `"utvrđuje se da je tužitelj
  dosjelošću stekao pravo vlasništva"`, `"dopušta se uknjižba"`
- **obrazloženje**: `"nema nikakve ni prikladne veze s javnom cestom"`,
  `"samostalni posjednik nekretnine u vlasništvu Republike Hrvatske"`,
  `"savjesnost odnosno poštenje posjeda"`
- **citati odredaba u svim varijantama pisanja**: `čl. 159. st. 4. ZV`,
  `čl. 159. st. 4. Zakona o vlasništvu i drugim stvarnim pravima`, `ZVDSP`,
  `čl. 388. st. 4.`, `§ 418 OGZ`, `§ 328 OGZ`
- **uloge stranaka**: `predlagatelj`/`protustranka` naspram `tužitelj`/`tuženik`
- **datumi i pragovi**: `15. veljače 1968.`, `8. listopada 1991.`,
  `16. listopada 1990.`, `40 godina`, `u širini od 3 m`

Datumi su, ispada, među najjačim signalima u cijelom korpusu: `15. veljače 1968.`
je gotovo jednoznačan pokazatelj da se odlučuje o statusu stare zgrade, a
`8. listopada 1991.` o uračunavanju posjeda po čl. 388. st. 4. ZV. To je
doslovan niz, dakle posao za BM25, a ne za vektor.

**Tvrdo pravilo:** brojevi članaka koji ulaze u BM25 moraju biti provjereni, ili
protiv `zakonsko_kazalo` (popunjeno za 94 % korpusa, 2289 od 2439 odluka, 338
različitih propisa), ili protiv punih tekstova propisa iz `zakoni.py`. Model koji
izmisli "čl. 231. ZV" trovao bi dohvat tiho i uvjerljivo. Stari klasifikator je
upravo na tome pao s druge strane: tražio je čl. 55., a zlatne presude govore o
**čl. 56.** ZoŠ.

### 2b. Morfološko širenje za FTS5

Mehanički korak, najveći omjer dobitka i truda u cijelom cjevovodu. Svaka
punoznačna riječ iz snopa siječe se na stabilan prefiks i dobiva `*`:

```
dosjelost, dosjelošću, dosjelosti      -> dosjelo*
okućnica, okućnice, okućnicu           -> okućnic*
poslužna, poslužnog, poslužnoj         -> poslužn*
posjednik, posjedniku, posjedovanje    -> posjed*      (oprez: posjeta, posjed uz sud)
```

Prefiks se ne bira napamet. Postupak: model predloži rez, skripta izbroji
dokumente za nekoliko duljina reza, i uzima se najkraći rez koji ne eksplodira
(pravilo: rez se skraćuje dok broj pogodaka ne poraste više od otprilike 3x u
odnosu na prethodni korak). Tablica prefiksa se **zamrzne** i drži u repozitoriju,
jer se ne mijenja između problema.

Iskrena napomena: pravi hrvatski lematizator (`classla`, `stanza`) bio bi bolji
od zvjezdice, ali traži ponovno indeksiranje cijelog korpusa i novu ovisnost.
Zvjezdica hvata najveći dio dobitka (`dosjelo*` daje 13/17 naspram 8/17 za točan
oblik). Lematizator je odgoda, ne prioritet.

### 2c. HyDE (hipotetski ulomak obrazloženja)

Za svaki institut model piše **2 do 4 ulomka obrazloženja kakva bi napisao sud**,
u sudačkom registru, s pravilnim nazivima stranaka, uputom na dokaze i zaključkom.
Ne odgovor korisniku. Primjer izlaza za nužni prolaz:

> "Iz nalaza i mišljenja vještaka geodetske struke proizlazi da nekretnina
> predlagatelja predstavlja enklavu unutar šumskog kompleksa te da nema nikakve
> veze s javnom cestom. Sud je stoga ocijenio da su ispunjene pretpostavke iz
> čl. 224. st. 1. ZV, pri čemu je korist za povlasnu nekretninu pretežnija od
> štete koja se osnivanjem prolaza nanosi poslužnoj nekretnini..."

Taj ulomak se ugrađuje i **njegov vektor postaje upit**.

**Zašto radi:** e5 mjeri blizinu u prostoru u kojem su presude gusto smještene,
a laička pitanja rijetka. Korisnikova rečenica pada u područje gdje nema ničega.
Hipotetski ulomak pada usred oblaka presuda. To je isti mehanizam koji objašnjava
zašto laički upit o pristupu kući daje 3 JAKE, a laički upit o otkupu 0: razlika
je isključivo u tome koliko je jezik upita blizu jeziku korpusa. HyDE tu blizinu
proizvodi namjerno umjesto da se na nju nada.

**Detalj koji se lako promaši:** `ugradi()` u `vektor.py` dodaje prefiks
`query: ` ili `passage: `. HyDE ulomak je pseudodokument, pa ide s
**`passage: `**, jer se uspoređuje s dokumentima. Korisnikovo pitanje, ako se
ikad ugrađuje izravno, ide s `query: `. Zamjena prefiksa mjerljivo kvari e5.

**Tvrdo pravilo:** HyDE izlaz hrani **samo vektorsku granu**, nikad BM25. Ulomak
je izmišljen; ako u njemu piše pogrešan broj članka, u vektorskom prostoru to je
sitan pomak, a u BM25 je izravan lažni pogodak s visokim rangom. Ovo je najvažnija
sigurnosna ograda u cijelom sloju 2.

### Trošak

Po institutu: 1 poziv za snop, 1 poziv za HyDE, plus ugradnja 2-4 ulomka
(oko 0,2 s po ulomku na ovom CPU-u). Za 10 instituta: 20 poziva i par sekundi
računanja. Zanemarivo.

---

## Sloj 3: DOHVAT

### Što se mijenja u odnosu na postojeći `vektor.py`

Stroj je dobar, prezentacija ga guši. Tri izmjene, po važnosti:

**1. Agregacija na dokument prije rezanja.** Ovo je izmjereno najskuplja greška
sadašnjeg CLI-ja: na dokumentnoj razini top 200 sadrži **16/17 zlatnih**, a
`-k 8` nad čancima daje samo **5-6 različitih odluka**, jer jedna presuda zauzme
tri mjesta. Ocjena dokumenta:

```
ocjena(dok) = max(RRF čanaka) + λ · log(1 + broj različitih čanaka iznad praga)
```

Drugi član nije kozmetika: presuda koja o institutu govori kroz šest točaka
obrazloženja gotovo sigurno o njemu **odlučuje**, a presuda s jednim pogotkom ga
vjerojatno **spominje**. To je prva i besplatna aproksimacija sloja 4. λ oko 0,3,
ali vidi upozorenje o preprilagodbi u sloju 6.

**2. Tri grane umjesto dvije.** BM25 nad čancima (`chunks_fts`), vektor nad
čancima, i **BM25 nad cijelim odlukama** (`odluke_fts`, preko `store.trazi`).
Treća grana postoji zbog neugodne činjenice u nastavku.

**3. Unija po institutima s podrijetlom.** Svaki kandidat nosi zapis koji ga je
institut i koji upit doveo. To treba sloju 4 (koji institut ocjenjujemo) i sloju
6 (koji je upit donio kojeg zlatnog).

### Neugodna činjenica: indeks pokriva 18,6 % korpusa

`chunks` sadrži 17290 čanaka nad **454 od 2439 odluka**. Da je 17/17 zlatnih
indeksirano je sreća uzorka (indeksiralo se ciljano), a ne svojstvo sustava. Za
novi korisnički problem vektorska grana danas vidi manje od petine korpusa, i
brojka 16/17 se na njega **ne prenosi**.

Procjena dovršetka: 38,1 čanaka po odluci, preostalo 1985 odluka, dakle oko
**75 600 novih čanaka**. Pri izmjerenih 5,0 čanaka/s to je **oko 4,2 sata** na
ovom CPU-u, jednokratno, inkrementalno, može preko noći. Rezultat: ~93 000
čanaka, oko 143 MB embeddinga. Ovo je prioritet nula, prije svakog drugog rada na
dohvatu.

### Što ovdje NIJE potrebno

**ANN indeks (faiss, hnswlib): ne.** `_vektor()` učita sve embeddinge i napravi
jedno množenje matrica. Danas: 17290 × 384 float32 = 26,6 MB, množenje reda
veličine 10 ms. Nakon punog indeksiranja: 143 MB i oko 50 ms. Aproksimativni
susjedi imaju smisla iznad otprilike milijun čanaka. Ovdje bi donijeli ovisnost,
indeks koji se mora održavati i gubitak točnosti, a uštedjeli desetinke sekunde.

**Vraćanje na portal: da, ali kao zaseban put.** Korpus je prikupljen ciljano oko
šumarske tematike. Institut nužnog prolaza vodi se u izvanparnici (upisnik R1), a
tih u korpusu ima malo. Kad sloj 3 za neki institut vrati mršav skup, snop upita
iz sloja 2 ide u `anon.harvest`, uz dvije zamke iz `metodologija.md`: zadana
logika portala je **OR**, pa upit bez navodnika vraća smeće, i postoji tvrdi
strop od 10 000 pogodaka po upitu.

**Podudaranje po oznaci predmeta mora biti neosjetljivo na dijakritiku.** Pri
mjerenju su dvije zlatne odluke "nedostajale" jer je oznaka `Gž`, a tražilo se
`Gz`. FTS ima `remove_diacritics 2`, ali usporedba metapodataka nema. Dvije od
sedamnaest, dakle 11,8 postotnih bodova odziva, izgubljeno na jednom kvačici.

---

## Sloj 4: PRESLAGIVANJE (SPOMINJE naspram ODLUČUJE)

Ovo je sloj u kojem preciznost nastaje. Kandidata je 200-400, izlaza treba 40-80.

### Signali, redom od besplatnih prema skupima

**a) Mjesto pogotka u dokumentu.** `cankiraj()` čuva uvod prije prve numerirane
točke kao zaseban čanak, dakle **čanak `ord = 0` sadrži izreku**. Pogodak u
izreci vrijedi višestruko više od pogotka u prepričavanju navoda stranaka.
Razlikovni izrazi: `"tužitelj u tužbi navodi"`, `"tuženik u odgovoru na tužbu
osporava"` (institut se samo spominje) naspram `"sud je utvrdio"`, `"ocjenom
izvedenih dokaza"`, `"valjalo je odlučiti kao u izreci"` (o institutu se
odlučuje).

**b) Gustoća.** Broj različitih čanaka s leksikom instituta, normiran duljinom
(`odluke_meta.duljina` postoji). Već ugrađeno u ocjenu iz sloja 3.

**c) Suprotstavljenost stranaka.** Traži se sazviježđe: **maskirano ime fizičke
osobe** na jednoj strani i **imenovana javnopravna osoba** na drugoj (Republika
Hrvatska, Hrvatske šume d.o.o., Općinsko državno odvjetništvo, Ministarstvo
poljoprivrede). Anonimizacija portala tu neočekivano pomaže: fizičke osobe su
maskirane, pravne nisu, pa je razlika strojno vidljiva. Presuda u sporu dviju
fizičkih osoba o međi može spominjati istu doktrinu, ali ne pokazuje kako se
prolazi protiv države, a to je ono što korisniku treba.

**d) Vrsta postupka i upisnik.** Iz sloja 1 dolazi očekivani upisnik. Nužni
prolaz je izvanparnica: `R1`, ne `P`. Dosjelost je parnica: `P`, pa žalbeno `Gž`.
Upisnik je u shemi (`upisnici.oznaka`, indeks `ix_strat_upisnik`), pa je ovaj
filtar upit, a ne model. Također `sudovi.vrsta`: trgovački sud u sporu fizičke
osobe o dosjelosti je gotovo sigurno drugi predmet.

**e) Vrsta zahtjeva iz izreke.** `"prijedlog radi osnivanja nužnog prolaza"`,
`"tužbeni zahtjev radi utvrđenja prava vlasništva"`, `"radi utvrđenja i
uknjižbe"`. Vadi se iz čanka `ord = 0`.

**f) Citirani propisi.** `zakonsko_kazalo` je popunjeno za 94 % korpusa. Institut
iz sloja 1 nosi popis očekivanih propisa; podudaranje je spoj tablica, ne model.
Ovo je jeftin i vrlo čist signal koji stari postupak uopće nije koristio, iako je
podatak već bio u bazi.

**g) Tek onda jezični model.** Na preostalih 60-100 kandidata, s izrekom i 2-3
najbolja čanka, s eksplicitnim mjerilom: odlučuje li o institutu, tko je protiv
koga, koji je ishod, koja je nosiva rečenica.

### Zašto ne ručno bodovanje

Zato što je izmjereno koliko vrijedi. `analiza_cl55.py` ima osam ručno
otežanih signala; na zlatnom skupu su upalila dva, i jedan od ta dva
(`ugovor o zamjeni nekretnina`, 6/17) je **lažno pozitivan**: hvata nabrajanje
načina stjecanja u obrazloženju, a ne institut. Signali `okrupnjivanje`,
`gospodarska jedinica`, `odluka o zamjeni šuma`, `srazmjerna vrijednost` i
`ministar sklapa ugovor` daju **0/17**. Preciznost cjeline: 0,011. Jedna zlatna
je zbog kazne od -3 bodova pala na **#2381 od 2439**.

Ručni bodovi po ključnim riječima nad pravnim tekstom su u ovom projektu
dokazani način da se ne uspije. Signali a-f gore preživljavaju samo zato što su
**strukturni** (mjesto u dokumentu, upisnik, stranke, spoj po propisu), a ne
leksički pogodci s izmišljenim težinama.

### Iskreno o unakrsnom koderu

Generički višejezični cross-encoder na 400 čanaka na ovom CPU-u traje nekoliko
minuta, dakle izvedivo je. Ali on je treniran za **tematsku relevantnost**, a
tematsku relevantnost su BM25 i e5 već dali. Razlika koja nam treba, "odlučuje
naspram spominje", nije tematska i on je nije vidio u treningu. Bez označenih
parova za doučavanje očekivani dobitak je blizu nule. Preskočiti dok ne postoji
nekoliko stotina ručno označenih parova.

---

## Sloj 5: PROVJERA (protivnički prolaz)

Zadnji sloj ne rangira nego **pokušava srušiti** ono što je preživjelo.

### Ulaz i uloga

Prolaz dobiva: tvrdnju koju bi presuda trebala poduprijeti (iz polja "zašto
pristaje" u dosjeu instituta), doslovne čanke, i izreku. **Ne dobiva** ocjenu ni
obrazloženje iz sloja 4, da ne nasljeđuje njegovo uvjerenje. Odgovara na četiri
pitanja:

1. **Odlučuje li ili spominje?** Ako institut stoji samo u prepričanim navodima
   stranaka ili u nabrajanju načina stjecanja, presuda ispada.
2. **Podupire li tvrdnju ili je lažni prijatelj?** Lažni prijatelj je izmjeren, ne
   hipotetski: TS Split P-422/2025-19 je stari klasifikator stavio na **#1 od
   2439**, a to je presuda u kojoj je stranka **izgubila**.
3. **Koji je ishod i tko je izgubio?** Izreka daje odgovor; `RE_USVOJEN` i
   `RE_ODBIJEN` iz `analiza_cl55.py` su polazna točka, izreka je razlučiva u 701
   odluci u korpusu (457 odbijeno, 244 usvojeno).
4. **Ako je izgubljeno, zašto?** Ovo je najvrednije polje u cijelom cjevovodu.

### Protuprimjeri nisu otpad, nego druga polovica proizvoda

Presuda u kojoj je stranka izgubila kaže **što je trebalo dokazati**, a to je
točno ono što korisnik mora znati prije nego što pokrene postupak. Iz zlatnog
skupa, četiri protuprimjera pretvaraju se izravno u popis dokaza:

| protuprimjer | razlog gubitka | što iz toga slijedi |
|---|---|---|
| TS Zagreb P-1687/2024-16 | nije dokazano da nije bila šuma na 16.10.1990. | pribaviti dokaz o statusu zemljišta na taj datum |
| ZS Slavonski Brod Gž-69/2023-4 | elaborat bez potvrde katastra | geodetski elaborat mora imati ovjeru |
| OS Šibenik P-1886/2019-55 | svjedoci nisu identificirali baš taj dio | svjedoci moraju pokazati točnu česticu na skici |
| ZS Rijeka Gž-1989/2017-3 | put kao javno dobro, nenadležnost suda | provjeriti status puta prije izbora pravnog puta |

Zato izlaz cjevovoda ima **dvije obvezne klase**: potporne odluke i
protuprimjeri. Cjevovod koji vrati samo pobjede daje krivu sliku izgleda i
prešućuje dokazni teret. Odziv se u sloju 6 mjeri odvojeno za obje klase.

### Uzemljenje citata

Mehanička ograda protiv izmišljanja: svaka tvrdnja u izlazu nosi `doc_id`,
redni broj čanka i **doslovan navod**. Skripta provjerava je li navod podniz
teksta tog čanka nakon normalizacije razmaka. Tvrdnja bez navoda koji se nalazi
u bazi se **briše**, bez rasprave. Ovo je dvadesetak redaka koda i uklanja
najopasniju klasu greške u pravnom alatu.

Uz to se provjeravaju `pravomocnost` i `datum`: nepravomoćna prvostupanjska
presuda vrijedi manje, a odluka o izvanparničnom postupku donesena prije
1. 1. 2024. traži napomenu o novom ZIP-u (NN 59/23).

---

## Sloj 6: MJERENJE

### Zlatni skup i mjere

17 odluka, tri razreda: 9 jako korisnih, 4 protuprimjera, 4 slabije. Mjeri se na
**dokumentnoj razini**, jer je korisniku jedinica presuda, ne čanak.

| mjera | zašto |
|---|---|
| recall@{10, 20, 50, 200} | osnovna |
| recall@k samo za razred JAKO | jedina koja stvarno nosi vrijednost |
| recall@k za protuprimjere | druga polovica proizvoda, mjeri se odvojeno |
| različitih odluka u top-k | jer je stari CLI na k=8 vraćao 5-6 odluka |
| rang prve JAKO presude | stari postupak: **#91 od 2439** |
| preciznost@10 | stari klasifikator: 0,011 na 88 kandidata |
| udio tvrdnji s provjerljivim navodom | mora biti 1,00 |

### Referentne točke koje treba nadmašiti

| postupak | odziv | napomena |
|---|---|---|
| frazna pretraga (stara) | **0/17** | fraza ima 0 pogodaka u korpusu |
| `analiza_cl55.py`, prag 6 | 1/17 | i taj jedan je protuprimjer, na #1 |
| hibrid, korisnikova formulacija, k=8 | 0 JAKIH | "otkup parcele od države" |
| hibrid, laički upit o pristupu, k=8 | 3 JAKE | sreća formulacije |
| hibrid, dokumentna razina, top 200 | **16/17** | gornja granica postojećeg stroja |

Cilj novog cjevovoda: **svih 9 JAKIH u top 20 dokumenata**, najmanje 3 od 4
protuprimjera u izlazu, udio provjerljivih navoda 1,00. Gornja granica 16/17
pokazuje da je to pitanje formulacije i preslagivanja, ne dohvata.

### Ablacije, jer inače ne znamo što je pomoglo

Isključi jedan sloj, izmjeri, vrati. Očekivanje, koje mjerenje treba potvrditi
ili oboriti:

| isključeno | očekivani gubitak | temelj procjene |
|---|---|---|
| sloj 1 (panel), ostaje korisnikova formulacija | **najveći** | 0 JAKIH na "otkup parcele" |
| morfološko širenje (`*`) | velik, uz nulti trošak | 8/17 naspram 13/17 |
| agregacija na dokument | velik | 5-6 odluka naspram 200 |
| HyDE | umjeren | pomiče vektorsku granu, ne BM25 |
| filtar po upisniku i propisu | umjeren za preciznost | besplatno, podatak već postoji |
| unakrsni koder | blizu nule | nema podataka za doučavanje |

### Upozorenje o preprilagodbi, i to ozbiljno

**17 zlatnih odluka je vrlo malo.** Jedna presuda vrijedi 5,9 postotnih bodova
odziva. Svako podešavanje λ, praga, konstante RRF-a ili duljine prefiksa protiv
tih 17 je preprilagodba, i izmjereni napredak bit će djelomično iluzija. Tri
mjere:

1. Zlatni skup se **zamrzne** i ne dopunjuje nakon što je viđen rezultat.
2. Podešavanje parametara ide s izostavljanjem po jednog primjera
   (leave-one-out), ne na punom skupu.
3. Potreban je **drugi činjenični sklop** kao skup za provjeru, s vlastitim
   zlatnim skupom, koji se ne gleda dok cjevovod nije zamrznut. Bez njega tvrdnja
   "cjevovod radi" znači samo "cjevovod radi na ovom slučaju".

Uz to, korpus je prikupljen ciljano oko šumarske tematike (Zakon o šumama je
citiran u 1297 od 2439 odluka), pa se brojke ne prenose na bazu od 1,17 milijuna
odluka. To je već zapisano u `baseline.md` i `mjerenje.md` i vrijedi i ovdje.

---

## Ima li RNN ikakvu ulogu ovdje

Kratak odgovor: **ne**, i posezanje za njom je krivo postavljena dijagnoza.

Duži odgovor, po mogućim mjestima ugradnje.

**Kao koder za dohvat.** Ne. Vrijednost `multilingual-e5-small` ne dolazi od
arhitekture nego od predtreniranja na milijardama tokena na stotinu jezika.
Rekurentna mreža trenirana na 2439 dokumenata (oko 93 000 čanaka, reda veličine
nekoliko desetaka milijuna tokena) ne bi bila slabija za nekoliko postotaka nego
za red veličine. Nijedna arhitektura ne nadoknađuje nepostojeće podatke za
predtreniranje. Uz to, jednosmjerna rekurencija komprimira dokument u jedan
skriveni vektor, pa duge presude gubi po konstrukciji; upravo taj problem je
motivirao pažnju 2015. i transformere 2017.

**Kao klasifikator instituta.** Ne. Imamo 17 označenih primjera. Ako se ikad
skupi nekoliko tisuća, referentna točka nije RNN nego ono što već postoji u
`baseline.py`: TF-IDF s riječnim i znakovnim n-gramima plus logistička regresija.
Znakovni n-grami hvataju hrvatsku sklonidbu i nedosljednu dijakritiku, što je
ovdje pola posla, a rade u minutama na CPU-u. Na skupovima ove veličine
rekurentne mreže tu osnovicu tipično ne nadmaše, a kad je nadmaše, razlika je
manja od raspršenja među podjelama.

**Kao preslagivač.** Ne. Preslagivanje traži unakrsnu pažnju između upita i
dokumenta. Rekurentni preslagivači su napušteni upravo zato što upit sabiju u
vektor fiksne duljine prije nego što vide dokument, a to je suprotno od onoga što
sloj 4 mora raditi.

**Kao označivač nizova (jedino mjesto gdje nije besmislena).** BiLSTM s CRF
slojem je legitimna i podatkovno štedljiva arhitektura za označavanje tokena:
uloge stranaka, granice izreke, datumi, pozivi na odredbe. Ali i tu, iskreno:
`zakonsko_kazalo` već pokriva 94 % korpusa i daje citirane propise s NN
brojevima, `odluke_meta` već ima datum, vrstu, upisnik i sud, a izreka se
razlučuje iz strukture čankiranja. Većina onoga što bi označivač trebao izvući
**već je izlučena pri dohvatu**. Ostatak pokrivaju regularni izrazi nad
sazviježđem stranaka. Arhitektura nije apsurdna, potreba ne postoji.

**Zašto se ideja uopće javlja.** Zato što se promašaj čita kao nedostatak
kapaciteta modela, a on to nije. Vodeći upit je imao **nula pogodaka u korpusu**.
Nijedan model na svijetu, rekurentan ili ne, ne popravlja upit čiji niz znakova
u korpusu ne postoji. Preostalih pet zlatnih izgubila je izostala zvjezdica u
FTS5 upitu. To su redom pogreške **predstavljanja znanja i formulacije upita**,
a ne pogreške modeliranja niza.

**Ako je pitanje bilo "spada li ovamo neuronska mreža uopće".** Spadaju dvije, i
obje su već tu: transformerski koder `multilingual-e5-small` u sloju 3 i jezični
model u slojevima 1, 2, 4 i 5. Nijedna nije rekurentna, i teško je zamisliti
izmjenu činjenica koja bi taj izbor promijenila.

---

## Što se u ovom cjevovodu NE isplati na 2439 odluka

Popis je jednako važan kao arhitektura, jer određuje gdje se ne troši vrijeme.

| komponenta | presuda | razlog |
|---|---|---|
| ANN indeks (faiss/hnsw) | **ne** | 26,6 MB danas, 143 MB nakon punog indeksiranja; puno množenje traje desetke ms |
| doučavanje embeddinga na korpusu | **ne** | 17 označenih primjera; rizik preprilagodbe na šumarstvo je veći od dobitka |
| trenirani preslagivač | **ne** | nema podataka za trening |
| generički unakrsni koder | **granično** | optimizira tematsku relevantnost, koju već imamo |
| podešavanje konstante RRF-a (k=60) | **ne** | razlike su unutar šuma na 17 primjera |
| graf citiranja | **ne kao graf** | ali spoj po `zakonsko_kazalo` (94 % pokrivenosti) da, i to odmah |
| hrvatski lematizator | **kasnije** | bolji od `*`, ali traži ponovno indeksiranje |
| **dovršetak vektorskog indeksa** | **odmah** | 18,6 % pokrivenosti je stvarna gornja granica sustava |
| **morfološki prefiksi** | **odmah** | 8/17 naspram 13/17, trošak je jedan znak |
| **agregacija na dokument** | **odmah** | 5-6 odluka naspram 200, trošak je jedan `GROUP BY` |

Prva tri retka s dna popisa daju veći dobitak od svega ostalog zajedno i nemaju
veze sa strojnim učenjem.

---

## Načini na koje ovaj cjevovod može zakazati

Sve navedeno je predviđanje, ne izmjereno stanje.

**Panel se sruši u jednu točku.** Ako svi kutovi dijele preambulu s korisnikovom
kvalifikacijom, tri prolaza daju jedan odgovor i usidravanje se vraća, samo
skuplje. Ograda: činjenice bez kvalifikacije, kutovi s različitim ulaznim
kategorijama, provjera da se izlazi razlikuju.

**Model izmisli institut.** Ograda: svaki institut mora biti vezan uz odredbu
koja se provjerava protiv `zakoni.py` ili `zakonsko_kazalo`; nepotvrđeni ispadaju
iz BM25 grane, a u vektorsku ulaze samo kroz HyDE.

**Korpus jednostavno nema odgovor.** Vrlo moguće za nužni prolaz: prikupljanje je
išlo oko šumarske tematike, izvanparničnih R1 predmeta ima malo. Ograda: prazan
ili mršav skup po institutu okida `anon.harvest` sa snopom upita iz sloja 2, uz
navodnike (zadana logika portala je OR) i uz strop od 10 000 pogodaka.

**Mjerenje laže samom sebi.** Najvjerojatniji od svih. 17 primjera, podešavanje
protiv njih, i lijepa tablica koja ne znači ništa. Ograda: zamrznut zlatni skup,
leave-one-out, i drugi činjenični sklop kao skup za provjeru.

**Tiha migracija baze.** Već se dogodilo jednom tijekom mjerenja: `store.py` je
zamijenjen shemom 2 i prvi `veza()` je migrirao `corpus.sqlite` sa 163 na 116 MB
bez izričite naredbe. Korpus je nakon provjere bio cjelovit, ali automatska
migracija pri otvaranju veze je opasnost usred mjerenja. Ograda: mjerne skripte
otvaraju bazu preko `store.otvori_ro`, koji ne migrira, i zapisuju
`PRAGMA user_version` uz svaki rezultat.

---

## Redoslijed izvedbe

1. **Dovršiti vektorski indeks** (~4,2 h, jednokratno). Bez toga svaka brojka o
   dohvatu vrijedi za 18,6 % korpusa.
2. **Agregacija čanak -> dokument** u `vektor.py`, plus izlaz na razini odluke.
   Jedan `GROUP BY`, najveći trenutni dobitak.
3. **Tablica morfoloških prefiksa**, provjerena brojenjem, zamrznuta u repozitoriju.
4. **Mjerna skripta i zlatni skup** kao datoteka, s podudaranjem oznaka
   neosjetljivim na dijakritiku (`Gž`/`Gz`). Prvo mjerenje daje polazne brojke.
5. **Sloj 1 i 2** kao poziv modela s izlazom u strogom obliku. Tek sada se mjeri
   pomak koji donosi formulacija.
6. **Sloj 4**, redom: strukturni signali (besplatni), pa model na ostatku.
7. **Sloj 5** s uzemljenjem citata i obveznim protuprimjerima.
8. Ablacije, pa drugi činjenični sklop kao provjera.

Koraci 1-4 nisu strojno učenje i donose većinu dobitka. Koraci 5-7 su ono što
stari postupak uopće nije imao i ono zbog čega se cjevovod zove lov, a ne
pretraga.
