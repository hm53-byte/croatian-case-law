# -*- coding: utf-8 -*-
"""
anon.search: parsiranje HTML-a rezultata pretrage, bez mreze.

Umjesto stvarnog zahtjeva prema odluke.sudovi.hr podmecemo spremljeni
uzorak iz tests/podaci/rezultati_pretrage.html. Uzorak oponasa markup
portala: a.search-result, .decision-number, .decision-court,
.decision-date, .final-decision, .result-snippet, .number-of-rslts.
"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mreza_straza  # noqa: E402  postavlja putanje i zabranjuje mrezu

import anon  # noqa: E402

UZORAK = mreza_straza.uzorak("rezultati_pretrage.html")


def ucitaj_uzorak():
    with io.open(UZORAK, encoding="utf-8") as f:
        return f.read()


class LazniGet(object):
    """Biljezi pozive i vraca spremljeni HTML umjesto mreznog odgovora."""

    def __init__(self, html):
        self.html = html
        self.pozivi = []

    def __call__(self, url, params=None, cache=True, timeout=45):
        self.pozivi.append({"url": url, "params": params, "cache": cache})
        return self.html


class BazaZaSearch(unittest.TestCase):

    def setUp(self):
        self.lazni = LazniGet(ucitaj_uzorak())
        self._pravi_get = anon.get
        anon.get = self.lazni

    def tearDown(self):
        anon.get = self._pravi_get


class TestParsiranjeRezultata(BazaZaSearch):

    def test_ne_dira_mrezu(self):
        anon.search("zamjena šumskog zemljišta")
        self.assertEqual(len(self.lazni.pozivi), 1)
        self.assertEqual(self.lazni.pozivi[0]["url"], anon.SEARCH_URL)

    def test_broj_rezultata(self):
        r = anon.search("zamjena šumskog zemljišta")
        self.assertEqual(r["ukupno"], 1234)

    def test_broj_izvucenih_pogodaka(self):
        """Tri valjana pogotka; unos bez id-a i navigacija se preskacu."""
        r = anon.search("zamjena")
        self.assertEqual(len(r["rezultati"]), 3)
        for stavka in r["rezultati"]:
            self.assertNotEqual(stavka["id"], "")
            self.assertNotIn("Nepotpun", stavka["broj"])

    def test_prvi_pogodak_u_cijelosti(self):
        r = anon.search("zamjena")
        prvi = r["rezultati"][0]
        self.assertEqual(prvi["id"], "05c6cdd3-1486-4903-b85f-eda703b4e5e0")
        self.assertEqual(prvi["broj"], "Rev-533/2015-2")
        self.assertEqual(prvi["sud"], "Vrhovni sud Republike Hrvatske")
        self.assertEqual(prvi["datum_prikaz"], "22.2.2019.")
        self.assertEqual(prvi["datum"], "2019-02-22")
        self.assertEqual(prvi["pravomocnost"], "pravomoćna")
        self.assertIn("okrupnjivanja", prvi["isjecak"])

    def test_slovni_datum_u_rezultatu(self):
        r = anon.search("zamjena")
        drugi = r["rezultati"][1]
        self.assertEqual(drugi["broj"], "Usoz-14/2018-7")
        self.assertEqual(drugi["sud"], "Visoki upravni sud Republike Hrvatske")
        self.assertEqual(drugi["datum_prikaz"], "16. listopada 2018.")
        self.assertEqual(drugi["datum"], "2018-10-16")
        self.assertEqual(drugi["pravomocnost"], "nije pravomoćna")

    def test_id_se_izvlaci_i_kad_href_ima_vise_parametara(self):
        r = anon.search("zamjena")
        self.assertEqual(r["rezultati"][1]["id"],
                         "7f1a2b3c-0000-4aaa-9bbb-ccddeeff0011")

    def test_apsolutni_url(self):
        r = anon.search("zamjena")
        for stavka in r["rezultati"]:
            self.assertTrue(stavka["url"].startswith(anon.BASE + "/Document/View"))
            self.assertIn(stavka["id"], stavka["url"])

    def test_treci_pogodak(self):
        r = anon.search("zamjena")
        treci = r["rezultati"][2]
        self.assertEqual(treci["id"], "aaaabbbb-cccc-4ddd-8eee-ffff00001111")
        self.assertEqual(treci["broj"], "Gž-101/2020-3")
        self.assertEqual(treci["sud"], "Županijski sud u Zagrebu")
        self.assertEqual(treci["datum"], "2020-09-03")

    def test_isjecak_je_splostena_jedna_linija(self):
        r = anon.search("zamjena")
        isjecak = r["rezultati"][0]["isjecak"]
        self.assertNotIn("\n", isjecak)
        self.assertNotIn("  ", isjecak)
        self.assertEqual(isjecak, isjecak.strip())

    def test_svi_kljucevi_prisutni(self):
        r = anon.search("zamjena")
        ocekivani = {"id", "url", "broj", "sud", "datum_prikaz", "datum",
                     "pravomocnost", "isjecak"}
        for stavka in r["rezultati"]:
            self.assertEqual(set(stavka.keys()), ocekivani)


class TestParametriUpita(BazaZaSearch):

    def test_osnovni_parametri(self):
        anon.search("zamjena šuma", page=3)
        p = self.lazni.pozivi[0]["params"]
        self.assertEqual(p["q"], "zamjena šuma")
        self.assertEqual(p["page"], 3)
        self.assertNotIn("sk", p)
        self.assertNotIn("zk", p)
        self.assertNotIn("prm", p)

    def test_filtri(self):
        anon.search("zamjena", sk="ŠUME", zk="Zakon o šumama",
                    samo_pravomocne=True)
        p = self.lazni.pozivi[0]["params"]
        self.assertEqual(p["sk"], "ŠUME")
        self.assertEqual(p["zk"], "Zakon o šumama")
        self.assertEqual(p["prm"], "pravomocna")

    def test_cache_se_prosljeduje(self):
        anon.search("zamjena", cache=False)
        self.assertIs(self.lazni.pozivi[0]["cache"], False)


class TestPrazniRezultati(unittest.TestCase):

    def setUp(self):
        self._pravi_get = anon.get

    def tearDown(self):
        anon.get = self._pravi_get

    def test_stranica_bez_pogodaka(self):
        anon.get = LazniGet(
            u"<html><body><div class='number-of-rslts'>0 rezultata</div>"
            u"<div class='results'></div></body></html>")
        r = anon.search("nepostojeci pojam")
        self.assertEqual(r["ukupno"], 0)
        self.assertEqual(r["rezultati"], [])

    def test_stranica_bez_brojaca(self):
        anon.get = LazniGet(u"<html><body><div class='results'></div></body></html>")
        r = anon.search("bilo sto")
        self.assertEqual(r["ukupno"], 0)
        self.assertEqual(r["rezultati"], [])


class TestSearchAll(BazaZaSearch):

    def test_postuje_max_rezultata(self):
        """Generator staje na zadanom broju i ne trazi nove stranice."""
        stavke = list(anon.search_all("zamjena", max_rezultata=2))
        self.assertEqual(len(stavke), 2)
        self.assertEqual(len(self.lazni.pozivi), 1)

    def test_staje_kad_je_dosegnut_ukupan_broj(self):
        stavke = list(anon.search_all("zamjena", max_rezultata=3))
        self.assertEqual(len(stavke), 3)
        self.assertEqual(len(self.lazni.pozivi), 1)


if __name__ == "__main__":
    unittest.main()
