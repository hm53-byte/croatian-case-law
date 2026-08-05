# -*- coding: utf-8 -*-
"""
anon._iso_datum: normalizacija hrvatskih datuma u ISO oblik.

Portal ispisuje datume u dva oblika: brojcanom ('22.2.2019.') i slovnom
('16. listopada 2018.'). Baza trazi 'YYYY-MM-DD', inace sortiranje i
raspon datuma u statistici ne rade.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mreza_straza  # noqa: E402,F401  postavlja putanje i zabranjuje mrezu

import anon  # noqa: E402


class TestBrojcaniOblik(unittest.TestCase):

    def test_primjer_iz_dokumentacije(self):
        self.assertEqual(anon._iso_datum("22.2.2019."), "2019-02-22")

    def test_nadopuna_vodecih_nula(self):
        self.assertEqual(anon._iso_datum("1.1.2020."), "2020-01-01")
        self.assertEqual(anon._iso_datum("5.9.2003."), "2003-09-05")

    def test_dvoznamenkasti_dan_i_mjesec(self):
        self.assertEqual(anon._iso_datum("31.12.1999."), "1999-12-31")

    def test_bez_zavrsne_tocke(self):
        self.assertEqual(anon._iso_datum("22.2.2019"), "2019-02-22")

    def test_razmaci_oko_tocaka(self):
        self.assertEqual(anon._iso_datum("22. 2. 2019."), "2019-02-22")

    def test_okolni_tekst_se_ignorira(self):
        self.assertEqual(
            anon._iso_datum("Datum odluke: 22.2.2019. godine"), "2019-02-22")


class TestSlovniOblik(unittest.TestCase):

    def test_primjer_iz_dokumentacije(self):
        self.assertEqual(anon._iso_datum("16. listopada 2018."), "2018-10-16")

    def test_svi_mjeseci(self):
        ocekivano = {
            "siječnja": "01", "veljače": "02", "ožujka": "03", "travnja": "04",
            "svibnja": "05", "lipnja": "06", "srpnja": "07", "kolovoza": "08",
            "rujna": "09", "listopada": "10", "studenoga": "11", "prosinca": "12",
        }
        for mjesec, broj in ocekivano.items():
            self.assertEqual(
                anon._iso_datum("7. %s 2021." % mjesec), "2021-%s-07" % broj,
                "mjesec %r nije prepoznat" % mjesec)

    def test_inacica_studenog(self):
        self.assertEqual(anon._iso_datum("30. studenog 2021."), "2021-11-30")

    def test_velika_slova(self):
        self.assertEqual(anon._iso_datum("16. LISTOPADA 2018."), "2018-10-16")

    def test_bez_razmaka_iza_tocke(self):
        self.assertEqual(anon._iso_datum("16.listopada 2018."), "2018-10-16")


class TestNeispravanUlaz(unittest.TestCase):

    def test_prazan_niz(self):
        self.assertEqual(anon._iso_datum(""), "")

    def test_none(self):
        self.assertEqual(anon._iso_datum(None), "")

    def test_samo_razmaci(self):
        self.assertEqual(anon._iso_datum("   \n\t "), "")

    def test_tekst_bez_datuma(self):
        for s in ("nepoznato", "n/a", "-", "bez datuma", "Datum odluke:"):
            self.assertEqual(anon._iso_datum(s), "", "ulaz %r" % s)

    def test_nepoznat_naziv_mjeseca(self):
        self.assertEqual(anon._iso_datum("16. octobra 2018."), "")
        self.assertEqual(anon._iso_datum("16. sijecnja 2018."), "")

    def test_nepotpun_datum(self):
        self.assertEqual(anon._iso_datum("22.2."), "")
        self.assertEqual(anon._iso_datum("2019."), "")

    def test_izlaz_je_uvijek_niz(self):
        for ulaz in (None, "", "22.2.2019.", "16. listopada 2018.", "smece"):
            self.assertIsInstance(anon._iso_datum(ulaz), str)


if __name__ == "__main__":
    unittest.main()
