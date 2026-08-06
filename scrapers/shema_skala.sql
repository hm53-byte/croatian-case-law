-- =====================================================================
-- Shema korpusa za mjerilo od ~1.2 milijuna odluka (ANON + usud + NN).
-- Sve odluke u ovoj shemi potkrijepljene su mjerenjima nad postojecih
-- 2439 odluka; brojke su u komentarima uz svaki dio.
--
-- Projekcija na 1.173.225 odluka: ~20 GB (zlib-6 + FTS5 detail=full),
-- naspram ~35 GB bez kompresije.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 0. PRAGMA postavke
-- page_size 4096 je izmjereno najbolji izbor: 8k/16k/32k daju vecu
-- datoteku (17.0 / 18.3 / 18.7 / 17.7 MB za istu kolicinu teksta)
-- uz zanemarivu razliku u brzini citanja (0.032 vs 0.026 ms/dok).
-- ---------------------------------------------------------------------
PRAGMA page_size = 4096;          -- postaviti PRIJE prvog upisa
PRAGMA journal_mode = WAL;        -- citanje ne blokira upis tijekom crawla
PRAGMA synchronous = NORMAL;      -- OFF donosi samo ~2% (511 -> 520 odl/s)
PRAGMA temp_store = MEMORY;
PRAGMA cache_size = -262144;      -- 256 MB stranicnog cachea
PRAGMA foreign_keys = ON;
PRAGMA wal_autocheckpoint = 4000; -- ~16 MB WAL-a tijekom masovnog upisa

-- ---------------------------------------------------------------------
-- 1. SIFARNICI
-- 68 razlicitih sudova, 60 upisnika na 2439 odluka. Normalizacija stedi
-- ~70 B/dok, sto je ~0.08 GB na punom korpusu; vaznije je da omogucuje
-- brz i tocan GROUP BY pri stratificiranom uzorkovanju.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sudovi (
    sud_id   INTEGER PRIMARY KEY,
    naziv    TEXT NOT NULL UNIQUE,
    razina   TEXT,        -- 'opcinski' | 'zupanijski' | 'visoki' | 'vrhovni' | ...
    vrsta    TEXT         -- 'gradanski' | 'trgovacki' | 'upravni' | 'prekrsajni'
);

-- upisnik_id je portalov vlastiti id iz obrasca pretrage (parametar
-- vu=oznaka;id). Oznaka NIJE jedinstvena: obrazac nudi 400 upisnika, a 49
-- oznaka se ponavlja izmedu vrsta sudova (mjereno nad spremljenom stranicom
-- pretrage; npr. 'Ovr' postoji kao gradanski i kao trgovacki upisnik).
-- Zato je jedinstven samo id, a oznaka ima obican indeks.
CREATE TABLE IF NOT EXISTS upisnici (
    upisnik_id INTEGER PRIMARY KEY,
    oznaka     TEXT NOT NULL,          -- 'P', 'Rev', 'Gz', ...
    naziv      TEXT
);
CREATE INDEX IF NOT EXISTS ix_upisnici_oznaka ON upisnici(oznaka);

