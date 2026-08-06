# -*- coding: utf-8 -*-
"""
Lokalni korpus pravnog gradiva: SQLite + FTS5, pripremljen za mjerilo Sloja 1
(1,17 milijuna odluka) prema docs/arhitektura-korpusa.md.

Ovo je "ius-info kod kuce": jednom preuzeta odluka ostaje zauvijek na disku,
crawl je inkrementalan (ne dohvaca ponovno ono sto vec imas), a nad cijelim
korpusom radi trenutna full-text pretraga bez ijednog mreznog zahtjeva.

Sto se promijenilo u shemi 2 (i zasto)
--------------------------------------

1.  Tekst je odvojen od metapodataka i komprimiran zlib-om, razina 6.
    Mjereno na 200 odluka: omjer 0,3372 (ustedi 66,3 %), kompresija
    1,072 ms/dok, dekompresija 0,124 ms/dok. Razina 9 donosi jos 0,04 %
    uz 19 % vise CPU-a, razina 1 gubi 5,3 postotna boda. Razina 6 je izbor.
    Projekcija na puni korpus: 8,15 GB umjesto 23,03 GB.

2.  `odluke` vise nije tablica nego POGLED koji dekomprimira u letu.
    Tablica s metapodacima je `odluke_meta` i namjerno nema tekst: ista
    2439 odluka u jednoj tablici s tekstom zauzimaju 50,8 MB, a sama
    metatablica 3,55 MB, dakle puno skeniranje za fasetiranje i
    stratifikaciju ima 14 puta manju povrsinu.

    Posljedica za pozivatelja: NIJEDNA. `SELECT * FROM odluke` i dalje
    vraca `tekst` i `meta_json` kao obican tekst, `o.rowid` i dalje spaja
    na `odluke_fts`, `store.trazi()` radi isto sto je i radio. Kompresija
    je vidljiva samo onome tko gleda velicinu datoteke.

3.  Sifarnici `sudovi` i `upisnici`: 68 sudova i 60 upisnika na 2439
    odluka. Normalizacija stedi oko 70 B/dok, ali vaznije je da GROUP BY
    po sudu postaje brz i tocan, sto je temelj stratificiranog uzorkovanja.

4.  `uzorak_kljuc` je DETERMINISTICAN: prvih 8 bajtova sha256(id + sol).
    Time je uzorak ponovljiv i kad se baza gradi iznova ili drugim
    redoslijedom, sto je uvjet da netko treci moze provjeriti nalaz.
    Uz indeks (sud_id, godina, uzorak_kljuc) nasumican izbor unutar sloja
    postaje raspon po indeksu s LIMIT-om, dakle O(k) umjesto
    ORDER BY random() koji nad 1,17 M redaka mora proci sve.

5.  `nacin_odabira`: 'ciljano' | 'uzorak' | 'delta' | 'puni'. Postojecih
    2439 odluka prikupljeno je ciljano oko sumarske teme i NE SMIJU se u
    analizama tretirati kao slucajan uzorak. Bez ovog stupca ta se razlika
    gubi u trenutku spajanja baza.

6.  WAL, synchronous=NORMAL, 256 MB cachea, batch upis (`spremi_mnogo`).
    Mjereno: 511 odluka/s, sto je 60 do 250 puta brze od pristojnog crawla.

Sto se promijenilo u shemi 3 (dvije vrste gradiva)
--------------------------------------------------

Korpus vise ne drzi samo sudske odluke nego i doktrinu (clanci iz casopisa,
prije svega HRCAK preko OAI-PMH). Odluka je jedno, misljenje o odluci je
drugo, ali oboje se trazi istim upitom, pa je nosac isti.

7.  Stupac `gradivo` u `odluke_meta`: 'odluka' | 'doktrina'. Stupac, ne
    zasebna tablica, jer bi zasebna tablica znacila i drugi FTS indeks, a
    onda i spajanje dvaju rangiranja pri svakom upitu. Ovako je bm25 jedan
    i usporediv, a `store.trazi()` ostaje jedan poziv.

8.  Polja doktrine stoje na kraju `odluke_meta`, a ima ih samo osam.
    Kratkoca popisa je mjerena odluka, ne ukus.

    Provjereno nad 20 000 odluka (dbstat, SUM(payload), identicni podaci u
    obje varijante): stupac stoji 1 B po retku odluke i kad je NULL, jer
    SQLite zavrsne NULL stupce NE izostavlja iz zapisa. Ocekivao sam da
    izostavlja; ne izostavlja.
        stupci sheme 2                        126,44 B/red
        + 14 stupaca doktrine (svi NULL)      140,44 B/red   (+14,00)
        + `gradivo` NOT NULL 'odluka'         147,44 B/red   (+21,00)
    Dakle pun bibliografski opis dizao bi metatablicu za 16,6 %, i to na
    tablici koja postoji upravo zato da bude mala za puni sken (tocka 2).
    S osam stupaca rast je 15 B/red, oko 11,9 %, odnosno 17,6 MB na
    projekciji od 1,17 M odluka.

    Isprobana je i varijanta sa zasebnom tablicom `doktrina` i poljima kroz
    skalarne podupite: metatablica raste samo za `gradivo` (7 B/red), a
    izmjereno vrijeme upita je isto (SELECT * nad 50 redaka 1,036 naspram
    1,074 ms, FTS spoj 186,8 naspram 189,3 ms, pogled se u obje varijante
    spljosti). Odbijena je jer dobitak od 8 B/red ne placa drugu tablicu u
    svakom rucnom SQL upitu nad korpusom.

    Ono sto NIJE dobilo stupac ima svoje mjesto: kljucne rijeci clanka idu
    u postojeci `kazalo` (i time odmah u FTS), tip rada u `vrsta`
    ('izvorni znanstveni rad' ondje gdje odluka ima 'presuda'), a ISSN,
    jezik i pojedinacni dijelovi sveska u `meta` JSON.

9.  Licenca je OBAVEZNA za doktrinu, zajedno s URL-om izvora. `spremi()`
    odbija zapis doktrine bez `url` i bez `licenca` iznimkom. Hrcak je
    otvoreni pristup, ali licenca se razlikuje po casopisu i po clanku, pa
    zapis bez licence ne bi imao smisla ni pravno ni bibliografski.

    `redistribucija` je izvedena iz licence funkcijom
    `procijeni_redistribuciju()` i ima tri vrijednosti:
        'slobodna'   CC BY, CC BY-SA, CC0, javno dobro
        'uvjetna'    CC s NC ili ND clanom: dijeljenje je dopusteno, ali
                     pod uvjetima koje korpus sam ne moze jamciti
        'zabranjena' izricito "sva prava pridrzana"
        NULL         licenca zapisana, ali nije prepoznata
    Samo 'slobodna' smije van s ovog racunala bez daljnje provjere. Ostalo
    se drzi lokalno, za osobno istrazivanje.

10. FTS5 indeksira i jedno i drugo, u istoj tablici `odluke_fts`, uz tri
    nova stupca: `naslov`, `autori`, `casopis`. Za odluke su prazni.
    Izmjereno na 20 000 odluka: prazan stupac stoji 3,07 B/red u
    `odluke_fts_docsize`, a u `odluke_fts_data` nista (0,00 B/red), dakle
    oko 3,6 MB na punom korpusu za sva tri.

    Filtriranje po vrsti radi `store.trazi(..., vrsta=)` preko
    `odluke_meta.gradivo`, a ne preko MATCH-a, da rijec "doktrina" u tekstu
    odluke ne bi postala filtar.

    Sazetak clanka (`sazetak`) zivi u `tekstovi` kao `vrsta_zapisa='sazetak'`,
    komprimiran kao i sve ostalo, i indeksira se zajedno s punim tekstom.
    Za clanke kojima puni tekst nije dostupan pod jasnom licencom sazetak je
    jedino sto korpus ima, pa mora biti pretraziv.

Migracija: `veza()` sama prepozna staru bazu (shemu 1 ili 2) i prevede je bez
gubitka. Nadogradnja 2 -> 3 je aditivna (ALTER TABLE ADD COLUMN plus ponovna
izgradnja FTS indeksa); nijedan postojeci redak se ne prepisuje.
Rucno: `python store.py --migriraj [--baza PUT]`.

Baza: PRESUDE/data/corpus.sqlite
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sqlite3
import sys
import unicodedata
import zlib

from common import DATA_DIR

DB_PATH = DATA_DIR / "corpus.sqlite"

SHEMA_VERZIJA = 3

# Razina zlib-a za tekst odluke. 6 je izmjereni optimum (vidi docstring).
KOMP_RAZINA = 6
# Ispod ove granice zlib zaglavlje pojede dobitak, pa se sprema sirovi UTF-8
# (stupac `komp` = 0). Pogled to razrjesava sam, pa citanje ne primjecuje.
KOMP_PRAG_B = 200

# Sol za deterministicni uzorak. Mijenjanje ove vrijednosti mijenja SVE
# uzorke; ako se ikad promijeni, stari nalazi se vise ne mogu reproducirati.
UZORAK_SOL = b"presude-korpus-v2"

VRSTE_ODABIRA = ("ciljano", "uzorak", "delta", "puni")

# Vrste gradiva u korpusu. 'odluka' je zadana zbog 2439 vec prikupljenih
# odluka: nadogradnja sheme ih ne smije morati dirati.
VRSTE_GRADIVA = ("odluka", "doktrina")

# Stupci koje shema 3 dodaje na kraj `odluke_meta`, tim redom.
#
# Popis je namjerno kratak. Izmjereno na 20 000 odluka (dbstat, SUM(payload)):
# svaki stupac stoji 1 B po retku odluke i kad je NULL, jer SQLite zavrsne
# NULL stupce NE izostavlja iz zapisa. Pun bibliografski opis (14 stupaca)
# dizao je metatablicu sa 126,44 na 147,44 B/red, dakle 16,6 %, na tablici
# koja postoji upravo zato da bude mala za puni sken.
#
# Zato su stupci samo ona polja po kojima se filtrira ili se bez njih ne moze
# navesti izvor. Ostalo ima svoje mjesto:
#     kljucne rijeci  -> `kazalo`   (postojeci stupac, vec u FTS-u)
#     tip rada        -> `vrsta`    ('izvorni znanstveni rad' umjesto 'presuda')
#     ISSN, jezik, svezak, broj, stranice pojedinacno -> `meta` (JSON, zipan)
DOKTRINA_STUPCI = (
    ("naslov", "TEXT"),          # naslov clanka
    ("autori", "TEXT"),          # 'Prezime, Ime; Prezime, Ime'
    ("casopis", "TEXT"),
    ("citat", "TEXT"),           # 'Vol. 74 (2024), 2, 199-230', kako se navodi
    ("doi", "TEXT"),
    ("licenca", "TEXT"),         # doslovno kako stoji na izvoru
    ("licenca_url", "TEXT"),
    ("redistribucija", "TEXT"),  # izvedeno, vidi procijeni_redistribuciju
)

NOVI_STUPCI = (("gradivo", "TEXT NOT NULL DEFAULT 'odluka'"),) + DOKTRINA_STUPCI

# Polja doktrine koja `spremi()` cita iz zapisa i pise u odluke_meta.
_DOKTRINA_POLJA = tuple(ime for ime, _ in DOKTRINA_STUPCI)

REDISTRIBUCIJA = ("slobodna", "uvjetna", "zabranjena")


def procijeni_redistribuciju(licenca: str | None) -> str | None:
    """
    Iz teksta licence izvodi smije li se zapis dalje dijeliti.

    Vraca 'slobodna', 'uvjetna', 'zabranjena' ili None (licenca zapisana, ali
    nije prepoznata). None i 'zabranjena' znace isto u praksi: ne izlazi s
    ovog racunala. Razlika je u tome sto None trazi da netko pogleda.

    Namjerno konzervativno: NC i ND clanovi daju 'uvjetna', a ne 'slobodna',
    jer uvjet (nekomercijalnost, zabrana prerade) nije nesto sto korpus moze
    jamciti umjesto onoga tko gradivo dalje koristi.
    """
    if not licenca:
        return None
    # Hrcak licencu daje i kraticom ("CC BY-NC-ND 4.0") i punim imenom
    # ("Creative Commons Attribution NonCommercial NoDerivatives"), pa se
    # prepoznaju oba oblika.
    t = re.sub(r"[^a-z0-9]+", " ", _bez_dijakritika(licenca).lower()).strip()
    if not t:
        return None
    if "sva prava pridrzana" in t or "all rights reserved" in t:
        return "zabranjena"
    if ("cc0" in t or "public domain" in t or "javno dobro" in t
            or re.search(r"\bpdm\b", t)):
        return "slobodna"

    cc = "creative commons" in t or re.search(r"\bcc\b", t)
    atribucija = re.search(r"\bby\b", t) or "attribution" in t
    if not (cc or atribucija):
        return None
    if (re.search(r"\b(nc|nd)\b", t) or "noncommercial" in t
            or "non commercial" in t or "noderiv" in t or "no deriv" in t):
        return "uvjetna"
    if atribucija or re.search(r"\bsa\b", t) or "sharealike" in t:
        return "slobodna"
    return None


# ------------------------------------------------------------------ PRAGMA ---
# page_size 4096: 8k/16k/32k daju vecu datoteku (17,0 / 18,3 / 18,7 MB naspram
#   17,7) uz zanemarivu razliku u citanju (0,032 vs 0,026 ms/dok).
# synchronous NORMAL: 511 odl/s; OFF daje 520, dakle 2 % za gubitak izdrzljivosti.
# wal_autocheckpoint 4000: oko 16 MB WAL-a tijekom masovnog upisa.
PRAGME = (
    ("page_size", 4096),          # djeluje samo prije prvog upisa
    ("journal_mode", "WAL"),      # citanje ne blokira upis tijekom dugog crawla
    ("synchronous", "NORMAL"),
    ("temp_store", "MEMORY"),
    ("cache_size", -262144),      # 256 MB stranicnog cachea
    ("foreign_keys", "ON"),
    ("wal_autocheckpoint", 4000),
)

SHEMA = """
CREATE TABLE IF NOT EXISTS sudovi (
    sud_id INTEGER PRIMARY KEY,
    naziv  TEXT NOT NULL UNIQUE,
    razina TEXT,             -- 'opcinski' | 'zupanijski' | 'visoki' | 'vrhovni'
    vrsta  TEXT              -- 'gradanski' | 'trgovacki' | 'upravni' | 'prekrsajni'
);

