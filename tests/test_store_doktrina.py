# -*- coding: utf-8 -*-
"""
store, shema 3: korpus drzi dvije vrste gradiva, odluke i doktrinu, uz
jedinstvenu pretragu.

Sve se vrti nad privremenom bazom; stvarni data/corpus.sqlite se ne dira.

Tri skupine testova cuvaju odluke, a ne samo ponasanje:

  TestLicencaJeObavezna     zapis doktrine bez URL-a izvora ili bez licence
      ne ulazi u korpus. Hrcak je otvoreni pristup, ali licenca se razlikuje
      po casopisu pa i po clanku; bez zabiljezene licence kasnije nema
      nacina da se zna smije li se zapis dijeliti.

  TestIndeksiDoktrineSuDjelomicni   indeksi nad poljima doktrine moraju
      ostati djelomicni (WHERE gradivo='doktrina'). Puni indeks na
      (gradivo, godina) izmjeren je na 17,20 B/red, dakle 20 MB na
      projekciji od 1,17 M odluka, za posao koji djelomicni obavlja
      besplatno.

  TestMigracijaSheme2       nadogradnja 2 -> 3 nad bazom u tocno onoj shemi
      u kojoj je stvarnih 2439 odluka. Nijedan redak, tekst, sha256 ni
      pogodak u FTS-u ne smije se izgubiti.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mreza_straza  # noqa: E402,F401  postavlja putanje i zabranjuje mrezu

import store  # noqa: E402

ODLUKA = {
    "id": "05c6cdd3-1486-4903-b85f-eda703b4e5e0",
    "izvor": "anon",
    "url": "https://odluke.sudovi.hr/Document/View?id=05c6cdd3",
    "broj": "Rev-533/2015-2",
    "sud": u"Vrhovni sud Republike Hrvatske",
    "datum": "2019-02-22",
    "vrsta": u"presuda",
    "upisnik": "Rev",
    "kazalo": u"stvarna prava > zamjena nekretnina",
    "tekst": (u"Odbija se revizija tuženika kao neosnovana. Zamjena šumskog "
              u"zemljišta na temelju članka 55. Zakona o šumama. ") * 20,
}

CLANAK = {
    "id": "hrcak:315902",
    "gradivo": "doktrina",
    "izvor": "hrcak",
    "url": "https://hrcak.srce.hr/315902",
    "naslov": u"Zamjena šumskog zemljišta i načelo jedinstvenosti nekretnine",
    "autori": [u"Gliha, Igor", u"Josipović, Tatjana"],
    "casopis": u"Zbornik Pravnog fakulteta u Zagrebu",
    "citat": u"Vol. 74 (2024), 2, 199-230",
    "godina": 2024,
    "vrsta": u"izvorni znanstveni rad",
    "kazalo": u"šumsko zemljište; zamjena; jedinstvenost nekretnine",
    "doi": "10.3935/zpfz.74.2.01",
    "licenca": "CC BY-NC-ND 4.0",
    "licenca_url": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
    "sazetak": (u"Rad analizira institut zamjene šumskog zemljišta u svjetlu "
                u"načela superficies solo cedit. " * 6),
    "tekst": (u"Uvod. Institut zamjene šumskog zemljišta uređen je člankom 55. "
              u"Zakona o šumama, a doktrina o tome nije jedinstvena. ") * 20,
    "meta": {"issn": "0350-2058", "jezik": "hrv"},
}


class BazaTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="presude_dok_")
        self.db = os.path.join(self.dir, "corpus_test.sqlite")
        self.con = store.veza(self.db)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def oba(self):
        store.spremi(self.con, ODLUKA)
        store.spremi(self.con, CLANAK)


# ------------------------------------------------------------ vrsta gradiva ---

class TestVrstaGradiva(BazaTest):

    def test_zadano_je_odluka(self):
        store.spremi(self.con, ODLUKA)
        r = store.dohvati(self.con, ODLUKA["id"])
        self.assertEqual(r["gradivo"], "odluka")

    def test_doktrina_se_zapisuje_kao_doktrina(self):
        store.spremi(self.con, CLANAK)
        self.assertEqual(store.dohvati(self.con, CLANAK["id"])["gradivo"],
                         "doktrina")

    def test_spremi_doktrinu_ne_trazi_gradivo_u_zapisu(self):
        bez = {k: v for k, v in CLANAK.items() if k != "gradivo"}
        self.assertTrue(store.spremi_doktrinu(self.con, bez))
        self.assertEqual(store.dohvati(self.con, CLANAK["id"])["gradivo"],
                         "doktrina")

    def test_nepoznata_vrsta_gradiva_je_greska(self):
        with self.assertRaises(ValueError):
            store.spremi(self.con, dict(ODLUKA, gradivo="komentar"))

    def test_obje_vrste_zive_u_istoj_tablici(self):
        self.oba()
        n = dict(self.con.execute(
            "SELECT gradivo, COUNT(*) FROM odluke_meta GROUP BY 1").fetchall())
        self.assertEqual(n, {"odluka": 1, "doktrina": 1})


# --------------------------------------------------------- obavezna licenca ---

class TestLicencaJeObavezna(BazaTest):

    def test_bez_licence_ne_ulazi(self):
        bez = {k: v for k, v in CLANAK.items() if k != "licenca"}
        with self.assertRaises(ValueError) as e:
            store.spremi(self.con, bez)
        self.assertIn("licenc", str(e.exception).lower())
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM odluke_meta").fetchone()[0], 0)

    def test_bez_url_a_ne_ulazi(self):
        bez = {k: v for k, v in CLANAK.items() if k != "url"}
        with self.assertRaises(ValueError):
            store.spremi(self.con, bez)

    def test_prazna_licenca_je_isto_sto_i_nikakva(self):
        with self.assertRaises(ValueError):
            store.spremi(self.con, dict(CLANAK, licenca="   "))

    def test_sva_prava_pridrzana_je_valjan_upis(self):
        """Zapis sa zabranom je uredan zapis; zapis bez licence nije."""
        self.assertTrue(store.spremi(
            self.con, dict(CLANAK, licenca=u"Sva prava pridržana")))
        r = store.dohvati(self.con, CLANAK["id"])
        self.assertEqual(r["redistribucija"], "zabranjena")

    def test_odluka_ne_treba_licencu(self):
        self.assertTrue(store.spremi(self.con, {"id": "gol-1"}))


class TestProcjenaLicence(unittest.TestCase):

    def test_slobodne(self):
        for t in ("CC BY 4.0", "CC BY-SA 4.0", "cc0", "CC0 1.0 Universal",
                  u"Creative Commons Attribution 4.0", "public domain"):
            self.assertEqual(store.procijeni_redistribuciju(t), "slobodna", t)

    def test_uvjetne(self):
        for t in ("CC BY-NC 4.0", "CC BY-ND 4.0", "CC BY-NC-ND 4.0",
                  "CC BY-NC-SA 4.0",
                  u"Creative Commons Attribution NonCommercial NoDerivatives"):
            self.assertEqual(store.procijeni_redistribuciju(t), "uvjetna", t)

    def test_zabranjene(self):
        for t in (u"Sva prava pridržana", "All rights reserved",
                  u"sva prava pridrzana"):
            self.assertEqual(store.procijeni_redistribuciju(t), "zabranjena", t)

    def test_neprepoznato_je_none_a_ne_pretpostavka(self):
        """Neprepoznata licenca ne smije se tiho protumaciti kao dopustenje."""
        for t in (None, "", "   ", u"licenca izdavača, upit na uredništvo"):
            self.assertIsNone(store.procijeni_redistribuciju(t), repr(t))

    def test_nc_i_nd_nikad_ne_prolaze_kao_slobodni(self):
        for t in ("CC BY-NC 4.0", "CC BY-NC-ND 4.0", "CC BY-ND 3.0"):
            self.assertNotEqual(store.procijeni_redistribuciju(t), "slobodna", t)


class TestSlobodniZaDijeljenje(BazaTest):

    def test_vraca_samo_slobodne(self):
        store.spremi(self.con, dict(CLANAK, id="a", licenca="CC BY 4.0"))
        store.spremi(self.con, dict(CLANAK, id="b", licenca="CC BY-NC-ND 4.0"))
        store.spremi(self.con, dict(CLANAK, id="c", licenca=u"Sva prava pridržana"))
        store.spremi(self.con, dict(CLANAK, id="d", licenca=u"nešto deseto"))
        store.spremi(self.con, ODLUKA)
        self.assertEqual([r["id"] for r in store.slobodni_za_dijeljenje(self.con)],
                         ["a"])


# ------------------------------------------------------------ polja doktrine ---

class TestPoljaDoktrine(BazaTest):

    def test_bibliografija_se_cita_natrag(self):
        store.spremi(self.con, CLANAK)
        r = store.dohvati(self.con, CLANAK["id"])
        self.assertEqual(r["naslov"], CLANAK["naslov"])
        self.assertEqual(r["casopis"], CLANAK["casopis"])
        self.assertEqual(r["citat"], CLANAK["citat"])
        self.assertEqual(r["doi"], CLANAK["doi"])
        self.assertEqual(r["godina"], 2024)
        self.assertEqual(r["url"], CLANAK["url"])
        self.assertEqual(r["licenca"], CLANAK["licenca"])
        self.assertEqual(r["redistribucija"], "uvjetna")

    def test_autori_se_spajaju_u_jedan_niz(self):
        store.spremi(self.con, CLANAK)
        self.assertEqual(store.dohvati(self.con, CLANAK["id"])["autori"],
                         u"Gliha, Igor; Josipović, Tatjana")

    def test_autori_mogu_biti_i_obican_niz(self):
        store.spremi(self.con, dict(CLANAK, autori=u"Dika, Mihajlo"))
        self.assertEqual(store.dohvati(self.con, CLANAK["id"])["autori"],
                         u"Dika, Mihajlo")

    def test_godina_bez_datuma(self):
        """Clanak ima godinu izdanja, ali cesto nema puni datum."""
        store.spremi(self.con, CLANAK)
        r = store.dohvati(self.con, CLANAK["id"])
        self.assertEqual(r["godina"], 2024)
        self.assertIsNone(r["datum"])

    def test_sazetak_je_komprimiran_a_cita_se_kao_tekst(self):
        store.spremi(self.con, CLANAK)
        self.assertEqual(store.sazetak(self.con, CLANAK["id"]), CLANAK["sazetak"])
        vrsta, komp = self.con.execute(
            "SELECT typeof(tijelo), komp FROM tekstovi "
            "WHERE vrsta_zapisa='sazetak'").fetchone()
        self.assertEqual(vrsta, "blob")
        self.assertEqual(komp, store.KOMP_RAZINA)

    def test_odluka_nema_sazetak(self):
        store.spremi(self.con, ODLUKA)
        self.assertIsNone(store.sazetak(self.con, ODLUKA["id"]))

    def test_tekst_i_sazetak_su_odvojeni(self):
        store.spremi(self.con, CLANAK)
        r = store.dohvati(self.con, CLANAK["id"])
        self.assertEqual(r["tekst"], CLANAK["tekst"])
        self.assertEqual(r["sazetak"], CLANAK["sazetak"])

    def test_ostatak_bibliografije_ide_u_meta(self):
        store.spremi(self.con, CLANAK)
        r = store.dohvati(self.con, CLANAK["id"])
        self.assertEqual(json.loads(r["meta_json"])["issn"], "0350-2058")

    def test_dopuna_ne_brise_vec_zapisano(self):
        """Naknadno nadeni DOI ne smije obrisati naslov i autore."""
        store.spremi(self.con, CLANAK)
        store.spremi(self.con, {"id": CLANAK["id"], "gradivo": "doktrina",
                                "url": CLANAK["url"], "licenca": CLANAK["licenca"],
                                "doi": "10.9999/novi"})
        r = store.dohvati(self.con, CLANAK["id"])
        self.assertEqual(r["doi"], "10.9999/novi")
        self.assertEqual(r["naslov"], CLANAK["naslov"])
        self.assertEqual(r["casopis"], CLANAK["casopis"])

    def test_ponovno_spremanje_ne_stvara_duplikat(self):
        self.assertTrue(store.spremi(self.con, CLANAK))
        self.assertFalse(store.spremi(self.con, CLANAK))
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM odluke_meta").fetchone()[0], 1)


# -------------------------------------------------------- jedinstvena pretraga ---

class TestJedinstvenaPretraga(BazaTest):

    def test_jedan_upit_nalazi_obje_vrste(self):
        self.oba()
        pogodci = store.trazi(self.con, u"šumskog")
        self.assertEqual({r["gradivo"] for r in pogodci}, {"odluka", "doktrina"})

    def test_filtar_po_vrsti(self):
        self.oba()
        samo_o = store.trazi(self.con, u"šumskog", vrsta="odluka")
        samo_d = store.trazi(self.con, u"šumskog", vrsta="doktrina")
        self.assertEqual([r["id"] for r in samo_o], [ODLUKA["id"]])
        self.assertEqual([r["id"] for r in samo_d], [CLANAK["id"]])

    def test_bez_filtra_je_cijeli_korpus(self):
        self.oba()
        self.assertEqual(len(store.trazi(self.con, u"šumskog", vrsta=None)), 2)

    def test_nepoznata_vrsta_je_greska_a_ne_prazan_popis(self):
        self.oba()
        with self.assertRaises(ValueError):
            store.trazi(self.con, u"šumskog", vrsta="komentar")

    def test_naslov_clanka_je_pretraziv(self):
        self.oba()
        r = store.trazi(self.con, u"jedinstvenosti")
        self.assertEqual([x["id"] for x in r], [CLANAK["id"]])

    def test_autor_je_pretraziv_po_stupcu(self):
        self.oba()
        self.assertEqual([r["id"] for r in store.trazi(self.con, u"autori:Gliha")],
                         [CLANAK["id"]])
        self.assertEqual(store.trazi(self.con, u"autori:tuženika"), [])

    def test_casopis_je_pretraziv_po_stupcu(self):
        self.oba()
        r = store.trazi(self.con, u'casopis:"Zbornik Pravnog fakulteta"')
        self.assertEqual([x["id"] for x in r], [CLANAK["id"]])

    def test_sazetak_je_pretraziv(self):
        """Za clanak bez punog teksta sazetak je jedino sto korpus ima."""
        samo_sazetak = dict(CLANAK, id="hrcak:1", tekst="",
                            sazetak=u"Rasprava o pomorskom dobru i koncesijama. " * 8)
        store.spremi(self.con, samo_sazetak)
        r = store.trazi(self.con, u"koncesijama")
        self.assertEqual([x["id"] for x in r], ["hrcak:1"])

    def test_kljucne_rijeci_clanka_su_u_kazalu_i_pretrazive(self):
        self.oba()
        r = store.trazi(self.con, u"kazalo:jedinstvenost")
        self.assertEqual([x["id"] for x in r], [CLANAK["id"]])

    def test_fraza_radi_i_nad_doktrinom(self):
        self.oba()
        self.assertEqual(
            len(store.trazi(self.con, u'"institut zamjene šumskog zemljišta"')), 1)

    def test_pretraga_bez_dijakritika_nalazi_clanak(self):
        self.oba()
        self.assertEqual(len(store.trazi(self.con, u"sumskog", vrsta="doktrina")), 1)

    def test_izmijenjen_naslov_nestaje_iz_indeksa(self):
        store.spremi(self.con, dict(CLANAK, naslov=u"Komasacija u praksi"))
        self.assertEqual(len(store.trazi(self.con, u"Komasacija")), 1)
        store.spremi(self.con, dict(CLANAK, naslov=u"Nešto posve deseto"))
        self.assertEqual(len(store.trazi(self.con, u"Komasacija")), 0)
        self.assertEqual(len(store.trazi(self.con, u"deseto")), 1)

    def test_izmijenjen_sazetak_nestaje_iz_indeksa(self):
        store.spremi(self.con, dict(CLANAK, sazetak=u"Rijec dosjelost. " * 20))
        self.assertEqual(len(store.trazi(self.con, u"dosjelost")), 1)
        store.spremi(self.con, dict(CLANAK, sazetak=u"Rijec komasacija. " * 20))
        self.assertEqual(len(store.trazi(self.con, u"dosjelost")), 0)
        self.assertEqual(len(store.trazi(self.con, u"komasacija")), 1)

    def test_isjecak_dolazi_iz_teksta_clanka(self):
        self.oba()
        r = store.trazi(self.con, u"doktrina", vrsta="doktrina")
        self.assertEqual(len(r), 1)
        self.assertIn(u"»", r[0]["isjecak"])

    def test_rijec_doktrina_u_odluci_ne_postaje_filtar(self):
        """
        Filtar ide preko stupca `gradivo`, ne preko MATCH-a. Da ide preko
        MATCH-a, ova bi odluka ispala kao doktrina.
        """
        store.spremi(self.con, dict(
            ODLUKA, id="o-2",
            tekst=u"Doktrina i sudska praksa o zamjeni zemljišta su jasne. " * 20))
        r = store.trazi(self.con, u"doktrina", vrsta="doktrina")
        self.assertEqual(r, [])
        r = store.trazi(self.con, u"doktrina", vrsta="odluka")
        self.assertEqual([x["id"] for x in r], ["o-2"])


class TestPogledOstajeSpljosten(BazaTest):
    """
    Filtar po vrsti ne smije natjerati SQLite da materijalizira pogled.
    Materijalizacija je za pet redaka nekoc kostala 738 ms umjesto 16 ms,
    jer je dekomprimirala cijeli korpus.
    """

    def plan(self, sql, par):
        return "\n".join(r[3] for r in
                         self.con.execute("EXPLAIN QUERY PLAN " + sql, par))

    def test_filtar_po_gradivu_ne_materijalizira(self):
        self.oba()
        p = self.plan(
            "SELECT o.*, bm25(odluke_fts) AS rang FROM odluke_fts "
            "JOIN odluke o ON o.rowid = odluke_fts.rowid "
            "WHERE odluke_fts MATCH ? AND o.gradivo = ? ORDER BY rang LIMIT 5",
            (u"zamjena", "doktrina"))
        self.assertNotIn("MATERIALIZE", p.upper(), p)


class TestIndeksiDoktrineSuDjelomicni(BazaTest):
    """
    Izmjereno na 20 000 odluka bez ijednog clanka: sva tri djelomicna
    indeksa zauzimaju po jednu stranicu (4096 B). Puni indeks na
    (gradivo, godina) stajao je 17,20 B/red, dakle 20 MB na projekciji.
    """

    def test_indeksi_nose_uvjet_gradiva(self):
        for ime in ("ix_doktrina_godina", "ix_doktrina_casopis",
                    "ix_doktrina_licenca"):
            sql = self.con.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (ime,)).fetchone()
            self.assertIsNotNone(sql, "nema indeksa %s" % ime)
            self.assertIn("WHERE", sql[0].upper(), ime)
            self.assertIn("gradivo", sql[0], ime)

    def test_nema_punog_indeksa_po_gradivu(self):
        red = self.con.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='ix_gradivo'"
        ).fetchone()
        self.assertIsNone(red, "puni indeks po gradivu kosta 17,2 B/red")

    def test_upit_po_casopisu_koristi_djelomicni_indeks(self):
        plan = "\n".join(r[3] for r in self.con.execute(
            "EXPLAIN QUERY PLAN SELECT rid FROM odluke_meta "
            "WHERE gradivo='doktrina' AND casopis=?", (u"Zbornik",)))
        self.assertIn("ix_doktrina_casopis", plan)


class TestStatistika(BazaTest):

    def test_broji_po_vrsti_gradiva(self):
        self.oba()
        s = store.statistika(self.con)
        self.assertEqual(s["po_gradivu"], {"odluka": 1, "doktrina": 1})

    def test_broji_doktrinu_po_pravu_dijeljenja(self):
        store.spremi(self.con, dict(CLANAK, id="a", licenca="CC BY 4.0"))
        store.spremi(self.con, dict(CLANAK, id="b", licenca="CC BY-NC 4.0"))
        store.spremi(self.con, ODLUKA)
        s = store.statistika(self.con)
        self.assertEqual(s["po_licenci"], {"slobodna": 1, "uvjetna": 1})

    def test_casopisi(self):
        self.oba()
        self.assertEqual(store.statistika(self.con)["po_casopisu"],
                         {CLANAK["casopis"]: 1})


# ---------------------------------------------------------------- shema 2 ---
#
# Doslovna shema 2, prepisana iz stvarnog data/corpus.sqlite (2439 odluka).
# Test migracije mora polaziti od onoga sto na disku stvarno stoji, a ne od
# rekonstrukcije po sjecanju.

SHEMA_V2 = """
CREATE TABLE sudovi (
    sud_id INTEGER PRIMARY KEY, naziv TEXT NOT NULL UNIQUE,
    razina TEXT, vrsta TEXT
);
CREATE TABLE upisnici (
    upisnik_id INTEGER PRIMARY KEY, oznaka TEXT NOT NULL UNIQUE, naziv TEXT
);
CREATE TABLE odluke_meta (
    rid           INTEGER PRIMARY KEY,
    id            TEXT NOT NULL UNIQUE,
    izvor         TEXT NOT NULL DEFAULT 'anon',
    url           TEXT, broj TEXT,
    sud_id        INTEGER REFERENCES sudovi(sud_id),
    upisnik_id    INTEGER REFERENCES upisnici(upisnik_id),
    datum         TEXT, godina INTEGER, vrsta TEXT, ecli TEXT,
    pravomocnost  TEXT, kazalo TEXT, zakonsko_kazalo TEXT, eurovoc TEXT,
    propisi       TEXT, duljina INTEGER, sha256 BLOB,
    uzorak_kljuc  INTEGER NOT NULL DEFAULT 0,
    nacin_odabira TEXT NOT NULL DEFAULT 'ciljano',
    dohvaceno     TEXT DEFAULT (datetime('now'))
);
CREATE TABLE tekstovi (
    rid INTEGER NOT NULL REFERENCES odluke_meta(rid) ON DELETE CASCADE,
    vrsta_zapisa TEXT NOT NULL DEFAULT 'tekst',
    komp INTEGER NOT NULL DEFAULT 6, n_bajt INTEGER, tijelo BLOB NOT NULL,
    PRIMARY KEY (rid, vrsta_zapisa)
);
CREATE TABLE pretrage (
    upit TEXT, izvor TEXT, stranica INTEGER, pogodaka INTEGER,
    obavljeno TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (upit, izvor, stranica)
);
CREATE TABLE slojevi (
    sud_id INTEGER, upisnik_id INTEGER, godina INTEGER, n INTEGER NOT NULL,
    osvjezeno TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sud_id, upisnik_id, godina)
) WITHOUT ROWID;
CREATE INDEX ix_strat_sud      ON odluke_meta(sud_id, godina, uzorak_kljuc);
CREATE INDEX ix_strat_upisnik  ON odluke_meta(upisnik_id, godina, uzorak_kljuc);
CREATE INDEX ix_strat_nacin    ON odluke_meta(nacin_odabira, uzorak_kljuc);
CREATE INDEX ix_odluke_godina  ON odluke_meta(godina, sud_id);
CREATE INDEX ix_odluke_datum   ON odluke_meta(datum);
CREATE INDEX ix_odluke_izvor   ON odluke_meta(izvor);
CREATE INDEX ix_odluke_sha     ON odluke_meta(sha256);
CREATE VIEW v_odluke AS
SELECT o.rid AS rid,
       COALESCE(o.broj, '') AS broj,
       COALESCE((SELECT s.naziv FROM sudovi s WHERE s.sud_id = o.sud_id), '') AS sud,
       COALESCE(o.kazalo, '') AS kazalo,
       COALESCE((SELECT CASE WHEN t.komp = 0 THEN CAST(t.tijelo AS TEXT)
                             ELSE odzipaj(t.tijelo) END
                   FROM tekstovi t
                  WHERE t.rid = o.rid AND t.vrsta_zapisa = 'tekst'), '') AS tekst