-- ---------------------------------------------------------------------
-- 2. METAPODACI
-- Namjerno BEZ teksta i BEZ meta_json-a.
--
-- Mjerenje: ista 2439 odluka u jednoj tablici s tekstom zauzimaju
-- 50.8 MB; sama metatablica zauzima 3.55 MB. Razdvajanje smanjuje
-- povrsinu punog skeniranja 14x, sto je presudno za fasetiranje i
-- stratificirano uzorkovanje po sudu/upisniku/godini nad 1.17M redaka.
--
-- meta_json je izmjereno 795 B/dok i 100% redundantan: svaki njegov
-- kljuc (Broj odluke, Sud, Datum, Pravomocnost, Upisnik, Vrsta,
-- Zakonsko kazalo, Stvarno kazalo, EuroVoc, ECLI, Prethodne/Naknadne
-- odluke) vec ima svoj stupac. Izbacivanjem se stedi 0.93 GB.
-- Sirovi odgovor portala, ako se zeli cuvati, ide komprimiran u
-- tablicu 'tekstovi' kao zaseban zapis vrste 'meta'.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS odluke (
    rid           INTEGER PRIMARY KEY,   -- gusti kljuc; spona na FTS i tekstove
    id            TEXT NOT NULL UNIQUE,  -- UUID izvora (36 znakova)
    izvor         TEXT NOT NULL DEFAULT 'anon',
    url           TEXT,
    broj          TEXT,                  -- npr. Rev-533/2015-2
    sud_id        INTEGER REFERENCES sudovi(sud_id),
    upisnik_id    INTEGER REFERENCES upisnici(upisnik_id),
    datum         TEXT,                  -- ISO YYYY-MM-DD
    godina        INTEGER,               -- izvedeno iz datuma, za stratifikaciju
    datum_objave  TEXT,
    vrsta         TEXT,                  -- presuda / rjesenje / odluka
    ecli          TEXT,
    pravomocna    INTEGER,               -- 0/1/NULL
    datum_pravom  TEXT,
    stvarno_kazalo   TEXT,               -- 85 B/dok
    zakonsko_kazalo  TEXT,               -- 264 B/dok, najveci metapodatak
    eurovoc          TEXT,               -- 76 B/dok
    prethodne     TEXT,
    naknadne      TEXT,
    duljina       INTEGER,               -- znakova u tekstu (QA + stratifikacija)
    sha256        BLOB,                  -- 32 B; dedup i detekcija izmjene
    uzorak_kljuc  INTEGER NOT NULL,      -- random(); vidi indeks ix_strat
    dohvaceno     TEXT DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- 3. TEKST: zasebna tablica, zlib-6 BLOB
--
-- Mjereno na uzorku od 200 odluka:
--   zlib-1  omjer 0.3902  komp 0.424 ms/dok  dekomp 0.135 ms/dok
--   zlib-6  omjer 0.3372  komp 1.072 ms/dok  dekomp 0.124 ms/dok
--   zlib-9  omjer 0.3368  komp 1.275 ms/dok  dekomp 0.129 ms/dok
-- Razina 9 donosi 0.04% preko razine 6 uz 19% vise CPU-a: ne isplati se.
-- Razina 6 je izbor. Na punom korpusu: 8.19 GB umjesto 23.03 GB.
-- Dekompresija od 0.124 ms/dok znaci ~6 ms za stranicu od 50 pogodaka.
-- ---------------------------------------------------------------------
-- NAPOMENA: provedbena shema zivi u scrapers/store.py (SHEMA, POGLEDI,
-- FTS_SHEMA) i ona je mjerodavna. Ova datoteka je referenca za mjerilo i
-- drzi tablice crawla (zadaci, red_cekanja, dohvat_log) koje store.py jos
-- ne stvara jer se masovno prikupljanje ne pokrece (vidi dio 0 dokumenta
-- docs/arhitektura-korpusa.md).
--
-- Tablica je OBICNA (rowid), ne WITHOUT ROWID. Izmjereno nad 4876 stvarnih
-- zapisa uz page_size 4096:  WITHOUT ROWID 8344,8 B/dok, rowid 7528,6 B/dok.
-- U indeksnom B-stablu lokalno stane oko 1 kB po retku, pa gotovo svaki BLOB
-- ode u overflow lanac; u rowid tablici lokalno stane oko 4 kB.
-- Razlika je 0,96 GB na punom korpusu uz jednako brz dohvat po kljucu.
CREATE TABLE IF NOT EXISTS tekstovi (
    rid          INTEGER NOT NULL REFERENCES odluke(rid) ON DELETE CASCADE,
    vrsta_zapisa TEXT NOT NULL DEFAULT 'tekst',  -- 'tekst' | 'meta'
    komp         INTEGER NOT NULL DEFAULT 6,     -- 0 = cisti UTF-8, 6 = zlib-6
    n_bajt       INTEGER,                        -- duljina nekomprimiranog UTF-8
    tekst        BLOB NOT NULL,
    PRIMARY KEY (rid, vrsta_zapisa)
);

-- Pogled koji dekomprimira. Aplikacija mora registrirati SQL funkciju
-- 'odzipaj' (con.create_function). Provjereno na SQLite 3.39.5: FTS5 s
-- vanjskim sadrzajem nad OVIM pogledom radi u cijelosti - MATCH, bm25,
-- snippet(), highlight(), 'rebuild' i 'delete'.
--
-- Spojeni stupci se dohvacaju SKALARNIM PODUPITIMA, a ne JOIN-om, i to nije
-- stvar ukusa. Pogled ciji FROM sadrzi LEFT JOIN-ove SQLite ne moze
-- spljostiti u nadredeni upit nego ga MATERIJALIZIRA, pa upit koji spaja
-- pogled na odluke_fts dekomprimira CIJELI korpus da bi vratio pet redaka.
-- Izmjereno na 2439 odluka, upit '"stjecanje bez osnove"':
--     s LEFT JOIN-ovima      738,5 ms  (EXPLAIN QUERY PLAN: MATERIALIZE)
--     sa skalarnim podupitima 16,3 ms
-- Puno skeniranje pogleda jednako je brzo u obje varijante (571 vs 569 ms).
CREATE VIEW IF NOT EXISTS v_odluke AS
SELECT o.rid AS rid,
       COALESCE(o.broj, '') AS broj,
       COALESCE((SELECT s.naziv FROM sudovi s WHERE s.sud_id = o.sud_id), '') AS sud,
       COALESCE(o.stvarno_kazalo, '') AS kazalo,
       COALESCE((SELECT CASE WHEN t.komp = 0 THEN CAST(t.tekst AS TEXT)
                             ELSE odzipaj(t.tekst) END
                   FROM tekstovi t
                  WHERE t.rid = o.rid AND t.vrsta_zapisa = 'tekst'), '') AS tekst
FROM odluke o;

-- ---------------------------------------------------------------------
-- 4. FTS5: vanjski sadrzaj nad dekomprimirajucim pogledom
--
-- Izmjerene velicine indeksa (2439 odluka, samo stupac tekst, nakon
-- 'optimize'), i projekcija na 1.173.225:
--   detail=full    6771 B/dok   ->  7.94 GB   (fraze, NEAR, snippet)
--   detail=column  2924 B/dok   ->  3.43 GB   (bez fraza i NEAR)
--   detail=none    1160 B/dok   ->  1.36 GB   (samo prisutnost pojma)
-- Za pravni korpus fraze su temeljna operacija ("stjecanje bez osnove",
-- doslovni citati clanaka), pa je detail=full opravdan.
--
-- Vanjski sadrzaj naspram contentless: indeks je jednake velicine
-- (16515072 B u oba slucaja), ali contentless gubi snippet()/highlight(),
-- a na SQLite 3.39.5 nema ni contentless_delete=1, pa brisanje trazi da
-- se izvorni tekst ponovno preda upitu. Vanjski sadrzaj nad pogledom
-- daje contentless cijenu na disku uz puni skup mogucnosti.
--
-- BEZ prefix= opcije. Izmjereno na istih 2439 odluka:
--   bez prefiksa   6771 B/dok  ->  7.94 GB   'sumsk*' za 1.7 ms
--   prefix='3'    10281 B/dok  -> 12.06 GB   'sumsk*' za 1.5 ms
--   prefix='2 3'  13907 B/dok  -> 16.32 GB   'sumsk*' za 1.5 ms
-- Prefiksna pretraga i bez prefiksnog indeksa traje 1.7 ms, pa 8.4 GB
-- dodatnog diska kupuje 0.2 ms. Ne isplati se.
-- ---------------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS odluke_fts USING fts5(
    broj, sud, kazalo, tekst,
    content='v_odluke', content_rowid='rid',
    tokenize='unicode61 remove_diacritics 2'
);

-- ---------------------------------------------------------------------
-- 5. INDEKSI ZA STRATIFICIRANO UZORKOVANJE
--
-- uzorak_kljuc je trajni slucajni broj upisan pri unosu. Time nasumican
-- izbor unutar sloja postaje raspon po indeksu s LIMIT-om, dakle O(k),
-- umjesto ORDER BY random() koji nad 1.17M redaka mora proci sve.
-- Uz to je ponovljiv: isti kljuc daje isti uzorak.
--
--   SELECT rid FROM odluke
--    WHERE sud_id=? AND godina=? AND uzorak_kljuc > ?
--    ORDER BY uzorak_kljuc LIMIT 50;
--
-- Izmjereni trosak pomocnih indeksa: ~77 B/dok ukupno, 0.09 GB na
-- punom korpusu. Zanemarivo naspram koristi.
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_strat_sud
    ON odluke(sud_id, godina, uzorak_kljuc);
CREATE INDEX IF NOT EXISTS ix_strat_upisnik
    ON odluke(upisnik_id, godina, uzorak_kljuc);
CREATE INDEX IF NOT EXISTS ix_odluke_godina  ON odluke(godina, sud_id);
CREATE INDEX IF NOT EXISTS ix_odluke_datum   ON odluke(datum);
CREATE INDEX IF NOT EXISTS ix_odluke_izvor   ON odluke(izvor);
CREATE INDEX IF NOT EXISTS ix_odluke_sha     ON odluke(sha256);

-- Predizracunate velicine slojeva; bez toga svaki plan uzorkovanja
-- pokrece agregaciju nad 1.17M redaka.
CREATE TABLE IF NOT EXISTS slojevi (
    sud_id     INTEGER,
    upisnik_id INTEGER,
    godina     INTEGER,
    n          INTEGER NOT NULL,
    osvjezeno  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sud_id, upisnik_id, godina)
) WITHOUT ROWID;

