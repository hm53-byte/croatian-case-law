# -*- coding: utf-8 -*-
"""
vektor.cankiraj: lomljenje presude na cankove.

Kljucno svojstvo koje se ovdje stiti: nijedan cank ne smije preci
MAX_ZNAKOVA (1600), jer bi ga e5-small model tiho odrezao i dio
obrazlozenja nikad ne bi zavrsio u indeksu.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mreza_straza  # noqa: E402,F401  postavlja putanje i zabranjuje mrezu

import vektor  # noqa: E402


def tocka(broj, znak, duljina):
    """Numerirana tocka obrazlozenja zadane duljine."""
    glava = "%d. " % broj
    return glava + znak * max(0, duljina - len(glava))


class TestGranice(unittest.TestCase):
    """Tvrda granica od 1600 znakova."""

    def _provjeri_granicu(self, cankovi):
        for i, c in enumerate(cankovi):
            self.assertLessEqual(
                len(c), vektor.MAX_ZNAKOVA,
                "cank #%d ima %d znakova, granica je %d"
                % (i, len(c), vektor.MAX_ZNAKOVA))

    def test_konstante(self):
        self.assertEqual(vektor.MAX_ZNAKOVA, 1600)
        self.assertEqual(vektor.CILJ_ZNAKOVA, 1100)
        self.assertEqual(vektor.PREKLOP, 200)
        self.assertLess(vektor.CILJ_ZNAKOVA, vektor.MAX_ZNAKOVA)

    def test_predugacak_segment_se_tvrdo_razbija(self):
        """Jedna tocka od ~1800 znakova mora se razbiti, ne odrezati."""
        tekst = "\n".join([
            tocka(1, "a", 1819),
            tocka(2, "b", 400),
            tocka(3, "c", 400),
            tocka(4, "d", 400),
        ])
        cankovi = vektor.cankiraj(tekst)
        self._provjeri_granicu(cankovi)
        self.assertGreaterEqual(len(cankovi), 2)
        # sadrzaj duge tocke nije izgubljen
        self.assertGreaterEqual(sum(c.count("a") for c in cankovi), 1800)

    def test_zavrsna_zastita_lovi_preklop_preko_granice(self):
        """
        Segment od 1550 znakova prolazi prvu provjeru (< 1600), ali mu se
        pri pakiranju doda 200 znakova preklopa i cank naraste na ~1750.
        Zavrsna zastita to mora razbiti.
        """
        tekst = "\n".join([
            tocka(1, "a", 500),
            tocka(2, "b", 500),
            tocka(3, "c", 500),
            tocka(4, "d", 1550),
            tocka(5, "e", 500),
        ])
        cankovi = vektor.cankiraj(tekst)
        self._provjeri_granicu(cankovi)
        # barem jedan cank je nabijen do same granice, sto dokazuje da je
        # zavrsna zastita doista odradila posao
        self.assertIn(vektor.MAX_ZNAKOVA, [len(c) for c in cankovi])

    def test_duga_presuda_nijedan_cank_ne_prelazi_granicu(self):
        """Realisticna presuda s 40 tocaka razlicite duljine."""
        duljine = [120, 340, 900, 1500, 2400, 60, 1750, 430, 3100, 780]
        tocke = []
        for i in range(1, 41):
            d = duljine[i % len(duljine)]
            tocke.append(tocka(i, chr(ord("a") + i % 26), d))
        cankovi = vektor.cankiraj("\n".join(tocke))
        self.assertGreater(len(cankovi), 10)
        self._provjeri_granicu(cankovi)


class TestLomljenjePoTockama(unittest.TestCase):

    def test_uvod_prije_prve_tocke_je_sacuvan(self):
        """Izreka stoji prije tocke 1. i ne smije se izgubiti."""
        uvod = ("REPUBLIKA HRVATSKA VRHOVNI SUD REPUBLIKE HRVATSKE ZAGREB "
                "U IME REPUBLIKE HRVATSKE PRESUDA Odbija se revizija tuzenika "
                "kao neosnovana. Obrazlozenje")
        tekst = uvod + "\n" + "\n".join([
            tocka(1, "a", 300), tocka(2, "b", 300), tocka(3, "c", 300),
        ])
        cankovi = vektor.cankiraj(tekst)
        self.assertTrue(cankovi)
        self.assertIn("Odbija se revizija", cankovi[0])

    def test_lomi_se_na_granici_tocke_a_ne_nasred_recenice(self):
        """Svaka tocka od ~700 znakova pocinje novi cank na svojoj granici."""
        tocke = [tocka(i, chr(ord("a") + i), 700) for i in range(1, 7)]
        cankovi = vektor.cankiraj("\n".join(tocke))
        self.assertGreater(len(cankovi), 1)
        # broj tocke uvijek stoji na pocetku reda unutar canka
        for c in cankovi:
            self.assertRegex(c, r"(?m)^\s*\d{1,3}\.\s")

    def test_podtocke_su_takoder_granice(self):
        """Oznake tipa '2.1.' su valjane granice tocaka."""
        self.assertTrue(vektor.RE_TOCKA.search("\n2.1. tekst podtocke"))
        self.assertTrue(vektor.RE_TOCKA.search("\n13. tekst tocke"))
        self.assertIsNone(vektor.RE_TOCKA.search("usred recenice 5. nema granice"))

    def test_bez_numeracije_lomi_se_po_odlomcima(self):
        """Tekst bez numeriranih tocaka ide fallback granom (po redovima)."""
        odlomci = ["Odlomak broj %d. %s" % (i, "rijec " * 100) for i in range(4)]
        cankovi = vektor.cankiraj("\n".join(o.strip() for o in odlomci))
        self.assertTrue(cankovi)
        for c in cankovi:
            self.assertLessEqual(len(c), vektor.MAX_ZNAKOVA)


class TestPreklop(unittest.TestCase):

    def test_susjedni_cankovi_dijele_kontekst(self):
        """Pocetak sljedeceg canka mora se nalaziti u prethodnom (preklop)."""
        tocke = [tocka(i, chr(ord("a") + i), 500) for i in range(1, 8)]
        cankovi = vektor.cankiraj("\n".join(tocke))
        self.assertGreaterEqual(len(cankovi), 3)
        for prvi, drugi in zip(cankovi, cankovi[1:]):
            glava = drugi[:120]
            self.assertIn(
                glava, prvi,
                "nema preklopa izmedu susjednih cankova: %r" % glava[:40])

    def test_preklop_nije_veci_od_zadanog(self):
        tocke = [tocka(i, chr(ord("a") + i), 500) for i in range(1, 8)]
        cankovi = vektor.cankiraj("\n".join(tocke))
        for prvi, drugi in zip(cankovi, cankovi[1:]):
            zajednicko = 0
            for n in range(1, min(len(prvi), len(drugi)) + 1):
                if prvi.endswith(drugi[:n]):
                    zajednicko = n
            self.assertLessEqual(zajednicko, vektor.PREKLOP + 5)


class TestOdbacivanjeKratkih(unittest.TestCase):

    def test_prazan_ulaz(self):
        self.assertEqual(vektor.cankiraj(""), [])
        self.assertEqual(vektor.cankiraj("   \n\t  \n "), [])
        self.assertEqual(vektor.cankiraj(None), [])

    def test_prekratak_tekst_se_odbacuje(self):
        """Ispod 60 znakova nema dovoljno konteksta za embedding."""
        self.assertEqual(vektor.cankiraj("Kratak tekst."), [])
        self.assertEqual(vektor.cankiraj("a" * 60), [])

    def test_tekst_tik_iznad_praga_prolazi(self):
        cankovi = vektor.cankiraj("a" * 61)
        self.assertEqual(len(cankovi), 1)
        self.assertEqual(len(cankovi[0]), 61)

    def test_kratak_ostatak_tvrdog_reza_se_odbacuje(self):
        """
        Segment od 1819 znakova reze se korakom 900 na 1100+919+19.
        Onaj ostatak od 19 znakova ne smije zavrsiti u indeksu.
        """
        tekst = "\n".join([tocka(1, "a", 1819), tocka(2, "b", 400),
                           tocka(3, "c", 400), tocka(4, "d", 400)])
        cankovi = vektor.cankiraj(tekst)
        for c in cankovi:
            self.assertGreater(len(c), 60)

    def test_svi_cankovi_su_ociscen_tekst(self):
        tekst = "\n".join([tocka(i, chr(ord("a") + i), 600) for i in range(1, 6)])
        for c in vektor.cankiraj(tekst):
            self.assertEqual(c, c.strip())
            self.assertNotIn("\t", c)
            self.assertNotIn("  ", c)


if __name__ == "__main__":
    unittest.main()