CREATE TABLE IF NOT EXISTS upisnici (
    upisnik_id INTEGER PRIMARY KEY,
    oznaka     TEXT NOT NULL UNIQUE,     -- doslovan tekst upisnika s portala
    naziv      TEXT
);

-- Metapodaci BEZ teksta, za obje vrste gradiva. Vidi tocke 2 i 7 u
-- docstringu modula. Stupci doktrine su na kraju jer SQLite zavrsne NULL
-- stupce uopce ne zapisuje, pa redak odluke za njih ne placa nista.
CREATE TABLE IF NOT EXISTS odluke_meta (
    rid           INTEGER PRIMARY KEY,   -- gusti kljuc; spona na FTS i tekstove
    id            TEXT NOT NULL UNIQUE,  -- stabilan ID izvora (UUID ANON-a, usud:...)
    izvor         TEXT NOT NULL DEFAULT 'anon',   -- 'anon' | 'usud' | 'nn'
    url           TEXT,
    broj          TEXT,                  -- oznaka predmeta, npr. Rev-533/2015-2
    sud_id        INTEGER REFERENCES sudovi(sud_id),
    upisnik_id    INTEGER REFERENCES upisnici(upisnik_id),
    datum         TEXT,                  -- ISO YYYY-MM-DD ako je razlucivo
    godina        INTEGER,               -- izvedeno iz datuma, za stratifikaciju
    vrsta         TEXT,                  -- presuda / rjesenje / odluka
    ecli          TEXT,
    pravomocnost  TEXT,
    kazalo        TEXT,                  -- stvarno kazalo
    zakonsko_kazalo TEXT,                -- citirani propisi s NN brojevima
    eurovoc       TEXT,
    propisi       TEXT,
    duljina       INTEGER,               -- znakova u tekstu (QA + stratifikacija)
    sha256        BLOB,                  -- 32 B; detekcija izmjene bez usporedbe 18 kB
    uzorak_kljuc  INTEGER NOT NULL DEFAULT 0,   -- determinististan, vidi _uzorak_kljuc
    nacin_odabira TEXT NOT NULL DEFAULT 'ciljano',
    dohvaceno     TEXT DEFAULT (datetime('now')),
    -- shema 3 nadalje; sve novo ide na kraj i mora ostati na kraju
    gradivo       TEXT NOT NULL DEFAULT 'odluka',  -- 'odluka' | 'doktrina'
    naslov        TEXT,
    autori        TEXT,
    casopis       TEXT,
    citat         TEXT,          -- svezak, broj i stranice, kako se navodi
    doi           TEXT,
    licenca       TEXT,          -- obavezno za doktrinu, doslovno s izvora
    licenca_url   TEXT,
    redistribucija TEXT          -- 'slobodna'|'uvjetna'|'zabranjena'|NULL
);

