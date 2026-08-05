# -*- coding: utf-8 -*-
"""
store: lokalni korpus u SQLite-u. Sve se vrti nad privremenom bazom
(tempfile), stvarni data/corpus.sqlite se ne dira.

Najvaznije svojstvo: crawl je inkrementalan, pa ponovno spremanje iste
odluke ne smije stvoriti duplikat.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mreza_straza  # noqa: E402,F401  postavlja putanje i zabranjuje mrezu

import store  # noqa: E402

ODLUKA = {
    "id": "05c6cdd3-1486-4903-b85f-eda703b4e5e0",
    "izvor": "anon",
    "url": "https://odluke.sudovi.hr/Document/View?id=05c6cdd3-1486-4903-b85f-eda703b4e5e0",
    "broj": "Rev-533/2015-2",
    "sud": u"Vrhovni sud Republike Hrvatske",
    "datum": "2019-02-22",
    "vrsta": "presuda",
    "upisnik": "Rev",
    "ecli": "ECLI:HR:VSRH:2019:533",
    "pravomocnost": u"pravomoćna",
    "kazalo": u"stvarna prava > zamjena nekretnina",
    "propisi": u"Zakon o šumama, čl. 55.",
    "tekst": u"Odbija se revizija tuženika. Obrazloženje: zamjena šumskog "
             u"zemljišta na temelju članka 55. Zakona o šumama.",
    "meta": {"Broj odluke": "Rev-533/2015-2", "Sud": u"Vrhovni sud Republike Hrvatske"},
}


class BazaTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="presude_test_")
        self.db = os.path.join(self.dir, "corpus_test.sqlite")
        self.con = store.veza(self.db)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def broj_zapisa(self):
        return self.con.execute("SELECT COUNT(*) FROM odluke").fetchone()[0]

    def dohvati(self, doc_id):
        return self.con.execute("SELECT * FROM odluke WHERE id=?", (doc_id,)).fetchone()


class TestShema(BazaTest):

    def test_baza_je_stvorena_na_zadanoj_putanji(self):
        self.assertTrue(os.path.exists(self.db))

    def test_prava_baza_nije_dirana(self):
        self.assertNotEqual(os.path.abspath(self.db),
                            os.path.abspath(str(store.DB_PATH)))

    def test_tablice_postoje(self):
        imena = {r[0] for r in self.con.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        self.assertIn("odluke", imena)
        self.assertIn("pretrage", imena)

    def test_prazna_baza(self):
        self.assertEqual(self.broj_zapisa(), 0)
        self.assertFalse(store.ima(self.con, ODLUKA["id"]))

    def test_ponovno_otvaranje_ne_ruse_sheme(self):
        con2 = store.veza(self.db)
        con2.close()
        self.assertEqual(self.broj_zapisa(), 0)


class TestSpremiIProcitaj(BazaTest):

    def test_spremanje_vraca_true_za_novu_odluku(self):
        self.assertTrue(store.spremi(self.con, ODLUKA))
        self.assertEqual(self.broj_zapisa(), 1)

    def test_procitani_zapis_je_isti(self):
        store.spremi(self.con, ODLUKA)
        r = self.dohvati(ODLUKA["id"])
        self.assertIsNotNone(r)
        for kljuc in ("izvor", "url", "broj", "sud", "datum", "vrsta",
                      "upisnik", "ecli", "pravomocnost", "kazalo",
                      "propisi", "tekst"):
            self.assertEqual(r[kljuc], ODLUKA[kljuc], "polje %r" % kljuc)

    def test_meta_je_spremljena_kao_json(self):
        store.spremi(self.con, ODLUKA)
        r = self.dohvati(ODLUKA["id"])
        self.assertEqual(json.loads(r["meta_json"]), ODLUKA["meta"])

    def test_dijakritika_prezivljava_zapis(self):
        store.spremi(self.con, ODLUKA)
        r = self.dohvati(ODLUKA["id"])
        self.assertIn(u"šumskog", r["tekst"])
        self.assertIn(u"tuženika", r["tekst"])

    def test_ima_prepoznaje_spremljenu_odluku(self):
        self.assertFalse(store.ima(self.con, ODLUKA["id"]))
        store.spremi(self.con, ODLUKA)
        self.assertTrue(store.ima(self.con, ODLUKA["id"]))
        self.assertFalse(store.ima(self.con, "nepostojeci-id"))

    def test_minimalan_zapis(self):
        """Nedostajuca polja ne smiju rusiti spremanje."""
        self.assertTrue(store.spremi(self.con, {"id": "gol-1"}))
        r = self.dohvati("gol-1")
        self.assertEqual(r["tekst"], "")
        self.assertEqual(r["izvor"], "anon")

    def test_dohvaceno_je_popunjeno(self):
        store.spremi(self.con, ODLUKA)
        self.assertTrue(self.dohvati(ODLUKA["id"])["dohvaceno"])


class TestBezDuplikata(BazaTest):

    def test_ponovno_spremanje_ne_stvara_duplikat(self):
        self.assertTrue(store.spremi(self.con, ODLUKA))
        self.assertFalse(store.spremi(self.con, ODLUKA))
        self.assertFalse(store.spremi(self.con, ODLUKA))
        self.assertEqual(self.broj_zapisa(), 1)

    def test_broj_redaka_s_tim_id_em_je_jedan(self):
        for _ in range(5):
            store.spremi(self.con, ODLUKA)
        n = self.con.execute("SELECT COUNT(*) FROM odluke WHERE id=?",
                             (ODLUKA["id"],)).fetchone()[0]
        self.assertEqual(n, 1)

    def test_ponovno_spremanje_osvjezava_tekst(self):
        store.spremi(self.con, ODLUKA)
        novi = dict(ODLUKA)
        novi["tekst"] = u"Dopunjeni puni tekst odluke."
        novi["kazalo"] = u"novo kazalo"
        novi["propisi"] = u"Zakon o šumama, čl. 55. i 56."
        store.spremi(self.con, novi)
        r = self.dohvati(ODLUKA["id"])
        self.assertEqual(r["tekst"], u"Dopunjeni puni tekst odluke.")
        self.assertEqual(r["kazalo"], u"novo kazalo")
        self.assertEqual(r["propisi"], u"Zakon o šumama, čl. 55. i 56.")
        self.assertEqual(self.broj_zapisa(), 1)

    def test_upsert_zadrzava_izvorne_metapodatke(self):
        """
        Dokumentira stvarno ponasanje: ON CONFLICT osvjezava samo tekst,
        kazalo, propise i meta_json. Broj, sud, datum, vrsta, upisnik, ECLI
        i pravomocnost ostaju onakvi kakvi su prvi put upisani.
        """
        store.spremi(self.con, ODLUKA)
        drugi = dict(ODLUKA)
        drugi["broj"] = "PROMIJENJENO"
        drugi["sud"] = "Drugi sud"
        drugi["datum"] = "2020-01-01"
        store.spremi(self.con, drugi)
        r = self.dohvati(ODLUKA["id"])
        self.assertEqual(r["broj"], "Rev-533/2015-2")
        self.assertEqual(r["sud"], u"Vrhovni sud Republike Hrvatske")
        self.assertEqual(r["datum"], "2019-02-22")

    def test_razliciti_id_je_novi_zapis(self):
        store.spremi(self.con, ODLUKA)
        drugi = dict(ODLUKA)
        drugi["id"] = "aaaabbbb-cccc-4ddd-8eee-ffff00001111"
        drugi["broj"] = u"Gž-101/2020-3"
        self.assertTrue(store.spremi(self.con, drugi))
        self.assertEqual(self.broj_zapisa(), 2)


class TestPretragaKorpusa(BazaTest):

    def test_trazi_nalazi_spremljenu_odluku(self):
        store.spremi(self.con, ODLUKA)
        redovi = store.trazi(self.con, u"zamjena")
        self.assertEqual(len(redovi), 1)
        self.assertEqual(redovi[0]["id"], ODLUKA["id"])

    def test_trazi_bez_pogodaka(self):
        store.spremi(self.con, ODLUKA)
        self.assertEqual(store.trazi(self.con, u"pomorskodobro"), [])

    def test_pretraga_ne_vraca_duplikate_nakon_ponovnog_spremanja(self):
        for _ in range(3):
            store.spremi(self.con, ODLUKA)
        redovi = store.trazi(self.con, u"zamjena")
        self.assertEqual(len(redovi), 1)


class TestEvidencijaPretraga(BazaTest):

    def test_zabiljezi_pretragu(self):
        store.zabiljezi_pretragu(self.con, u"zamjena šuma", "anon", 1, 42)
        r = self.con.execute("SELECT * FROM pretrage").fetchone()
        self.assertEqual(r["upit"], u"zamjena šuma")
        self.assertEqual(r["izvor"], "anon")
        self.assertEqual(r["pogodaka"], 42)

    def test_ista_pretraga_se_prepisuje(self):
        store.zabiljezi_pretragu(self.con, u"zamjena", "anon", 1, 10)
        store.zabiljezi_pretragu(self.con, u"zamjena", "anon", 1, 20)
        n = self.con.execute("SELECT COUNT(*) FROM pretrage").fetchone()[0]
        self.assertEqual(n, 1)
        self.assertEqual(
            self.con.execute("SELECT pogodaka FROM pretrage").fetchone()[0], 20)


class TestStatistika(BazaTest):

    def test_prazna_baza(self):
        s = store.statistika(self.con)
        self.assertEqual(s["ukupno"], 0)
        self.assertEqual(s["po_izvoru"], {})

    def test_zbroj_po_izvoru_i_raspon_datuma(self):
        store.spremi(self.con, ODLUKA)
        drugi = dict(ODLUKA)
        drugi["id"] = "usud-1"
        drugi["izvor"] = "usud"
        drugi["datum"] = "2021-06-01"
        store.spremi(self.con, drugi)
        s = store.statistika(self.con)
        self.assertEqual(s["ukupno"], 2)
        self.assertEqual(s["po_izvoru"], {"anon": 1, "usud": 1})
        self.assertEqual(tuple(s["raspon"]), ("2019-02-22", "2021-06-01"))


if __name__ == "__main__":
    unittest.main()
