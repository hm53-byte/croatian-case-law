# -*- coding: utf-8 -*-
"""
Tvrda zapreka u common.py: hostovi ciji robots.txt glasi 'Disallow: /'
(odluke.sudovi.hr, sljeme.usud.hr) ne smiju se dohvacati bez oznake pisanog
dopustenja izvora. Zapreka mora pasti PRIJE ijednog mreznog zahtjeva, s
izlaznim kodom 3, i ne smije dirati citanje vec keširanih odgovora s diska.

Nijedan test ne otvara mrezu; mreza_straza to i onemogucava, ali zapreka
mora pasti prije nje (SystemExit, ne MreznaZabrana).
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mreza_straza  # noqa: E402  postavlja putanje i zabranjuje mrezu

import common  # noqa: E402


class Baza(unittest.TestCase):
    """Cuva i vraca stanje dopustenja, da testovi ne cure jedan u drugi."""

    def setUp(self):
        self._dopustenje = common.DOPUSTENJE
        self._zabiljezeno = common._dopustenje_zabiljezeno
        common.DOPUSTENJE = ""
        common._dopustenje_zabiljezeno = False

    def tearDown(self):
        common.DOPUSTENJE = self._dopustenje
        common._dopustenje_zabiljezeno = self._zabiljezeno


class TestZapreka(Baza):

    def _ocekuj_zapreku(self, poziv):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as cm:
                poziv()
        self.assertEqual(cm.exception.code, 3)
        self.assertIn("robots.txt", stderr.getvalue())

    def test_get_na_zabranjenu_rutu_pada_kodom_3(self):
        self._ocekuj_zapreku(lambda: common.get(
            "https://odluke.sudovi.hr/Document/DisplayList",
            params={"q": "x"}, cache=False))

    def test_get_bytes_na_pdf_rutu_pada_kodom_3(self):
        self._ocekuj_zapreku(lambda: common.get_bytes(
            "https://odluke.sudovi.hr/Document/DownloadPDF?id=x"))

    def test_post_na_usud_pada_kodom_3(self):
        self._ocekuj_zapreku(lambda: common.post(
            "https://sljeme.usud.hr/usud/praksaw.nsf/vSignaturaPoGodiniZap.xsp"))

    def test_usud_nema_nijednu_dopustenu_rutu_osim_robots(self):
        self._ocekuj_zapreku(lambda: common.zapreka_robots(
            "https://sljeme.usud.hr/"))
        common.zapreka_robots("https://sljeme.usud.hr/robots.txt")  # ne dize

    def test_informativne_rute_odluke_prolaze(self):
        # Tocno one rute koje robots.txt izrijekom dopusta.
        for putanja in ("/", "/robots.txt", "/Home/Privacy", "/Home/About",
                        "/Home/Cookies", "/Home/Accessibility",
                        "/Home/UserManual"):
            common.zapreka_robots("https://odluke.sudovi.hr" + putanja)

    def test_ostali_hostovi_prolaze(self):
        common.zapreka_robots("https://narodne-novine.nn.hr/eli/sluzbeni/2018")
        common.zapreka_robots("https://hrcak.srce.hr/oai")

    def test_dopustenje_otvara_zapreku(self):
        common.DOPUSTENJE = "KLASA-000/00-00/00"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            common.zapreka_robots(
                "https://odluke.sudovi.hr/Document/View?id=x")
        self.assertIn("KLASA-000/00-00/00", stdout.getvalue())


class TestKesiranoProlazi(Baza):
    """Citanje vec keširanog odgovora nije mrezni zahtjev i ne prolazi zapreku."""

    def setUp(self):
        super(TestKesiranoProlazi, self).setUp()
        self._cache_dir = common.CACHE_DIR
        common.CACHE_DIR = type(common.CACHE_DIR)(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(str(common.CACHE_DIR), ignore_errors=True)
        common.CACHE_DIR = self._cache_dir
        super(TestKesiranoProlazi, self).tearDown()

    def test_kes_se_cita_bez_zapreke(self):
        url = "https://odluke.sudovi.hr/Document/View"
        params = {"id": "test"}
        putanja = common._cache_path(url, params)
        putanja.write_text("<html>keširano</html>", encoding="utf-8")
        self.assertEqual(common.get(url, params=params), "<html>keširano</html>")


if __name__ == "__main__":
    unittest.main()