-- Tekst i sirovi metapodaci, komprimirani. `vrsta_zapisa` dopusta da uz
-- tekst odluke stoji i sirovi meta zapis, bez sirenja metatablice.
--
-- NAMJERNO obicna (rowid) tablica, ne WITHOUT ROWID. Izmjereno nad stvarnih
-- 4876 zapisa (15,0 MB teksta + 1,1 MB meta, page_size 4096):
--     WITHOUT ROWID   20,35 MB   8344,8 B/dok
--     rowid + PK      18,36 MB   7528,6 B/dok
-- Razlog je granica lokalnog sadrzaja: u indeksnom B-stablu (a WITHOUT ROWID
-- tablica JEST indeks) lokalno stane oko 1 kB po retku, pa gotovo svaki BLOB
-- ode u overflow lanac. U rowid tablici lokalno stane oko 4 kB. Razlika je
-- 816 B/dok, dakle 0,96 GB na punom korpusu, uz jednako brz dohvat po
-- kljucu (0,044 naspram 0,043 ms). Razdvajanje na dvije tablice s
-- `rid INTEGER PRIMARY KEY` stedjelo bi jos samo 69 B/dok (0,08 GB), sto ne
-- placa drugu tablicu.
CREATE TABLE IF NOT EXISTS tekstovi (
    rid          INTEGER NOT NULL REFERENCES odluke_meta(rid) ON DELETE CASCADE,
    vrsta_zapisa TEXT NOT NULL DEFAULT 'tekst',   -- 'tekst' | 'meta' | 'sazetak'
    komp         INTEGER NOT NULL DEFAULT 6,      -- 0 = cisti UTF-8, 6 = zlib-6
    n_bajt       INTEGER,                         -- duljina nekomprimiranog UTF-8
    tijelo       BLOB NOT NULL,
    PRIMARY KEY (rid, vrsta_zapisa)
);

CREATE TABLE IF NOT EXISTS pretrage (
    upit       TEXT,
    izvor      TEXT,
    stranica   INTEGER,
    pogodaka   INTEGER,
    obavljeno  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (upit, izvor, stranica)
);

-- Predizracunate velicine slojeva. Bez toga svaki plan uzorkovanja pokrece
-- agregaciju nad 1,17 M redaka; s tim je plan upit nad nekoliko tisuca redaka.
CREATE TABLE IF NOT EXISTS slojevi (
    sud_id     INTEGER,
    upisnik_id INTEGER,
    godina     INTEGER,
    n          INTEGER NOT NULL,
    osvjezeno  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sud_id, upisnik_id, godina)
) WITHOUT ROWID;

-- Indeksi za stratificirano uzorkovanje. Trosak svih pomocnih indeksa je
-- izmjerenih 151 B/dok, dakle 0,18 GB na punom korpusu.
CREATE INDEX IF NOT EXISTS ix_strat_sud
    ON odluke_meta(sud_id, godina, uzorak_kljuc);
CREATE INDEX IF NOT EXISTS ix_strat_upisnik
    ON odluke_meta(upisnik_id, godina, uzorak_kljuc);
CREATE INDEX IF NOT EXISTS ix_strat_nacin
    ON odluke_meta(nacin_odabira, uzorak_kljuc);
CREATE INDEX IF NOT EXISTS ix_odluke_godina ON odluke_meta(godina, sud_id);
CREATE INDEX IF NOT EXISTS ix_odluke_datum  ON odluke_meta(datum);
CREATE INDEX IF NOT EXISTS ix_odluke_izvor  ON odluke_meta(izvor);
CREATE INDEX IF NOT EXISTS ix_odluke_sha    ON odluke_meta(sha256);

-- Svi indeksi nad gradivom su DJELOMICNI, s uvjetom gradivo='doktrina'.
-- Redak odluke u njih uopce ne ulazi, pa na korpusu od 1,17 M odluka ne
-- kostaju nista: izmjereno, sve tri zauzimaju po jednu stranicu (4096 B) uz
-- 20 000 odluka i nijedan clanak. Puni indeks na (gradivo, godina) stajao je
-- 17,20 B/red, dakle 20 MB na projekciji, za posao koji djelomicni obavlja
-- besplatno.
CREATE INDEX IF NOT EXISTS ix_doktrina_godina
    ON odluke_meta(godina) WHERE gradivo = 'doktrina';
CREATE INDEX IF NOT EXISTS ix_doktrina_casopis
    ON odluke_meta(casopis, godina) WHERE gradivo = 'doktrina';
CREATE INDEX IF NOT EXISTS ix_doktrina_doi
    ON odluke_meta(doi) WHERE doi IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_doktrina_licenca
    ON odluke_meta(redistribucija) WHERE gradivo = 'doktrina';

"""

# ---------------------------------------------------------------- pogledi ---
#
# OBA pogleda dohvacaju spojene vrijednosti SKALARNIM PODUPITIMA, a ne
# JOIN-om. To nije stvar ukusa nego izmjerena razlika od 45 puta.
#
# Pogled ciji FROM sadrzi LEFT JOIN-ove SQLite ne moze "spljostiti" u
# nadredeni upit, pa ga MATERIJALIZIRA: `store.trazi()` je tada za svaki
# upit dekomprimirao CIJELI korpus da bi vratio 5 redaka. Izmjereno na
# 2439 odluka, upit '"stjecanje bez osnove"':
#     pogled s LEFT JOIN-ovima   738,5 ms   (EXPLAIN: MATERIALIZE odluke)
#     pogled sa skalarnim podupitima  16,3 ms
# Na 1,17 M odluka prva varijanta ne bi bila spora nego neupotrebljiva.
# Puno skeniranje pogleda jednako je brzo u obje varijante (571 vs 569 ms),
# dakle podupiti nisu kompromis.
#
# Pogledi su kod, ne podaci: `veza()` ih usporeduje s ovim tekstom i
# ponovno stvara ako se razlikuju.

POGLED_V_ODLUKE = """
CREATE VIEW v_odluke AS
SELECT o.rid AS rid,
       COALESCE(o.broj, '') AS broj,
       COALESCE((SELECT s.naziv FROM sudovi s WHERE s.sud_id = o.sud_id), '') AS sud,
       COALESCE(o.kazalo, '') AS kazalo,
       COALESCE(o.naslov, '') AS naslov,
       COALESCE(o.autori, '') AS autori,
       COALESCE(o.casopis, '') AS casopis,
       COALESCE((SELECT CASE WHEN t.komp = 0 THEN CAST(t.tijelo AS TEXT)
                             ELSE odzipaj(t.tijelo) END
                   FROM tekstovi t
                  WHERE t.rid = o.rid AND t.vrsta_zapisa = 'tekst'), '')
       || COALESCE(char(10) ||
                   (SELECT CASE WHEN z.komp = 0 THEN CAST(z.tijelo AS TEXT)
                                ELSE odzipaj(z.tijelo) END
                      FROM tekstovi z
                     WHERE z.rid = o.rid AND z.vrsta_zapisa = 'sazetak'), '') AS tekst
FROM odluke_meta o
"""

POGLED_ODLUKE = """
CREATE VIEW odluke AS
SELECT o.rid AS rowid,
       o.rid AS rid,
       o.id AS id,
       o.izvor AS izvor,
       o.url AS url,
       o.broj AS broj,
       (SELECT s.naziv FROM sudovi s WHERE s.sud_id = o.sud_id) AS sud,
       o.datum AS datum,
       o.godina AS godina,
       o.vrsta AS vrsta,
       (SELECT u.oznaka FROM upisnici u WHERE u.upisnik_id = o.upisnik_id) AS upisnik,
       o.ecli AS ecli,
       o.pravomocnost AS pravomocnost,
       o.kazalo AS kazalo,
       o.zakonsko_kazalo AS zakonsko_kazalo,
       o.eurovoc AS eurovoc,
       o.propisi AS propisi,
       COALESCE((SELECT CASE WHEN t.komp = 0 THEN CAST(t.tijelo AS TEXT)
                             ELSE odzipaj(t.tijelo) END
                   FROM tekstovi t
                  WHERE t.rid = o.rid AND t.vrsta_zapisa = 'tekst'), '') AS tekst,
       COALESCE((SELECT CASE WHEN m.komp = 0 THEN CAST(m.tijelo AS TEXT)
                             ELSE odzipaj(m.tijelo) END
                   FROM tekstovi m
                  WHERE m.rid = o.rid AND m.vrsta_zapisa = 'meta'), '{}') AS meta_json,
       COALESCE((SELECT CASE WHEN z.komp = 0 THEN CAST(z.tijelo AS TEXT)
                             ELSE odzipaj(z.tijelo) END
                   FROM tekstovi z
                  WHERE z.rid = o.rid AND z.vrsta_zapisa = 'sazetak'), '') AS sazetak,
       o.duljina AS duljina,
       o.sha256 AS sha256,
       o.uzorak_kljuc AS uzorak_kljuc,
       o.nacin_odabira AS nacin_odabira,
       o.sud_id AS sud_id,
       o.upisnik_id AS upisnik_id,
       o.dohvaceno AS dohvaceno,
       o.gradivo AS gradivo,
       o.naslov AS naslov,
       o.autori AS autori,
       o.casopis AS casopis,
       o.citat AS citat,
       o.doi AS doi,
       o.licenca AS licenca,
       o.licenca_url AS licenca_url,
       o.redistribucija AS redistribucija