-- ---------------------------------------------------------------------
-- 6. NAPREDAK CRAWLA
--
-- Trazilica portala vraca najvise 10.000 pogodaka po upitu (1000 stranica
-- po 10). Pokrivanje 1.17M odluka zato NIJE jedan upit nego razdioba
-- prostora upita na celije koje svaka daje ispod 10.000 pogodaka:
-- (sud, upisnik, godina), a ako je celija prevelika, dijeli se na mjesece
-- pa po potrebi na dane.
--
-- Tablica 'zadaci' je jedini izvor istine o tome gdje je crawl stao.
-- Nastavak nakon prekida je: uzmi sljedecu celiju u stanju 'ceka' ili
-- onu u 'u_tijeku' ciji je zahvat istekao.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS zadaci (
    zadatak_id   INTEGER PRIMARY KEY,
    izvor        TEXT NOT NULL DEFAULT 'anon',
    sud_id       INTEGER,
    upisnik_id   INTEGER,
    od_datuma    TEXT,          -- granice celije, ISO
    do_datuma    TEXT,
    upit         TEXT,          -- doslovan q= ako se koristi tekstualni upit
    ocekivano    INTEGER,       -- 'ukupno' koje je portal prijavio
    stranica     INTEGER NOT NULL DEFAULT 0,   -- zadnja POTVRDENO obradena
    spremljeno   INTEGER NOT NULL DEFAULT 0,   -- koliko je odluka upisano
    stanje       TEXT NOT NULL DEFAULT 'ceka',
                 -- 'ceka' | 'u_tijeku' | 'gotovo' | 'prevelika' | 'greska'
    pokusaja     INTEGER NOT NULL DEFAULT 0,
    zadnja_greska TEXT,
    zahvat_do    TEXT,          -- do kada radnik drzi celiju (istek zahvata)
    sljedeci_pokusaj TEXT,      -- za odgodu nakon 429/5xx
    azurirano    TEXT DEFAULT (datetime('now')),
    UNIQUE (izvor, sud_id, upisnik_id, od_datuma, do_datuma, upit)
);
CREATE INDEX IF NOT EXISTS ix_zadaci_red
    ON zadaci(stanje, sljedeci_pokusaj, zadatak_id);