FROM odluke_meta o;
CREATE VIEW odluke AS
SELECT o.rid AS rowid, o.rid AS rid, o.id AS id, o.izvor AS izvor,
       o.url AS url, o.broj AS broj,
       (SELECT s.naziv FROM sudovi s WHERE s.sud_id = o.sud_id) AS sud,
       o.datum AS datum, o.godina AS godina, o.vrsta AS vrsta,
       (SELECT u.oznaka FROM upisnici u WHERE u.upisnik_id = o.upisnik_id) AS upisnik,
       o.ecli AS ecli, o.pravomocnost AS pravomocnost, o.kazalo AS kazalo,
       o.zakonsko_kazalo AS zakonsko_kazalo, o.eurovoc AS eurovoc,
       o.propisi AS propisi,
       COALESCE((SELECT CASE WHEN t.komp = 0 THEN CAST(t.tijelo AS TEXT)
                             ELSE odzipaj(t.tijelo) END
                   FROM tekstovi t
                  WHERE t.rid = o.rid AND t.vrsta_zapisa = 'tekst'), '') AS tekst,
       COALESCE((SELECT CASE WHEN m.komp = 0 THEN CAST(m.tijelo AS TEXT)
                             ELSE odzipaj(m.tijelo) END
                   FROM tekstovi m
                  WHERE m.rid = o.rid AND m.vrsta_zapisa = 'meta'), '{}') AS meta_json,
       o.duljina AS duljina, o.sha256 AS sha256,
       o.uzorak_kljuc AS uzorak_kljuc, o.nacin_odabira AS nacin_odabira,
       o.sud_id AS sud_id, o.upisnik_id AS upisnik_id, o.dohvaceno AS dohvaceno