FROM odluke_meta o
"""

# `odluke` je javno lice pohrane: isti stupci koje je imala tablica iz sheme
# 1, plus novi, pa stari kod ne treba mijenjati. `rowid` je izlozen imenom
# jer se po njemu spaja na odluke_fts.
POGLEDI = {"v_odluke": POGLED_V_ODLUKE, "odluke": POGLED_ODLUKE}

# detail=full je zadano i namjerno: fraza je temeljna operacija ovog korpusa
# ("stjecanje bez osnove", doslovni citati clanaka), a detail=column je gubi.
# Bez prefix= opcije: 8,4 GB dodatnog diska kupovalo bi 0,2 ms po upitu.
#
# Jedan indeks za obje vrste gradiva. `naslov`, `autori` i `casopis` su prazni
# za odluke; prazan stupac u FTS5 stoji jedan bajt u docsize zapisu, dakle oko
# 3,5 MB na 1,17 M odluka. Zauzvrat su `autori:Gliha` i `casopis:"Zbornik"`
# jeftini stupcani filtri, a odluka i clanak o njoj dolaze iz istog bm25.
FTS_SHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS odluke_fts USING fts5(
    broj, sud, kazalo, naslov, autori, casopis, tekst,
    content='v_odluke', content_rowid='rid',
    tokenize='unicode61 remove_diacritics 2'
);
"""

# Redoslijed stupaca u odluke_fts; snippet() trazi indeks stupca. Mora se
# poklapati sa stupcima pogleda v_odluke, redom.
FTS_STUPCI = ("broj", "sud", "kazalo", "naslov", "autori", "casopis", "tekst")
FTS_TEKST = FTS_STUPCI.index("tekst")
_FTS_POPIS = ", ".join(FTS_STUPCI)
_FTS_UPITNICI = ",".join("?" * len(FTS_STUPCI))


# ------------------------------------------------------------ kompresija ---

def zipaj(s: str | None) -> tuple[int, int, bytes]:
    """Vraca (komp, n_bajt, blob) za tekst. Kratki tekstovi ostaju sirovi."""
    sirovo = (s or "").encode("utf-8")
    if len(sirovo) < KOMP_PRAG_B:
        return 0, len(sirovo), sirovo
    return KOMP_RAZINA, len(sirovo), zlib.compress(sirovo, KOMP_RAZINA)


def odzipaj(blob) -> str | None:
    """SQL funkcija: zlib BLOB -> tekst. Registrira se u veza()."""
    if blob is None:
        return None
    if isinstance(blob, str):
        return blob
    try:
        return zlib.decompress(blob).decode("utf-8")
    except zlib.error:
        # Zapis koji nije komprimiran (komp=0 s krivim stupcem, ili stara
        # datoteka): procitaj ga doslovno umjesto da srusi cijeli upit.
        return bytes(blob).decode("utf-8", "replace")


def _uzorak_kljuc(doc_id: str) -> int:
    """
    Determinististan kljuc za stratificirano uzorkovanje: prvih 8 bajtova
    sha256(id + sol), pomaknuto u pozitivan 63-bitni raspon koji SQLite
    sprema kao INTEGER. Isti ID uvijek daje isti kljuc, pa je uzorak
    ponovljiv i provjerljiv.
    """
    h = hashlib.sha256(doc_id.encode("utf-8") + UZORAK_SOL).digest()
    return int.from_bytes(h[:8], "big") >> 1


def _godina(datum: str | None) -> int | None:
    m = re.match(r"^(\d{4})", datum or "")
    return int(m.group(1)) if m else None


# ----------------------------------------------------------------- veza ---

def _postavi_pragme(con: sqlite3.Connection) -> None:
    for ime, vrijednost in PRAGME:
        try:
            con.execute(f"PRAGMA {ime} = {vrijednost}").fetchall()
        except sqlite3.DatabaseError:
            # WAL ne radi na svakom datotecnom sustavu; ostalo je savjet, ne uvjet.
            pass


def _verzija(con: sqlite3.Connection) -> int:
    return con.execute("PRAGMA user_version").fetchone()[0]


def _ima_objekt(con: sqlite3.Connection, ime: str, tip: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type=? AND name=?", (tip, ime)
    ).fetchone() is not None


def _stara_shema(con: sqlite3.Connection) -> bool:
    """Shema 1: `odluke` je TABLICA (u shemi 2 je pogled)."""
    return _ima_objekt(con, "odluke", "table")


def _sazmi(s: str) -> str:
    return " ".join((s or "").split())


def _uskladi_poglede(con: sqlite3.Connection) -> list[str]:
    """
    Pogled je kod, ne podatak. Ako se definicija u bazi razlikuje od one u
    ovom modulu, pogled se ponovno stvara. Time popravak upita (npr. prelazak
    s JOIN-a na skalarne podupite) stize u postojecu bazu bez migracije
    podataka i bez rucnog zahvata.
    """
    obnovljeni = []
    for ime, ddl in POGLEDI.items():
        red = con.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name=?",
                          (ime,)).fetchone()
        if red is not None and _sazmi(red[0]) == _sazmi(ddl):
            continue
        if red is not None:
            con.execute(f"DROP VIEW {ime}")
        con.execute(ddl)
        obnovljeni.append(ime)
    return obnovljeni


def _stupci(con: sqlite3.Connection, tablica: str) -> tuple[str, ...]:
    return tuple(r[1] for r in con.execute(f"PRAGMA table_info({tablica})"))


def _treba_shemu_3(con: sqlite3.Connection) -> bool:
    """Baza sheme 2: `odluke_meta` postoji, ali nema stupac `gradivo`."""
    return (_ima_objekt(con, "odluke_meta", "table")
            and "gradivo" not in _stupci(con, "odluke_meta"))


def _nadogradi_stupce(con: sqlite3.Connection) -> list[str]:
    """
    Dodaje stupce sheme 3 na `odluke_meta`. ALTER TABLE ADD COLUMN u SQLite-u
    ne prepisuje nijedan postojeci redak: nova vrijednost se cita iz sheme.
    Nadogradnja 2439 odluka je zato trenutna i ne moze izgubiti podatak.

    Mora se izvrsiti PRIJE `executescript(SHEMA)`, jer djelomicni indeksi u
    shemi spominju stupce kojih u shemi 2 jos nema.
    """
    if not _ima_objekt(con, "odluke_meta", "table"):
        return []                      # nova baza; CREATE TABLE ce ih donijeti
    ima = set(_stupci(con, "odluke_meta"))
    dodani = []
    for ime, tip in NOVI_STUPCI:
        if ime in ima:
            continue
        con.execute(f"ALTER TABLE odluke_meta ADD COLUMN {ime} {tip}")
        dodani.append(ime)
    return dodani


def _uskladi_fts(con: sqlite3.Connection, *, prisili_obnovu: bool = False,
                 tiho: bool = True) -> str:
    """
    FTS shema je kod, kao i pogledi. Ako se stupci indeksa razlikuju od
    FTS_STUPCI, ili se promijenio pogled iz kojeg indeks cita, indeks se
    ponovno gradi iz sadrzaja. Podaci su u `odluke_meta` i `tekstovi`, pa
    rusenje indeksa ne moze izgubiti nista osim vremena.

    Vraca 'nema' | 'stvoren' | 'obnovljen' | 'nepromijenjen'.
    """
    if not _ima_objekt(con, "odluke_fts", "table"):
        try:
            con.executescript(FTS_SHEMA)
        except sqlite3.OperationalError as e:      # SQLite bez FTS5
            print(f"  [!] FTS5 nedostupan ({e}); koristi se LIKE pretraga.")
            return "nema"
        stanje = "stvoren"
    elif prisili_obnovu or _stupci(con, "odluke_fts") != FTS_STUPCI:
        con.execute("DROP TABLE odluke_fts")
        con.executescript(FTS_SHEMA)
        stanje = "obnovljen"
    else:
        return "nepromijenjen"

    n = con.execute("SELECT COUNT(*) FROM odluke_meta").fetchone()[0]
    if n:
        if not tiho:
            print(f"  gradim FTS5 indeks nad {n} zapisa ...", flush=True)
        con.execute("INSERT INTO odluke_fts(odluke_fts) VALUES ('rebuild')")
        con.execute("INSERT INTO odluke_fts(odluke_fts) VALUES ('optimize')")
    con.commit()
    return stanje


