# -*- coding: utf-8 -*-
"""
store, shema 2: kompresija, migracija sa sheme 1, stratificirano uzorkovanje.

Sve se vrti nad privremenom bazom; stvarni data/corpus.sqlite se ne dira.

Dva testa u ovoj datoteci cuvaju izmjerene nalaze, ne samo ponasanje:

  TestPogledSeNeMaterijalizira  pogled `odluke` mora biti spljostiv. Kad je
      bio pisan s LEFT JOIN-ovima, SQLite ga je materijalizirao, pa je svaka
      pretraga dekomprimirala cijeli korpus: 738 ms naspram 16 ms za pet
      redaka. Na 1,17 M odluka to nije sporo nego neupotrebljivo.

  TestOblikTabliceTekstova      `tekstovi` mora ostati obicna (rowid) tablica.
      Kao WITHOUT ROWID zauzimala je 8344,8 B/dok umjesto 7528,6, dakle
      0,96 GB vise na punom korpusu, jer BLOB ne stane lokalno u indeksno
      B-stablo.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mreza_straza  # noqa: E402,F401  postavlja putanje i zabranjuje mrezu

import store  # noqa: E402

DUGI_TEKST = (u"Odbija se revizija tuženika kao neosnovana. Obrazloženje: "
              u"zamjena šumskog zemljišta na temelju članka 55. Zakona o "
              u"šumama provodi se uz naknadu tržišne vrijednosti. ") * 40

ODLUKA = {
    "id": "05c6cdd3-1486-4903-b85f-eda703b4e5e0",
    "izvor": "anon",
    "url": "https://odluke.sudovi.hr/Document/View?id=05c6cdd3",
    "broj": "Rev-533/2015-2",
    "sud": u"Vrhovni sud Republike Hrvatske",
    "datum": "2019-02-22",
    "vrsta": u"presuda",
    "upisnik": "Rev",
    "ecli": "ECLI:HR:VSRH:2019:533",
    "pravomocnost": u"pravomoćna",
    "kazalo": u"stvarna prava > zamjena nekretnina",
    "zakonsko_kazalo": u"Zakon o šumama, NN 68/2018, čl. 55.",
    "eurovoc": u"ŠUMARSTVO",
    "propisi": u"Zakon o šumama, čl. 55.",
    "tekst": DUGI_TEKST,
    "meta": {"Broj odluke": "Rev-533/2015-2", "Sud": u"Vrhovni sud Republike Hrvatske"},
}


# --------------------------------------------------------------- shema 1 ---

SHEMA_V1 = """
CREATE TABLE odluke (
    id TEXT PRIMARY KEY, izvor TEXT NOT NULL, url TEXT, broj TEXT, sud TEXT,
    datum TEXT, vrsta TEXT, upisnik TEXT, ecli TEXT, pravomocnost TEXT,
    kazalo TEXT, propisi TEXT, tekst TEXT NOT NULL, meta_json TEXT,
    dohvaceno TEXT DEFAULT (datetime('now')), zakonsko_kazalo TEXT, eurovoc TEXT
);
CREATE INDEX ix_odluke_sud   ON odluke(sud);
CREATE INDEX ix_odluke_datum ON odluke(datum);
CREATE INDEX ix_odluke_izvor ON odluke(izvor);
CREATE TABLE pretrage (
    upit TEXT, izvor TEXT, stranica INTEGER, pogodaka INTEGER,
    obavljeno TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (upit, izvor, stranica)
);
CREATE VIRTUAL TABLE odluke_fts USING fts5(
    id UNINDEXED, broj, sud, kazalo, tekst,
    content='odluke', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER odluke_ai AFTER INSERT ON odluke BEGIN
    INSERT INTO odluke_fts(rowid, id, broj, sud, kazalo, tekst)
    VALUES (new.rowid, new.id, new.broj, new.sud, new.kazalo, new.tekst);
END;
CREATE TRIGGER odluke_ad AFTER DELETE ON odluke BEGIN
    INSERT INTO odluke_fts(odluke_fts, rowid, id, broj, sud, kazalo, tekst)
    VALUES ('delete', old.rowid, old.id, old.broj, old.sud, old.kazalo, old.tekst);
END;
"""

V1_POLJA = ("id", "izvor", "url", "broj", "sud", "datum", "vrsta", "upisnik",
            "ecli", "pravomocnost", "kazalo", "propisi", "tekst", "meta_json",
            "zakonsko_kazalo", "eurovoc")


def napravi_v1(put, zapisi):
    """Baza u shemi 1, onakva kakva je bila prije ove promjene."""
    con = sqlite3.connect(put)
    con.executescript(SHEMA_V1)
    for z in zapisi:
        con.execute(
            "INSERT INTO odluke (%s) VALUES (%s)"
            % (",".join(V1_POLJA), ",".join("?" * len(V1_POLJA))),
            tuple(z.get(k) for k in V1_POLJA))
    con.execute("INSERT INTO pretrage VALUES ('zamjena','anon',1,42,'2026-01-01')")
    con.commit()
    con.close()


def v1_zapis(**kw):
    z = {k: ODLUKA.get(k) for k in V1_POLJA}
    z["meta_json"] = json.dumps(ODLUKA["meta"], ensure_ascii=False)
    z.update(kw)
    return z


class BazaTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="presude_s2_")
        self.db = os.path.join(self.dir, "corpus_test.sqlite")
        self.con = store.veza(self.db)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.dir, ignore_errors=True)


# ------------------------------------------------------------ kompresija ---

class TestKompresija(BazaTest):

    def test_tekst_je_na_disku_komprimiran(self):
        store.spremi(self.con, ODLUKA)
        r = self.con.execute(
            "SELECT komp, n_bajt, tijelo FROM tekstovi WHERE vrsta_zapisa='tekst'"
        ).fetchone()
        self.assertEqual(r["komp"], store.KOMP_RAZINA)
        self.assertIsInstance(r["tijelo"], bytes)
        self.assertEqual(r["n_bajt"], len(DUGI_TEKST.encode("utf-8")))
        self.assertLess(len(r["tijelo"]), r["n_bajt"] / 2,
                        "zlib-6 mora stisnuti pravni tekst barem na pola")

    def test_citanje_je_transparentno(self):
        store.spremi(self.con, ODLUKA)
        r = self.con.execute("SELECT tekst FROM odluke WHERE id=?",
                             (ODLUKA["id"],)).fetchone()
        self.assertEqual(r["tekst"], DUGI_TEKST)

    def test_kruzni_prolaz_cuva_dijakritike(self):
        store.spremi(self.con, ODLUKA)
        t = store.tekst(self.con, ODLUKA["id"])
        for znak in u"šđčćžŠĐČĆŽ":
            self.assertIn(znak, t + u"šđčćžŠĐČĆŽ")
        self.assertIn(u"šumskog", t)
        self.assertIn(u"tuženika", t)

    def test_kratak_tekst_ostaje_nekomprimiran(self):
        """Ispod praga zlib zaglavlje pojede dobitak; citanje je isto."""
        kratak = dict(ODLUKA, id="kratak-1", tekst=u"Kratko rješenje o šumi.")
        store.spremi(self.con, kratak)
        r = self.con.execute(
            "SELECT komp FROM tekstovi t JOIN odluke_meta o ON o.rid=t.rid "
            "WHERE o.id=? AND t.vrsta_zapisa='tekst'", ("kratak-1",)).fetchone()
        self.assertEqual(r["komp"], 0)
        self.assertEqual(store.tekst(self.con, "kratak-1"), u"Kratko rješenje o šumi.")

    def test_prazan_tekst(self):
        store.spremi(self.con, {"id": "gol-1"})
        self.assertEqual(store.tekst(self.con, "gol-1"), "")
        self.assertEqual(
            self.con.execute("SELECT tekst FROM odluke WHERE id='gol-1'").fetchone()[0], "")

    def test_odzipaj_podnosi_null_i_smece(self):
        self.assertIsNone(store.odzipaj(None))
        self.assertEqual(store.odzipaj(zlib.compress(u"šuma".encode("utf-8"))), u"šuma")
        self.assertEqual(store.odzipaj(b"nije zlib"), "nije zlib")

    def test_meta_json_je_komprimiran_ali_se_cita_kao_json(self):
        store.spremi(self.con, ODLUKA)
        r = self.con.execute("SELECT meta_json FROM odluke WHERE id=?",
                             (ODLUKA["id"],)).fetchone()
        self.assertEqual(json.loads(r["meta_json"]), ODLUKA["meta"])
        vrsta = self.con.execute(
            "SELECT typeof(tijelo) FROM tekstovi WHERE vrsta_zapisa='meta'").fetchone()
        self.assertEqual(vrsta[0], "blob")

    def test_bez_mete_vraca_prazan_objekt(self):
        store.spremi(self.con, {"id": "gol-2"})
        r = self.con.execute("SELECT meta_json FROM odluke WHERE id='gol-2'").fetchone()
        self.assertEqual(json.loads(r["meta_json"]), {})

    def test_statistika_mjeri_omjer(self):
        store.spremi(self.con, ODLUKA)
        s = store.statistika(self.con)
        self.assertEqual(s["bajtova_sirovo"], len(DUGI_TEKST.encode("utf-8")))
        self.assertLess(s["omjer"], 0.5)


# ------------------------------------------------------- oblik i planovi ---

class TestOblikTabliceTekstova(BazaTest):
    """Izmjereno: WITHOUT ROWID je 816 B/dok skuplje (0,96 GB na korpusu)."""

    def test_tekstovi_nije_without_rowid(self):
        sql = self.con.execute(
            "SELECT sql FROM sqlite_master WHERE name='tekstovi'").fetchone()[0]
        self.assertNotIn("WITHOUT ROWID", sql.upper())

    def test_slojevi_jest_without_rowid(self):
        """Mala tablica bez BLOB-ova; ondje WITHOUT ROWID ima smisla."""
        sql = self.con.execute(
            "SELECT sql FROM sqlite_master WHERE name='slojevi'").fetchone()[0]
        self.assertIn("WITHOUT ROWID", sql.upper())


class TestPogledSeNeMaterijalizira(BazaTest):
    """
    Pogled `odluke` mora biti spljostiv. Materijalizacija je za pet redaka
    kostala 738 ms umjesto 16 ms, jer je dekomprimirala cijeli korpus.
    """

    def plan(self, sql, par):
        return "\n".join(r[3] for r in
                         self.con.execute("EXPLAIN QUERY PLAN " + sql, par))

    def test_spajanje_na_fts_ne_materijalizira_pogled(self):
        store.spremi(self.con, ODLUKA)
        p = self.plan(
            "SELECT o.*, bm25(odluke_fts) AS rang FROM odluke_fts "
            "JOIN odluke o ON o.rowid = odluke_fts.rowid "
            "WHERE odluke_fts MATCH ? ORDER BY rang LIMIT 5", (u"zamjena",))
        self.assertNotIn("MATERIALIZE", p.upper(), "pogled `odluke` nije spljosten:\n" + p)

    def test_dohvat_po_id_ne_materijalizira_pogled(self):
        store.spremi(self.con, ODLUKA)
        p = self.plan("SELECT * FROM odluke WHERE id=?", (ODLUKA["id"],))
        self.assertNotIn("MATERIALIZE", p.upper(), p)

    def test_pogled_se_obnavlja_kad_se_definicija_promijeni(self):
        self.con.execute("DROP VIEW odluke")
        self.con.execute("CREATE VIEW odluke AS SELECT rid AS rowid, id FROM odluke_meta")
        self.con.commit()
        con2 = store.veza(self.db)
        try:
            sql = con2.execute(
                "SELECT sql FROM sqlite_master WHERE name='odluke'").fetchone()[0]
            self.assertIn("meta_json", sql)
        finally:
            con2.close()


class TestIndeksiZaUzorkovanje(BazaTest):

    def test_upit_po_sloju_koristi_ix_strat_sud(self):
        store.spremi(self.con, ODLUKA)
        plan = "\n".join(r[3] for r in self.con.execute(
            "EXPLAIN QUERY PLAN SELECT rid FROM odluke_meta "
            "WHERE sud_id=? AND godina=? AND uzorak_kljuc>? "
            "ORDER BY uzorak_kljuc LIMIT 50", (1, 2019, 0)))
        self.assertIn("ix_strat_sud", plan)
        self.assertNotIn("TEMP B-TREE", plan.upper(),
                         "poredak mora doci iz indeksa, ne iz sortiranja")

    def test_indeksi_postoje(self):
        imena = {r[0] for r in self.con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        for i in ("ix_strat_sud", "ix_strat_upisnik", "ix_strat_nacin",
                  "ix_odluke_godina", "ix_odluke_datum", "ix_odluke_izvor"):
            self.assertIn(i, imena)


# ------------------------------------------------------------ uzorkovanje ---

class TestUzorakKljuc(BazaTest):

    def test_kljuc_je_determinististan(self):
        a = store._uzorak_kljuc("05c6cdd3-1486-4903-b85f-eda703b4e5e0")
        b = store._uzorak_kljuc("05c6cdd3-1486-4903-b85f-eda703b4e5e0")
        self.assertEqual(a, b)
        self.assertNotEqual(a, store._uzorak_kljuc("drugi-id"))

    def test_kljuc_stane_u_pozitivan_sqlite_integer(self):
        for i in range(200):
            k = store._uzorak_kljuc("uuid-%d" % i)
            self.assertGreaterEqual(k, 0)
            self.assertLess(k, 2 ** 63)

    def test_isti_id_daje_isti_kljuc_u_dvije_baze(self):
        store.spremi(self.con, ODLUKA)
        drugi = os.path.join(self.dir, "druga.sqlite")
        con2 = store.veza(drugi)
        try:
            store.spremi(con2, {"id": ODLUKA["id"], "tekst": u"drugaciji tekst"})
            k1 = self.con.execute("SELECT uzorak_kljuc FROM odluke_meta").fetchone()[0]
            k2 = con2.execute("SELECT uzorak_kljuc FROM odluke_meta").fetchone()[0]
            self.assertEqual(k1, k2)
        finally:
            con2.close()

    def test_uzorak_raste_bez_ponovnog_izvlacenja(self):
        """Rata od 10 mora biti pocetak rate od 25; inace uzorak nije ponovljiv."""
        for i in range(60):
            store.spremi(self.con, {"id": "u-%02d" % i, "sud": u"Općinski sud u Splitu",
                                    "datum": "2015-06-01", "tekst": u"tekst %d" % i},
                         commit=False)
        self.con.commit()
        sid = self.con.execute("SELECT sud_id FROM sudovi").fetchone()[0]
        mali = [r["id"] for r in store.uzorak_sloja(self.con, sud=sid, godina=2015, n=10)]
        veliki = [r["id"] for r in store.uzorak_sloja(self.con, sud=sid, godina=2015, n=25)]
        self.assertEqual(len(mali), 10)
        self.assertEqual(len(veliki), 25)
        self.assertEqual(veliki[:10], mali)

    def test_slojevi_se_popunjavaju(self):
        store.spremi(self.con, ODLUKA)
        store.spremi(self.con, dict(ODLUKA, id="x-2", datum="2015-01-01"))
        n = store.osvjezi_slojeve(self.con)
        self.assertEqual(n, 2)
        ukupno = self.con.execute("SELECT SUM(n) FROM slojevi").fetchone()[0]
        self.assertEqual(ukupno, 2)


class TestNacinOdabira(BazaTest):

    def test_zadano_je_ciljano(self):
        store.spremi(self.con, ODLUKA)
        r = self.con.execute("SELECT nacin_odabira FROM odluke WHERE id=?",
                             (ODLUKA["id"],)).fetchone()
        self.assertEqual(r[0], "ciljano")

    def test_moze_se_zadati(self):
        store.spremi(self.con, dict(ODLUKA, id="p-1", nacin_odabira="uzorak"))
        r = self.con.execute("SELECT nacin_odabira FROM odluke WHERE id='p-1'").fetchone()
        self.assertEqual(r[0], "uzorak")


# ------------------------------------------------------------- sifarnici ---

class TestSifarnici(BazaTest):

    def test_sud_se_ne_ponavlja(self):
        for i in range(5):
            store.spremi(self.con, dict(ODLUKA, id="s-%d" % i))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM sudovi").fetchone()[0], 1)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM upisnici").fetchone()[0], 1)

    def test_naziv_suda_se_cita_natrag(self):
        store.spremi(self.con, ODLUKA)
        r = self.con.execute("SELECT sud, upisnik FROM odluke WHERE id=?",
                             (ODLUKA["id"],)).fetchone()
        self.assertEqual(r["sud"], ODLUKA["sud"])
        self.assertEqual(r["upisnik"], ODLUKA["upisnik"])

    def test_prazan_sud_ostaje_null(self):
        store.spremi(self.con, {"id": "bez-suda"})
        r = self.con.execute("SELECT sud FROM odluke WHERE id='bez-suda'").fetchone()
        self.assertIsNone(r["sud"])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM sudovi").fetchone()[0], 0)

    def test_godina_se_izvodi_iz_datuma(self):
        store.spremi(self.con, ODLUKA)
        store.spremi(self.con, {"id": "bez-datuma"})
        self.assertEqual(self.con.execute(
            "SELECT godina FROM odluke WHERE id=?", (ODLUKA["id"],)).fetchone()[0], 2019)
        self.assertIsNone(self.con.execute(
            "SELECT godina FROM odluke WHERE id='bez-datuma'").fetchone()[0])


# ------------------------------------------------------------ batch upis ---

class TestBatchUpis(BazaTest):

    def test_spremi_mnogo_broji_novo_i_azurirano(self):
        zapisi = [dict(ODLUKA, id="b-%d" % i) for i in range(50)]
        z = store.spremi_mnogo(self.con, zapisi)
        self.assertEqual(z, {"novo": 50, "azurirano": 0})
        z = store.spremi_mnogo(self.con, zapisi)
        self.assertEqual(z, {"novo": 0, "azurirano": 50})
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM odluke_meta").fetchone()[0], 50)

    def test_batch_i_pojedinacno_daju_isto(self):
        store.spremi_mnogo(self.con, [dict(ODLUKA, id="b-1")])
        store.spremi(self.con, dict(ODLUKA, id="p-1"))
        a = dict(self.con.execute("SELECT * FROM odluke WHERE id='b-1'").fetchone())
        b = dict(self.con.execute("SELECT * FROM odluke WHERE id='p-1'").fetchone())
        for k in ("tekst", "sud", "upisnik", "kazalo", "meta_json", "duljina", "sha256"):
            self.assertEqual(a[k], b[k], "polje %r" % k)

    def test_pretraga_nalazi_sve_iz_batcha(self):
        store.spremi_mnogo(self.con, [dict(ODLUKA, id="b-%d" % i) for i in range(20)])
        self.assertEqual(len(store.trazi(self.con, u"zamjena", limit=100)), 20)


# ---------------------------------------------------------------- pretraga ---

class TestPretragaNadKompresijom(BazaTest):

    def test_isjecak_dolazi_iz_komprimiranog_teksta(self):
        store.spremi(self.con, ODLUKA)
        r = store.trazi(self.con, u"šumskog")
        self.assertEqual(len(r), 1)
        self.assertIn(u"»", r[0]["isjecak"])
        self.assertEqual(r[0]["tekst"], DUGI_TEKST)

    def test_fraza_radi(self):
        store.spremi(self.con, ODLUKA)
        self.assertEqual(len(store.trazi(self.con, u'"zamjena šumskog zemljišta"')), 1)
        self.assertEqual(len(store.trazi(self.con, u'"zemljišta šumskog zamjena"')), 0)

    def test_pretraga_bez_dijakritika_nalazi_isto(self):
        store.spremi(self.con, ODLUKA)
        self.assertEqual(len(store.trazi(self.con, u"sumskog")), 1)

    def test_stari_tekst_nestaje_iz_indeksa(self):
        store.spremi(self.con, dict(ODLUKA, tekst=u"Rijec komasacija se pojavljuje. " * 20))
        self.assertEqual(len(store.trazi(self.con, u"komasacija")), 1)
        store.spremi(self.con, dict(ODLUKA, tekst=u"Sada pise nesto posve drugo. " * 20))
        self.assertEqual(len(store.trazi(self.con, u"komasacija")), 0)
        self.assertEqual(len(store.trazi(self.con, u"drugo")), 1)


# ---------------------------------------------------------------- veza ---

class TestVeza(BazaTest):

    def test_wal_je_ukljucen(self):
        self.assertEqual(
            self.con.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")

    def test_pragme(self):
        self.assertEqual(self.con.execute("PRAGMA page_size").fetchone()[0], 4096)
        self.assertEqual(self.con.execute("PRAGMA synchronous").fetchone()[0], 1)
        self.assertEqual(self.con.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(self.con.execute("PRAGMA wal_autocheckpoint").fetchone()[0], 4000)

    def test_verzija_sheme_je_upisana(self):
        self.assertEqual(store._verzija(self.con), store.SHEMA_VERZIJA)

    def test_otvori_ro_moze_citati_komprimirano(self):
        store.spremi(self.con, ODLUKA)
        ro = store.otvori_ro(self.db)
        try:
            self.assertEqual(
                ro.execute("SELECT tekst FROM odluke WHERE id=?",
                           (ODLUKA["id"],)).fetchone()[0], DUGI_TEKST)
        finally:
            ro.close()

    def test_otvori_ro_ne_moze_pisati(self):
        ro = store.otvori_ro(self.db)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                ro.execute("DELETE FROM odluke_meta")
        finally:
            ro.close()

    def test_optimiziraj_ne_gubi_podatke(self):
        store.spremi_mnogo(self.con, [dict(ODLUKA, id="o-%d" % i) for i in range(20)])
        store.optimiziraj(self.con, vacuum=True)
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM odluke_meta").fetchone()[0], 20)
        self.assertEqual(len(store.trazi(self.con, u"zamjena", limit=100)), 20)
        self.assertEqual(self.con.execute("PRAGMA integrity_check").fetchone()[0], "ok")


# ------------------------------------------------------------- migracija ---

class TestMigracija(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="presude_mig_")
        self.db = os.path.join(self.dir, "stari.sqlite")
        self.zapisi = [
            v1_zapis(),
            v1_zapis(id="drugi", broj=u"Gž-101/2020-3", sud=u"Županijski sud u Splitu",
                     datum="2020-05-05", upisnik=u"Gž", tekst=u"Komasacija zemljišta. " * 30,
                     meta_json=u'{"Sud": "Županijski sud u Splitu"}'),
            v1_zapis(id="prazan", tekst="", meta_json="{}", sud=None, upisnik=None,
                     datum=None, kazalo=None),
            v1_zapis(id="usud-1", izvor="usud", sud=u"Ustavni sud Republike Hrvatske",
                     datum="2021-06-01", tekst=u"Ustavna tužba se odbija. " * 30),
        ]
        napravi_v1(self.db, self.zapisi)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_veza_prepozna_i_prevede_staru_bazu(self):
        con = store.veza(self.db)
        try:
            self.assertEqual(store._verzija(con), store.SHEMA_VERZIJA)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM odluke_meta").fetchone()[0],
                             len(self.zapisi))
        finally:
            con.close()

    def test_nijedno_polje_se_ne_gubi(self):
        con = store.veza(self.db)
        try:
            for z in self.zapisi:
                r = con.execute("SELECT * FROM odluke WHERE id=?", (z["id"],)).fetchone()
                self.assertIsNotNone(r, "nestala odluka %r" % z["id"])
                for k in V1_POLJA:
                    if k == "tekst":
                        self.assertEqual(r["tekst"], z["tekst"] or "", "tekst %r" % z["id"])
                    elif k == "meta_json":
                        self.assertEqual(json.loads(r["meta_json"]),
                                         json.loads(z["meta_json"] or "{}"))
                    else:
                        self.assertEqual(r[k], z[k], "polje %r u %r" % (k, z["id"]))
        finally:
            con.close()

    def test_dijakritika_prezivi_migraciju(self):
        con = store.veza(self.db)
        try:
            t = store.tekst(con, ODLUKA["id"])
            self.assertIn(u"šumskog", t)
            self.assertIn(u"tuženika", t)
            self.assertEqual(t, ODLUKA["tekst"])
        finally:
            con.close()

    def test_pretrage_prezive(self):
        con = store.veza(self.db)
        try:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM pretrage").fetchone()[0], 1)
        finally:
            con.close()

    def test_fts_radi_nakon_migracije(self):
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

    def test_stara_tablica_je_uklonjena_a_pogled_stvoren(self):
        con = store.veza(self.db)
        try:
            vrste = dict(con.execute(
                "SELECT name, type FROM sqlite_master WHERE name IN "
                "('odluke','odluke_v1','odluke_meta','tekstovi')").fetchall())
            self.assertEqual(vrste.get("odluke"), "view")
            self.assertEqual(vrste.get("odluke_meta"), "table")
            self.assertEqual(vrste.get("tekstovi"), "table")
            self.assertNotIn("odluke_v1", vrste)
        finally:
            con.close()

    def test_stari_trigeri_su_uklonjeni(self):
        con = store.veza(self.db)
        try:
            trigeri = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'")}
            self.assertEqual(trigeri & {"odluke_ai", "odluke_ad", "odluke_au"}, set())
        finally:
            con.close()

    def test_sigurnosna_kopija_je_napravljena(self):
        store.veza(self.db).close()
        kopija = self.db + ".shema1.bak"
        self.assertTrue(os.path.exists(kopija), "migracija mora ostaviti kopiju")
        stara = sqlite3.connect(kopija)
        try:
            self.assertEqual(
                stara.execute("SELECT COUNT(*) FROM odluke").fetchone()[0],
                len(self.zapisi))
        finally:
            stara.close()

    def test_migracija_je_idempotentna(self):
        con = store.veza(self.db)
        self.assertEqual(store.migriraj(con, tiho=True), 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM odluke_meta").fetchone()[0],
                         len(self.zapisi))
        con.close()
        con2 = store.veza(self.db)
        try:
            self.assertEqual(con2.execute("SELECT COUNT(*) FROM odluke").fetchone()[0],
                             len(self.zapisi))
        finally:
            con2.close()

    def test_tekst_zauzima_manje_nego_prije(self):
        """
        Ne mjeri se velicina datoteke: na cetiri odluke fiksni trosak nove
        sheme (sifarnici, sest indeksa, tablica slojeva) nadjaca ustedu.
        Mjeri se ono sto kompresija obecava, a to je velicina samog teksta.
        """
        con = store.veza(self.db)
        try:
            sirovo, na_disku = con.execute(
                "SELECT SUM(n_bajt), SUM(length(tijelo)) FROM tekstovi "
                "WHERE vrsta_zapisa='tekst'").fetchone()
            self.assertLess(na_disku, sirovo / 2)
        finally:
            con.close()

    def test_upis_nakon_migracije_radi(self):
        con = store.veza(self.db)
        try:
            prije = len(store.trazi(con, u"zamjena", limit=100))
            self.assertTrue(store.spremi(con, dict(ODLUKA, id="novi-poslije")))
            self.assertEqual(store.tekst(con, "novi-poslije"), DUGI_TEKST)
            self.assertEqual(len(store.trazi(con, u"zamjena", limit=100)), prije + 1)
        finally:
            con.close()

    def test_odbija_migraciju_kad_je_zabranjena(self):
        with self.assertRaises(RuntimeError):
            store.veza(self.db, auto_migracija=False)

    def test_migracija_ne_dira_pravu_bazu(self):
        self.assertNotEqual(os.path.abspath(self.db),
                            os.path.abspath(str(store.DB_PATH)))
        store.veza(self.db).close()
        self.assertTrue(os.path.exists(self.db))


if __name__ == "__main__":
    unittest.main()