FROM odluke_meta o;
CREATE VIRTUAL TABLE odluke_fts USING fts5(
    broj, sud, kazalo, tekst,
    content='v_odluke', content_rowid='rid',
    tokenize='unicode61 remove_diacritics 2'
);
"""


def napravi_v2(put, zapisi):
    """Baza u shemi 2, onakva kakva je prije ove promjene bila na disku."""
    import hashlib
    con = sqlite3.connect(put)
    con.create_function("odzipaj", 1, store.odzipaj, deterministic=True)
    con.executescript(SHEMA_V2)
    for i, z in enumerate(zapisi, start=1):
        sid = None
        if z.get("sud"):
            con.execute("INSERT OR IGNORE INTO sudovi (naziv) VALUES (?)", (z["sud"],))
            sid = con.execute("SELECT sud_id FROM sudovi WHERE naziv=?",
                              (z["sud"],)).fetchone()[0]
        t = z.get("tekst") or ""
        con.execute(
            "INSERT INTO odluke_meta (rid, id, izvor, url, broj, sud_id, datum, "
            "godina, vrsta, kazalo, propisi, duljina, sha256, uzorak_kljuc, "
            "nacin_odabira) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (i, z["id"], z.get("izvor") or "anon", z.get("url"), z.get("broj"),
             sid, z.get("datum"), store._godina(z.get("datum")), z.get("vrsta"),
             z.get("kazalo"), z.get("propisi"), len(t),
             hashlib.sha256(t.encode("utf-8")).digest(),
             store._uzorak_kljuc(z["id"]), "ciljano"))
        komp, n, blob = store.zipaj(t)
        con.execute("INSERT INTO tekstovi (rid, vrsta_zapisa, komp, n_bajt, tijelo) "
                    "VALUES (?,'tekst',?,?,?)", (i, komp, n, blob))
        if z.get("meta"):
            komp, n, blob = store.zipaj(json.dumps(z["meta"], ensure_ascii=False))
            con.execute("INSERT INTO tekstovi (rid, vrsta_zapisa, komp, n_bajt, tijelo) "
                        "VALUES (?,'meta',?,?,?)", (i, komp, n, blob))
    con.execute("INSERT INTO pretrage VALUES ('zamjena','anon',1,42,'2026-01-01')")
    con.execute("INSERT INTO odluke_fts(odluke_fts) VALUES ('rebuild')")
    con.execute("PRAGMA user_version = 2")
    con.commit()
    con.close()


class TestMigracijaSheme2(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="presude_mig3_")
        self.db = os.path.join(self.dir, "stari.sqlite")
        self.zapisi = [
            dict(ODLUKA, meta={"Sud": ODLUKA["sud"]}),
            dict(ODLUKA, id="drugi", broj=u"Gž-101/2020-3",
                 sud=u"Županijski sud u Splitu", datum="2020-05-05",
                 tekst=u"Komasacija zemljišta je provedena. " * 30),
            dict(ODLUKA, id="prazan", tekst="", sud=None, datum=None, kazalo=None,
                 meta=None),
        ]
        napravi_v2(self.db, self.zapisi)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_veza_prepozna_i_nadogradi(self):
        con = store.veza(self.db)
        try:
            self.assertEqual(store._verzija(con), 3)
            self.assertIn("gradivo",
                          {r[1] for r in con.execute("PRAGMA table_info(odluke_meta)")})
        finally:
            con.close()

    def test_nijedan_redak_se_ne_gubi(self):
        con = store.veza(self.db)
        try:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM odluke_meta").fetchone()[0],
                len(self.zapisi))
        finally:
            con.close()

    def test_nijedno_polje_se_ne_gubi(self):
        con = store.veza(self.db)
        try:
            for z in self.zapisi:
                r = con.execute("SELECT * FROM odluke WHERE id=?",
                                (z["id"],)).fetchone()
                self.assertIsNotNone(r, "nestao zapis %r" % z["id"])
                self.assertEqual(r["tekst"], z["tekst"] or "", z["id"])
                self.assertEqual(r["broj"], z["broj"], z["id"])
                self.assertEqual(r["sud"], z["sud"], z["id"])
                self.assertEqual(r["datum"], z["datum"], z["id"])
                self.assertEqual(r["kazalo"], z["kazalo"], z["id"])
                self.assertEqual(json.loads(r["meta_json"]),
                                 z.get("meta") or {}, z["id"])
        finally:
            con.close()

    def test_sve_postojece_postaje_odluka(self):
        con = store.veza(self.db)
        try:
            self.assertEqual(
                dict(con.execute("SELECT gradivo, COUNT(*) FROM odluke_meta "
                                 "GROUP BY 1").fetchall()),
                {"odluka": len(self.zapisi)})
        finally:
            con.close()

    def test_sha256_ostaje_isti(self):
        """
        Indeksni tekst odluke je i dalje doslovno tekst, pa nadogradnja ne
        smije promijeniti nijedan sha256. Da ga mijenja, sljedeci bi crawl
        mislio da su se sve odluke promijenile.
        """
        prije = dict(sqlite3.connect(self.db).execute(
            "SELECT id, sha256 FROM odluke_meta").fetchall())
        con = store.veza(self.db)
        try:
            poslije = dict(con.execute("SELECT id, sha256 FROM odluke_meta").fetchall())
            self.assertEqual(prije, poslije)
        finally:
            con.close()

    def test_fts_radi_nakon_nadogradnje(self):
        con = store.veza(self.db)
        try:
            self.assertEqual(len(store.trazi(con, u"komasacija")), 1)
            self.assertEqual(len(store.trazi(con, u"sumskog")), 1)
            self.assertEqual(len(store.trazi(con, u"nepostojecipojam")), 0)
            r = store.trazi(con, u'"zamjena šumskog zemljišta"')
            self.assertEqual(len(r), 1)
            self.assertIn(u"»", r[0]["isjecak"])
        finally:
            con.close()

    def test_fts_indeks_je_dobio_nove_stupce(self):
        con = store.veza(self.db)
        try:
            self.assertEqual(
                tuple(r[1] for r in con.execute("PRAGMA table_info(odluke_fts)")),
                store.FTS_STUPCI)
        finally:
            con.close()

    def test_pretrage_prezive(self):
        con = store.veza(self.db)
        try:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM pretrage").fetchone()[0], 1)
        finally:
            con.close()

    def test_doktrina_se_moze_dodati_nakon_nadogradnje(self):
        con = store.veza(self.db)
        try:
            self.assertTrue(store.spremi(con, CLANAK))
            self.assertEqual(len(store.trazi(con, u"šumskog")), 2)
            self.assertEqual(len(store.trazi(con, u"šumskog", vrsta="odluka")), 1)
            self.assertEqual(len(store.trazi(con, u"šumskog", vrsta="doktrina")), 1)
        finally:
            con.close()

    def test_sigurnosna_kopija_je_napravljena(self):
        store.veza(self.db).close()
        kopija = self.db + ".shema2.bak"
        self.assertTrue(os.path.exists(kopija), "nadogradnja mora ostaviti kopiju")
        stara = sqlite3.connect(kopija)
        try:
            self.assertEqual(
                stara.execute("SELECT COUNT(*) FROM odluke_meta").fetchone()[0],
                len(self.zapisi))
            self.assertNotIn("gradivo", {
                r[1] for r in stara.execute("PRAGMA table_info(odluke_meta)")})
        finally:
            stara.close()

    def test_nadogradnja_je_idempotentna(self):
        store.veza(self.db).close()
        con = store.veza(self.db)
        try:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM odluke_meta").fetchone()[0],
                len(self.zapisi))
            self.assertEqual(len(store.trazi(con, u"komasacija")), 1)
        finally:
            con.close()

    def test_odbija_nadogradnju_kad_je_zabranjena(self):
        with self.assertRaises(RuntimeError):
            store.veza(self.db, auto_migracija=False)

    def test_stara_baza_samo_za_citanje_daje_jasnu_poruku(self):
        """
        otvori_ro ne moze nadograditi bazu, pa stari cetverostupcani FTS puca
        na snippet() sedmog stupca. Poruka mora reci sto uciniti, a ne samo
        "column index out of range".
        """
        ro = store.otvori_ro(self.db)
        try:
            with self.assertRaises(RuntimeError) as e:
                store.trazi(ro, u"komasacija")
            self.assertIn("store.veza", str(e.exception))
        finally:
            ro.close()

    def test_optimiziraj_i_integritet_nakon_nadogradnje(self):
        con = store.veza(self.db)
        try:
            store.spremi(con, CLANAK)
            store.optimiziraj(con, vacuum=True)
            self.assertEqual(
                con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(len(store.trazi(con, u"komasacija")), 1)
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
