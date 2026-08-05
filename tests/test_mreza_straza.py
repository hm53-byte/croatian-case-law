# -*- coding: utf-8 -*-
"""
Provjera same straze: ako ona zakaze, ostali testovi mogu neopazice
otici na javni portal. Zato se ovdje testira i alat, ne samo kod.
"""
import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mreza_straza  # noqa: E402


class TestStrazaJeAktivna(unittest.TestCase):

    def test_create_connection_je_zabranjen(self):
        with self.assertRaises(mreza_straza.MreznaZabrana):
            socket.create_connection(("odluke.sudovi.hr", 443), 1)

    def test_dns_upit_je_zabranjen(self):
        with self.assertRaises(mreza_straza.MreznaZabrana):
            socket.getaddrinfo("odluke.sudovi.hr", 443)

    def test_connect_na_socketu_je_zabranjen(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with self.assertRaises(mreza_straza.MreznaZabrana):
                s.connect(("93.184.216.34", 80))
        finally:
            s.close()

    def test_requests_sesija_ne_moze_van(self):
        """Sesija iz common.py pada odmah, prije ijednog paketa na mrezi."""
        import common
        with self.assertRaises(mreza_straza.MreznaZabrana):
            common.session.get("https://odluke.sudovi.hr/", timeout=2)

    def test_rate_limit_je_pristojan(self):
        """Politika prema javnim portalima: najmanje 1,5 s izmedu zahtjeva."""
        import common
        self.assertGreaterEqual(common.RATE_LIMIT_S, 1.5)

    def test_postavi_je_idempotentna(self):
        mreza_straza.postavi()
        mreza_straza.postavi()
        self.assertTrue(getattr(socket.getaddrinfo, "je_straza", False))


class TestPutanje(unittest.TestCase):

    def test_scrapers_je_na_sys_path(self):
        self.assertIn(mreza_straza.SCRAPERS_DIR, sys.path)

    def test_uzorak_postoji(self):
        self.assertTrue(os.path.exists(
            mreza_straza.uzorak("rezultati_pretrage.html")))


if __name__ == "__main__":
    unittest.main()