-- Zapis svakog mreznog dodira: sluzi za postivanje portala (mjerenje
-- stvarne stope), za dijagnostiku 429/5xx i za dokaz da crawl nije
-- prelazio dogovorene granice.
CREATE TABLE IF NOT EXISTS dohvat_log (
    id         INTEGER PRIMARY KEY,
    zadatak_id INTEGER REFERENCES zadaci(zadatak_id),
    kada       TEXT DEFAULT (datetime('now')),
    putanja    TEXT,
    status     INTEGER,
    ms         INTEGER,
    bajtova    INTEGER
);
CREATE INDEX IF NOT EXISTS ix_log_kada ON dohvat_log(kada);

-- Odluke koje su viđene u rezultatima ali jos nisu preuzete. Razdvaja
-- fazu "popisi" od faze "preuzmi", pa prekid u bilo kojoj ne gubi rad.
CREATE TABLE IF NOT EXISTS red_cekanja (
    id          TEXT PRIMARY KEY,       -- UUID odluke
    zadatak_id  INTEGER,
    prioritet   INTEGER NOT NULL DEFAULT 0,
    pokusaja    INTEGER NOT NULL DEFAULT 0,
    stanje      TEXT NOT NULL DEFAULT 'ceka',  -- 'ceka'|'gotovo'|'greska'
    dodano      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_red_stanje
    ON red_cekanja(stanje, prioritet DESC, id);