def otvori_ro(path: pathlib.Path | str) -> sqlite3.Connection:
    """
    Korpus samo za citanje. Obavezno umjesto golog sqlite3.connect(): bez
    registrirane funkcije `odzipaj` pogled `odluke` ne moze dekomprimirati
    tekst i svaki upit nad njim pada.
    """
    con = sqlite3.connect(f"file:{pathlib.Path(path)}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.create_function("odzipaj", 1, odzipaj, deterministic=True)
    return con


def veza(path: pathlib.Path | str | None = None, *,
         auto_migracija: bool = True) -> sqlite3.Connection:
    """
    Otvara korpus. Stvara shemu ako je nema, i prevodi staru bazu na tekucu
    shemu ako na nju naidje (osim ako auto_migracija=False, tada digne
    gresku). Prepoznaje i shemu 1 (tablica `odluke`) i shemu 2 (bez stupca
    `gradivo`).
    """
    put = path or DB_PATH
    con = sqlite3.connect(put)
    con.row_factory = sqlite3.Row
    con.create_function("odzipaj", 1, odzipaj, deterministic=True)
    _postavi_pragme(con)

    if _stara_shema(con):
        if not auto_migracija:
            raise RuntimeError(
                f"Baza {put} je u shemi 1. Pokreni migraciju: "
                f"python store.py --migriraj --baza {put}")
        migriraj(con)
        return con

    if _treba_shemu_3(con):
        if not auto_migracija:
            raise RuntimeError(
                f"Baza {put} je u shemi 2 (bez gradiva). Pokreni migraciju: "
                f"python store.py --migriraj --baza {put}")
        if con.execute("SELECT COUNT(*) FROM odluke_meta").fetchone()[0]:
            # Nadogradnja je aditivna, ali korpus se skuplja tjednima i
            # kopija od nekoliko sekundi je jeftinija od jednog "ups".
            kop = _sigurnosna_kopija(con, "shema2")
            if kop:
                print(f"Sigurnosna kopija sheme 2: {kop}", flush=True)

    _nadogradi_stupce(con)            # prije sheme: indeksi trebaju te stupce
    con.executescript(SHEMA)
    obnovljeni = _uskladi_poglede(con)
    # Ako se promijenio pogled iz kojeg FTS cita sadrzaj, indeks je zastario
    # i mora se izgraditi iznova, inace bi snippet i brisanje radili nad
    # starim oblikom retka.
    _uskladi_fts(con, prisili_obnovu="v_odluke" in obnovljeni)
    if _verzija(con) < SHEMA_VERZIJA:
        con.execute(f"PRAGMA user_version = {SHEMA_VERZIJA}")
    con.commit()
    return con


# ------------------------------------------------------------- sifarnici ---

def _sifra(con: sqlite3.Connection, tablica: str, stupac: str, kljuc: str,
           vrijednost: str | None, kes: dict | None = None) -> int | None:
    """ID iz sifarnika, uz upis ako vrijednosti jos nema. None za praznu."""
    if not vrijednost:
        return None
    if kes is not None and vrijednost in kes:
        return kes[vrijednost]
    red = con.execute(f"SELECT {kljuc} FROM {tablica} WHERE {stupac}=?",
                      (vrijednost,)).fetchone()
    if red is None:
        cur = con.execute(f"INSERT INTO {tablica} ({stupac}) VALUES (?)",
                          (vrijednost,))
        sid = cur.lastrowid
    else:
        sid = red[0]
    if kes is not None:
        kes[vrijednost] = sid
    return sid


def sud_id(con, naziv, kes=None):
    return _sifra(con, "sudovi", "naziv", "sud_id", naziv, kes)


def upisnik_id(con, oznaka, kes=None):
    return _sifra(con, "upisnici", "oznaka", "upisnik_id", oznaka, kes)


# ----------------------------------------------------------------- upis ---

def ima(con: sqlite3.Connection, doc_id: str) -> bool:
    return con.execute("SELECT 1 FROM odluke_meta WHERE id=?",
                       (doc_id,)).fetchone() is not None


def _upisi_tijelo(con, rid: int, vrsta_zapisa: str, sadrzaj: str | None) -> None:
    komp, n, blob = zipaj(sadrzaj)
    con.execute(
        "INSERT INTO tekstovi (rid, vrsta_zapisa, komp, n_bajt, tijelo) "
        "VALUES (?,?,?,?,?) ON CONFLICT(rid, vrsta_zapisa) DO UPDATE SET "
        "komp=excluded.komp, n_bajt=excluded.n_bajt, tijelo=excluded.tijelo",
        (rid, vrsta_zapisa, komp, n, blob))


def _procitaj_tijelo(con, rid: int, vrsta_zapisa: str) -> str | None:
    r = con.execute(
        "SELECT CASE WHEN komp = 0 THEN CAST(tijelo AS TEXT) "
        "            ELSE odzipaj(tijelo) END "
        "  FROM tekstovi WHERE rid=? AND vrsta_zapisa=?",
        (rid, vrsta_zapisa)).fetchone()
    return r[0] if r else None


def _fts_red(con, rid: int) -> sqlite3.Row | None:
    """Redak onako kako ga vidi FTS indeks (stupci FTS_STUPCI, tim redom)."""
    return con.execute(f"SELECT {_FTS_POPIS} FROM v_odluke WHERE rid=?",
                       (rid,)).fetchone()


def _fts_dodaj(con, rid: int, red: sqlite3.Row | None = None) -> None:
    r = _fts_red(con, rid) if red is None else red
    if r is None:
        return
    con.execute(
        f"INSERT INTO odluke_fts (rowid, {_FTS_POPIS}) "
        f"VALUES (?,{_FTS_UPITNICI})", (rid, *tuple(r)))


def _fts_makni(con, rid: int, stari: sqlite3.Row | None) -> None:
    """FTS s vanjskim sadrzajem trazi STARE vrijednosti pri brisanju."""
    if stari is None:
        return
    con.execute(
        f"INSERT INTO odluke_fts (odluke_fts, rowid, {_FTS_POPIS}) "
        f"VALUES ('delete', ?,{_FTS_UPITNICI})", (rid, *tuple(stari)))


def _spoji(v) -> str | None:
    """Popis autora ili kljucnih rijeci -> jedan niz. Prazno ostaje None."""
    if v is None:
        return None
    if isinstance(v, (list, tuple, set)):
        v = "; ".join(str(x).strip() for x in v if str(x).strip())
    v = str(v).strip()
    return v or None


def _provjeri_doktrinu(rec: dict) -> None:
    """
    Doktrina bez URL-a izvora i bez licence ne ulazi u korpus.

    Nije formalnost. Hrcak je otvoreni pristup, ali licenca se razlikuje po
    casopisu pa i po pojedinom clanku, a bez zabiljezene licence nema nacina
    da se kasnije zna smije li se zapis dijeliti. Zapis kojem je licenca
    "sva prava pridrzana" je uredan zapis; zapis bez ijedne licence nije.
    """
    if not (rec.get("url") or "").strip():
        raise ValueError(
            f"doktrina bez url-a izvora: {rec.get('id')!r}. Svaki zapis "
            f"doktrine mora nositi URL s kojeg je preuzet.")
    if not (rec.get("licenca") or "").strip():
        raise ValueError(
            f"doktrina bez licence: {rec.get('id')!r}. Upisi licencu doslovno "
            f"kako stoji na izvoru (i 'sva prava pridrzana' je valjan upis).")


def _polja_doktrine(rec: dict) -> dict:
    """Polja doktrine iz zapisa, normalizirana. Vrijednosti None se ne diraju."""
    p = {ime: rec.get(ime) for ime in _DOKTRINA_POLJA}
    p["autori"] = _spoji(rec.get("autori"))
    if rec.get("licenca"):
        p["redistribucija"] = (rec.get("redistribucija")
                               or procijeni_redistribuciju(rec["licenca"]))
    for k, v in list(p.items()):
        if isinstance(v, str):
            p[k] = v.strip() or None
    return p


def _indeksni_tekst(tekst: str, sazetak: str) -> str:
    """
    Ono sto zapravo ulazi u FTS i iz cega se racuna sha256 i duljina.

    Isti izraz kao u pogledu v_odluke: tijelo, pa sazetak iza njega. Za
    odluku (koja nikad nema sazetak) to je doslovno tekst, pa se sha256
    postojecih 2439 odluka nadogradnjom sheme ne mijenja.
    """
    return tekst + (("\n" + sazetak) if sazetak else "")


def spremi(con: sqlite3.Connection, rec: dict, *, commit: bool = True,
           kes: dict | None = None) -> bool:
    """
    Upsert jednog zapisa, odluke ili doktrine. Vraca True ako je nov.

    Vrstu odreduje rec['gradivo'] ('odluka' zadano, 'doktrina' za clanke).
    Za doktrinu su `url` i `licenca` obavezni; bez njih se digne ValueError.

    Kao i u shemi 1, ponovno spremanje osvjezava sadrzajna polja (tekst,
    sazetak, kazalo, propise, meta i polja doktrine), a izvorne
    identifikacijske metapodatke (broj, sud, datum, vrsta, upisnik, ECLI,
    pravomocnost) ostavlja na miru.
    """
    kes = kes if kes is not None else {}
    doc_id = rec["id"]
    gradivo = rec.get("gradivo") or "odluka"
    if gradivo not in VRSTE_GRADIVA:
        raise ValueError(f"nepoznata vrsta gradiva {gradivo!r}; "
                         f"dopusteno: {', '.join(VRSTE_GRADIVA)}")
    if gradivo == "doktrina":
        _provjeri_doktrinu(rec)

    tekst = rec.get("tekst") or ""
    meta = json.dumps(rec.get("meta") or {}, ensure_ascii=False)
    ima_sazetak = "sazetak" in rec

    stari = con.execute(
        "SELECT rid, sha256, kazalo, broj, sud_id, gradivo FROM odluke_meta "
        "WHERE id=?", (doc_id,)).fetchone()
    if "fts" not in kes:
        kes["fts"] = _ima_objekt(con, "odluke_fts", "table")
    fts_ziv = kes["fts"]

    if stari is None:
        sazetak = (rec.get("sazetak") or "") if ima_sazetak else ""
        indeksno = _indeksni_tekst(tekst, sazetak)
        sha = hashlib.sha256(indeksno.encode("utf-8")).digest()
        stupci = ["id", "izvor", "url", "broj", "sud_id", "upisnik_id", "datum",
                  "godina", "vrsta", "ecli", "pravomocnost", "kazalo",
                  "zakonsko_kazalo", "eurovoc", "propisi", "duljina", "sha256",
                  "uzorak_kljuc", "nacin_odabira", "gradivo"]
        vrijednosti = [
            doc_id,
            rec.get("izvor") or "anon",
            rec.get("url"),
            rec.get("broj"),
            sud_id(con, rec.get("sud"), kes.setdefault("sud", {})),
            upisnik_id(con, rec.get("upisnik"), kes.setdefault("upisnik", {})),
            rec.get("datum"),
            rec.get("godina") if rec.get("godina") is not None
            else _godina(rec.get("datum")),
            rec.get("vrsta"),
            rec.get("ecli"),
            rec.get("pravomocnost"),
            rec.get("kazalo"),
            rec.get("zakonsko_kazalo"),
            rec.get("eurovoc"),
            rec.get("propisi"),
            len(indeksno),
            sha,
            _uzorak_kljuc(doc_id),
            rec.get("nacin_odabira") or "ciljano",
            gradivo,
        ]
        # Za odluku se stupci doktrine ne navode uopce: ostaju zavrsni NULL-ovi
        # koje SQLite u zapis ni ne upisuje.
        if gradivo == "doktrina":
            p = _polja_doktrine(rec)
            stupci += list(_DOKTRINA_POLJA)
            vrijednosti += [p[ime] for ime in _DOKTRINA_POLJA]
        cur = con.execute(
            "INSERT INTO odluke_meta (%s) VALUES (%s)"
            % (", ".join(stupci), ",".join("?" * len(stupci))), vrijednosti)
        rid = cur.lastrowid
        _upisi_tijelo(con, rid, "tekst", tekst)
        if sazetak:
            _upisi_tijelo(con, rid, "sazetak", sazetak)
        if rec.get("meta"):
            _upisi_tijelo(con, rid, "meta", meta)
        if fts_ziv:
            _fts_dodaj(con, rid)
        if commit:
            con.commit()
        return True

    rid = stari["rid"]
    if ima_sazetak:
        sazetak = rec.get("sazetak") or ""
    else:
        sazetak = _procitaj_tijelo(con, rid, "sazetak") or ""
    indeksno = _indeksni_tekst(tekst, sazetak)
    sha = hashlib.sha256(indeksno.encode("utf-8")).digest()

    prije = _fts_red(con, rid) if fts_ziv else None
    promjena = (bytes(stari["sha256"] or b"") != sha
                or (stari["kazalo"] or "") != (rec.get("kazalo") or ""))

    con.execute(
        """UPDATE odluke_meta SET
               kazalo = ?, zakonsko_kazalo = COALESCE(?, zakonsko_kazalo),
               eurovoc = COALESCE(?, eurovoc), propisi = ?,
               duljina = ?, sha256 = ?, gradivo = ?
           WHERE rid = ?""",
        (rec.get("kazalo"), rec.get("zakonsko_kazalo"), rec.get("eurovoc"),
         rec.get("propisi"), len(indeksno), sha,
         gradivo if gradivo != "odluka" else stari["gradivo"], rid))

    if gradivo == "doktrina":
        p = _polja_doktrine(rec)
        # COALESCE: djelomicna dopuna (npr. naknadno nadeni DOI) ne brise
        # ono sto je vec zapisano.
        con.execute(
            "UPDATE odluke_meta SET "
            + ", ".join(f"{ime} = COALESCE(?, {ime})" for ime in _DOKTRINA_POLJA)
            + " WHERE rid = ?",
            [p[ime] for ime in _DOKTRINA_POLJA] + [rid])
        novo = _fts_red(con, rid) if fts_ziv else None
        if prije is not None and novo is not None and tuple(prije) != tuple(novo):
            promjena = True

    _upisi_tijelo(con, rid, "tekst", tekst)
    if ima_sazetak:
        if sazetak:
            _upisi_tijelo(con, rid, "sazetak", sazetak)
        else:
            con.execute("DELETE FROM tekstovi WHERE rid=? AND vrsta_zapisa='sazetak'",
                        (rid,))
    if rec.get("meta"):
        _upisi_tijelo(con, rid, "meta", meta)
    if fts_ziv and promjena:
        _fts_makni(con, rid, prije)
        _fts_dodaj(con, rid)
    if commit:
        con.commit()
    return False


def spremi_mnogo(con: sqlite3.Connection, zapisi) -> dict:
    """
    Batch upis: jedna transakcija, jedan commit, dijeljeni kes sifarnika.
    Mjereno 511 odluka/s uz batch 1000 i synchronous=NORMAL u WAL nacinu.
    """
    kes: dict = {}
    zbroj = {"novo": 0, "azurirano": 0}
    for rec in zapisi:
        if spremi(con, rec, commit=False, kes=kes):
            zbroj["novo"] += 1
        else:
            zbroj["azurirano"] += 1
    con.commit()
    return zbroj


def zabiljezi_pretragu(con: sqlite3.Connection, upit: str, izvor: str,
                       stranica: int, pogodaka: int) -> None:
    con.execute("INSERT OR REPLACE INTO pretrage (upit, izvor, stranica, pogodaka) "
                "VALUES (?,?,?,?)", (upit, izvor, stranica, pogodaka))
    con.commit()


# -------------------------------------------------------------- citanje ---

def _bez_dijakritika(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def trazi(con: sqlite3.Connection, upit: str, limit: int = 50,
          vrsta: str | None = None) -> list[sqlite3.Row]:
    """
    Full-text pretraga lokalnog korpusa (FTS5, s fallbackom na LIKE).

    `vrsta` je neobavezna: None trazi po cijelom korpusu, 'odluka' samo po
    sudskim odlukama, 'doktrina' samo po clancima. Filtar ide preko stupca
    `odluke_meta.gradivo`, a NE preko MATCH-a: da je vrsta indeksirana kao
    tekst, upit za rijec "doktrina" u obrazlozenju presude povukao bi sa
    sobom i filtar. Ovako je poredak (bm25) i dalje jedan i usporediv medu
    vrstama, a filtriranje je obican uvjet nad spojenim retkom.

    Nepoznata vrsta digne ValueError umjesto da tiho vrati prazan popis.
    """
    if vrsta is not None and vrsta not in VRSTE_GRADIVA:
        raise ValueError(f"nepoznata vrsta gradiva {vrsta!r}; "
                         f"dopusteno: {', '.join(VRSTE_GRADIVA)} ili None")
    uvjet = " AND o.gradivo = ?" if vrsta else ""
    par = (upit, vrsta, limit) if vrsta else (upit, limit)
    try:
        return con.execute(
            f"""SELECT o.*, snippet(odluke_fts, {FTS_TEKST}, '»', '«', ' … ', 24) AS isjecak,
                       bm25(odluke_fts) AS rang
                FROM odluke_fts JOIN odluke o ON o.rowid = odluke_fts.rowid
                WHERE odluke_fts MATCH ?{uvjet}
                ORDER BY rang LIMIT ?""", par).fetchall()
    except sqlite3.OperationalError:
        pojam = f"%{_bez_dijakritika(re.sub(chr(34), '', upit))}%"
        par = (pojam, vrsta, limit) if vrsta else (pojam, limit)
        return con.execute(
            "SELECT *, substr(tekst,1,300) AS isjecak, 0 AS rang FROM odluke o "
            f"WHERE tekst LIKE ?{uvjet} LIMIT ?", par).fetchall()
    except sqlite3.DatabaseError as e:
        # Baza otvorena samo za citanje (otvori_ro) ne moze se nadograditi, pa
        # stara cetverostupcana odluke_fts na snippet() sedmog stupca puca s
        # "column index out of range". Poruka mora reci sto uciniti.
        if (_ima_objekt(con, "odluke_fts", "table")
                and _stupci(con, "odluke_fts") != FTS_STUPCI):
            raise RuntimeError(
                "FTS indeks je u staroj shemi (stupci "
                f"{_stupci(con, 'odluke_fts')}, ocekivano {FTS_STUPCI}). "
                "Otvori bazu jednom za pisanje, store.veza(put), da se "
                "nadogradi, pa ponovi pretragu.") from e
        raise


def dohvati(con: sqlite3.Connection, doc_id: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM odluke WHERE id=?", (doc_id,)).fetchone()


def tekst(con: sqlite3.Connection, doc_id: str) -> str | None:
    """Samo tekst jedne odluke, bez povlacenja ostatka retka."""
    r = con.execute(
        """SELECT CASE WHEN t.komp = 0 THEN CAST(t.tijelo AS TEXT)
                       ELSE odzipaj(t.tijelo) END
             FROM odluke_meta o JOIN tekstovi t
               ON t.rid = o.rid AND t.vrsta_zapisa = 'tekst'
            WHERE o.id = ?""", (doc_id,)).fetchone()
    return r[0] if r else None


def sazetak(con: sqlite3.Connection, doc_id: str) -> str | None:
    """Sazetak clanka, ako postoji. Za odluke uvijek None."""
    r = con.execute(
        """SELECT CASE WHEN t.komp = 0 THEN CAST(t.tijelo AS TEXT)
                       ELSE odzipaj(t.tijelo) END
             FROM odluke_meta o JOIN tekstovi t
               ON t.rid = o.rid AND t.vrsta_zapisa = 'sazetak'
            WHERE o.id = ?""", (doc_id,)).fetchone()
    return r[0] if r else None


def spremi_doktrinu(con: sqlite3.Connection, rec: dict, **kw) -> bool:
    """`spremi()` uz gradivo='doktrina'. Sve ostalo je isto."""
    return spremi(con, dict(rec, gradivo="doktrina"), **kw)


def slobodni_za_dijeljenje(con: sqlite3.Connection,
                           limit: int | None = None) -> list[sqlite3.Row]:
    """
    Zapisi doktrine koje je dopusteno dalje dijeliti bez daljnje provjere,
    dakle samo redistribucija='slobodna'. Sve ostalo, ukljucujuci 'uvjetna'
    i neprepoznatu licencu, ostaje lokalno.
    """
    sql = ("SELECT id, url, naslov, autori, casopis, citat, godina, doi, licenca "
           "FROM odluke_meta WHERE gradivo='doktrina' "
           "AND redistribucija='slobodna' ORDER BY casopis, godina")
    if limit:
        return con.execute(sql + " LIMIT ?", (limit,)).fetchall()
    return con.execute(sql).fetchall()


# ------------------------------------------------- stratificirani uzorak ---

def osvjezi_slojeve(con: sqlite3.Connection) -> int:
    """Prepucava tablicu `slojevi` iz stvarnog stanja. Vraca broj slojeva."""
    con.execute("DELETE FROM slojevi")
    con.execute(
        """INSERT INTO slojevi (sud_id, upisnik_id, godina, n)
           SELECT COALESCE(sud_id, -1), COALESCE(upisnik_id, -1),
                  COALESCE(godina, -1), COUNT(*)
             FROM odluke_meta
            GROUP BY 1, 2, 3""")
    con.commit()
    return con.execute("SELECT COUNT(*) FROM slojevi").fetchone()[0]


def uzorak_sloja(con: sqlite3.Connection, *, sud: int | None = None,
                 godina: int | None = None, upisnik: int | None = None,
                 n: int = 50, od_kljuca: int = 0) -> list[sqlite3.Row]:
    """
    Determinististan uzorak jednog sloja, O(n) po indeksu ix_strat_sud.

    Poredak po uzorak_kljuc je stalan, pa povecanje n samo dodaje odluke, a
    prethodno odabrane ostaju u uzorku. Uzorak se zato moze graditi u ratama
    i svaka rata je valjan uzorak sama za sebe.
    """
    uvjeti = ["uzorak_kljuc > ?"]
    param: list = [od_kljuca]
    if sud is not None:
        uvjeti.append("sud_id = ?")
        param.append(sud)
    if godina is not None:
        uvjeti.append("godina = ?")
        param.append(godina)
    if upisnik is not None:
        uvjeti.append("upisnik_id = ?")
        param.append(upisnik)
    param.append(n)
    return con.execute(
        "SELECT rid, id, uzorak_kljuc FROM odluke_meta WHERE "
        + " AND ".join(uvjeti) + " ORDER BY uzorak_kljuc LIMIT ?", param
    ).fetchall()


# ---------------------------------------------------------- odrzavanje ---

def optimiziraj(con: sqlite3.Connection, *, vacuum: bool = False) -> None:
    """
    Nakon svake vece serije upisa. Mjereno: `optimize` svodi inkrementalno
    gradeni FTS s 36,13 na 20,87 MB za 0,8 s, dakle 42 % velicine indeksa.
    To nije kozmetika. VACUUM je zaseban jer zakljucava bazu na minute.
    """
    try:
        con.execute("INSERT INTO odluke_fts(odluke_fts) VALUES ('optimize')")
        con.commit()
    except sqlite3.OperationalError:
        pass
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    con.execute("ANALYZE")
    con.commit()
    if vacuum:
        con.execute("VACUUM")


def statistika(con: sqlite3.Connection) -> dict:
    r = {}
    r["ukupno"] = con.execute("SELECT COUNT(*) FROM odluke_meta").fetchone()[0]
    r["po_izvoru"] = dict(con.execute(
        "SELECT izvor, COUNT(*) FROM odluke_meta GROUP BY izvor").fetchall())
    # Samo odluke: clanak nema sud, pa bi se sva doktrina slila u jedan red '?'
    # i lazno se popela medu najzastupljenije "sudove".
    r["po_sudu"] = dict(con.execute(
        """SELECT COALESCE(s.naziv,'?'), COUNT(*) c
             FROM odluke_meta o LEFT JOIN sudovi s ON s.sud_id = o.sud_id
            WHERE o.gradivo = 'odluka'
            GROUP BY 1 ORDER BY c DESC LIMIT 15""").fetchall())
    r["raspon"] = con.execute(
        "SELECT MIN(datum), MAX(datum) FROM odluke_meta "
        "WHERE datum IS NOT NULL AND datum<>''").fetchone()
    r["po_nacinu"] = dict(con.execute(
        "SELECT nacin_odabira, COUNT(*) FROM odluke_meta GROUP BY 1").fetchall())
    r["po_gradivu"] = dict(con.execute(
        "SELECT gradivo, COUNT(*) FROM odluke_meta GROUP BY 1").fetchall())
    r["po_licenci"] = dict(con.execute(
        "SELECT COALESCE(redistribucija,'?'), COUNT(*) FROM odluke_meta "
        "WHERE gradivo='doktrina' GROUP BY 1").fetchall())
    r["po_casopisu"] = dict(con.execute(
        "SELECT COALESCE(casopis,'?'), COUNT(*) c FROM odluke_meta "
        "WHERE gradivo='doktrina' GROUP BY 1 ORDER BY c DESC LIMIT 15").fetchall())
    sirovo, komprimirano = con.execute(
        "SELECT COALESCE(SUM(n_bajt),0), COALESCE(SUM(length(tijelo)),0) "
        "FROM tekstovi WHERE vrsta_zapisa='tekst'").fetchone()
    r["bajtova_sirovo"] = sirovo
    r["bajtova_na_disku"] = komprimirano
    r["omjer"] = (komprimirano / sirovo) if sirovo else None
    return r


# ------------------------------------------------------------ migracija ---

# Stupci sheme 1 koji se preslikavaju 1:1. `zakonsko_kazalo` i `eurovoc`
# postoje samo u bazama koje su naknadno dopunjene, pa se provjeravaju.
_V1_OBAVEZNO = ("id", "izvor", "url", "broj", "sud", "datum", "vrsta",
                "upisnik", "ecli", "pravomocnost", "kazalo", "propisi",
                "tekst", "meta_json", "dohvaceno")


def _sigurnosna_kopija(con: sqlite3.Connection,
                       oznaka: str = "shema1") -> pathlib.Path | None:
    """
    Kopija datoteke baze prije migracije, kroz SQLite backup API (dakle
    dosljedna i kad netko drugi cita). Vraca putanju ili None za bazu koja
    nije na disku. Postojeca kopija se ne prepisuje: prva je najvrjednija.
    """
    for _, ime, put in con.execute("PRAGMA database_list").fetchall():
        if ime == "main" and put:
            cilj = pathlib.Path(put).with_suffix(
                pathlib.Path(put).suffix + f".{oznaka}.bak")
            if cilj.exists():
                return cilj
            rez = sqlite3.connect(cilj)
            with rez:
                con.backup(rez)
            rez.close()
            return cilj
    return None


def migriraj(con: sqlite3.Connection, *, tiho: bool = False,
             batch: int = 1000, kopija: bool = True) -> int:
    """
    Prevodi bazu sa sheme 1 na shemu 2 bez gubitka. Idempotentno: nad vec
    migriranom bazom ne radi nista. Vraca broj prenesenih odluka.

    Postupak: napravi se sigurnosna kopija datoteke, stara tablica se
    preimenuje, nova shema se stvori, podaci se prenesu u batchevima (tekst
    i meta_json odlaze komprimirani), prenos se provjeri usporedbom s jos
    uvijek postojecom starom tablicom, tek onda se ona brise, FTS se izgradi
    iz nule i optimizira, baza se stisne.

    Ako provjera padne, digne se iznimka, a stara tablica ostaje netaknuta
    pod imenom `odluke_v1`.
    """
    if not _stara_shema(con):
        return 0

    def kaz(msg):
        if not tiho:
            print(msg, flush=True)

    if kopija:
        put = _sigurnosna_kopija(con)
        if put:
            kaz(f"Sigurnosna kopija sheme 1: {put}")

    stupci = {r[1] for r in con.execute("PRAGMA table_info(odluke)")}
    nedostaje = set(_V1_OBAVEZNO) - stupci
    if nedostaje:
        raise RuntimeError(f"Tablica `odluke` nije shema 1; nedostaju: {nedostaje}")
    ima_zk = "zakonsko_kazalo" in stupci
    ima_ev = "eurovoc" in stupci

    ukupno = con.execute("SELECT COUNT(*) FROM odluke").fetchone()[0]
    kaz(f"Migracija sheme 1 -> 2: {ukupno} odluka.")

    con.execute("PRAGMA foreign_keys = OFF").fetchall()
    con.commit()

    # 1. maknuti staru FTS masineriju (trigeri i indeks nad starom tablicom)
    for t in ("odluke_ai", "odluke_ad", "odluke_au"):
        con.execute(f"DROP TRIGGER IF EXISTS {t}")
    con.execute("DROP TABLE IF EXISTS odluke_fts")
    for i in ("ix_odluke_sud", "ix_odluke_datum", "ix_odluke_izvor"):
        con.execute(f"DROP INDEX IF EXISTS {i}")
    con.execute("ALTER TABLE odluke RENAME TO odluke_v1")
    con.commit()

    # 2. nova shema
    con.executescript(SHEMA)
    _uskladi_poglede(con)
    try:
        con.executescript(FTS_SHEMA)
    except sqlite3.OperationalError as e:
        kaz(f"  [!] FTS5 nedostupan ({e}); indeks se ne gradi.")
    con.commit()

    # 3. prijenos; rowid se cuva, pa vanjske reference na redni broj ostaju
    kes: dict = {"sud": {}, "upisnik": {}}
    preneseno = 0
    upit = ("SELECT rowid AS rowid, * FROM odluke_v1 ORDER BY rowid")
    for red in con.execute(upit).fetchall():
        rid = red["rowid"]
        tekst_v1 = red["tekst"] or ""
        con.execute(
            """INSERT INTO odluke_meta
               (rid, id, izvor, url, broj, sud_id, upisnik_id, datum, godina,
                vrsta, ecli, pravomocnost, kazalo, zakonsko_kazalo, eurovoc,
                propisi, duljina, sha256, uzorak_kljuc, nacin_odabira, dohvaceno)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, red["id"], red["izvor"] or "anon", red["url"], red["broj"],
             sud_id(con, red["sud"], kes["sud"]),
             upisnik_id(con, red["upisnik"], kes["upisnik"]),
             red["datum"], _godina(red["datum"]), red["vrsta"], red["ecli"],
             red["pravomocnost"], red["kazalo"],
             red["zakonsko_kazalo"] if ima_zk else None,
             red["eurovoc"] if ima_ev else None,
             red["propisi"], len(tekst_v1),
             hashlib.sha256(tekst_v1.encode("utf-8")).digest(),
             _uzorak_kljuc(red["id"]),
             # Postojeci korpus je prikupljen ciljano oko sumarske teme.
             "ciljano",
             red["dohvaceno"]))
        _upisi_tijelo(con, rid, "tekst", tekst_v1)
        mj = red["meta_json"]
        if mj and mj not in ("{}", "null"):
            _upisi_tijelo(con, rid, "meta", mj)
        preneseno += 1
        if preneseno % batch == 0:
            con.commit()
            kaz(f"  preneseno {preneseno}/{ukupno}")
    con.commit()
    kaz(f"  preneseno {preneseno}/{ukupno}")

    # 4. provjera prije brisanja izvora: nijedan redak ne smije nedostajati
    novo = con.execute("SELECT COUNT(*) FROM odluke_meta").fetchone()[0]
    n_tekst = con.execute(
        "SELECT COUNT(*) FROM tekstovi WHERE vrsta_zapisa='tekst'").fetchone()[0]
    if novo != ukupno or n_tekst != ukupno:
        raise RuntimeError(
            f"Migracija bi izgubila podatke: {ukupno} u izvoru, {novo} "
            f"metapodataka, {n_tekst} tekstova. Stara tablica `odluke_v1` "
            f"je netaknuta, nista nije obrisano.")
    razlika = con.execute(
        """SELECT COUNT(*) FROM odluke_v1 v JOIN odluke o ON o.id = v.id
            WHERE COALESCE(o.tekst,'') <> COALESCE(v.tekst,'')""").fetchone()[0]
    if razlika:
        raise RuntimeError(
            f"Tekst se ne poklapa nakon kompresije za {razlika} odluka. "
            f"Stara tablica `odluke_v1` je netaknuta.")
    kaz(f"  provjera: {novo} redaka, tekst identican nakon zlib kruga.")

    # 5. FTS iz nule, pa optimize (razlika je 40 % velicine indeksa)
    if _ima_objekt(con, "odluke_fts", "table"):
        kaz("  gradim FTS5 indeks ...")
        con.execute("INSERT INTO odluke_fts(odluke_fts) VALUES ('rebuild')")
        con.execute("INSERT INTO odluke_fts(odluke_fts) VALUES ('optimize')")
        con.commit()

    con.execute("DROP TABLE odluke_v1")
    con.execute(f"PRAGMA user_version = {SHEMA_VERZIJA}")
    con.commit()
    con.execute("PRAGMA foreign_keys = ON").fetchall()

    slojeva = osvjezi_slojeve(con)
    con.execute("VACUUM")
    con.commit()
    kaz(f"  slojeva (sud x upisnik x godina): {slojeva}")
    kaz("Migracija gotova.")
    return preneseno


# ------------------------------------------------------------------ CLI ---

def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Korpus: stanje i migracija.")
    p.add_argument("--baza", type=pathlib.Path, default=DB_PATH)
    p.add_argument("--migriraj", action="store_true",
                   help="prevedi bazu na tekucu shemu (1 -> 2 -> 3)")
    p.add_argument("--optimiziraj", action="store_true",
                   help="FTS optimize + checkpoint + ANALYZE")
    p.add_argument("--vacuum", action="store_true", help="uz --optimiziraj")
    a = p.parse_args()

    if a.migriraj and not a.baza.exists():
        sys.exit(f"Baza ne postoji: {a.baza}")

    con = veza(a.baza)
    if a.optimiziraj:
        optimiziraj(con, vacuum=a.vacuum)

    s = statistika(con)
    print(f"Baza: {a.baza}  (shema {_verzija(con)})")
    print(f"Ukupno zapisa: {s['ukupno']}")
    print(f"Po vrsti gradiva: {s['po_gradivu']}")
    print(f"Po izvoru: {s['po_izvoru']}")
    print(f"Po nacinu odabira: {s['po_nacinu']}")
    if s["ukupno"]:
        print(f"Raspon datuma: {s['raspon'][0]} … {s['raspon'][1]}")
        if s["omjer"]:
            print(f"Tekst: {s['bajtova_sirovo']/1e6:.1f} MB sirovo -> "
                  f"{s['bajtova_na_disku']/1e6:.1f} MB na disku "
                  f"(omjer {s['omjer']:.4f})")
        print("Najzastupljeniji sudovi:")
        for sud, c in s["po_sudu"].items():
            print(f"  {c:6d}  {sud}")
    if s["po_gradivu"].get("doktrina"):
        print(f"Doktrina po pravu dijeljenja: {s['po_licenci']}")
        print("Najzastupljeniji casopisi:")
        for cas, c in s["po_casopisu"].items():
            print(f"  {c:6d}  {cas}")
    con.close()


if __name__ == "__main__":
    main()
