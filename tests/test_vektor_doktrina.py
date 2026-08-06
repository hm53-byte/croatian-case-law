# -*- coding: utf-8 -*-
"""
vektor.cankiraj(..., 'doktrina'): lomljenje znanstvenog clanka na cankove.

Clanak dolazi iz PDF-a, a ne iz HTML-a, pa nosi cetiri smetnje koje presuda
nema: tvrdi prijelom retka nasred recenice, rastavljene rijeci, tekuce
zaglavlje na svakoj stranici i popis literature na kraju. Ovdje se stiti da
grana za doktrinu sve cetiri prezivi, i da i dalje postuje granicu modela.
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mreza_straza  # noqa: E402,F401  postavlja putanje i zabranjuje mrezu

import vektor  # noqa: E402


def prelomi(tekst, sirina=60):
    """Simulira tvrdi prijelom retka kakav daje izvlacenje iz PDF-a."""
    rijeci, retci, red = tekst.split(), [], ""
    for r in rijeci:
        if len(red) + len(r) + 1 > sirina:
            retci.append(red)
            red = r
        else:
            red += ((" " if red else "") + r)
    if red:
        retci.append(red)
    return "\n".join(retci)


ODLOMAK = ("Dosjelost je stjecanje prava vlasnistva na temelju posjeda koji "
           "traje zakonom odredeno vrijeme, a posjed mora biti samostalan, "
           "zakonit i posten kroz cijelo to razdoblje sto stranka mora "
           "dokazati u postupku pred sudom prvog stupnja. ")


RIJECI = ("posjed zakonitost savjesnost rokovi nekretnina uzurpacija "
          "pretvorba restitucija knjiga cestica vlasnik stjecatelj prednik "
          "sljednik tabularna izvanknjizna presumpcija predmnijeva teret "
          "dokazivanja parnica").split()


def tijelo(n, od=0):
    """
    n odlomaka teksta koji se NE ponavlja doslovno.

    Doslovno ponovljen redak je u clanku znak tekuceg zaglavlja, pa ga
    `_ocisti_pdf` brise. Fiksni odlomak prepisan n puta zato nije ispravan
    predlozak za tijelo clanka.

    Odlomci se razlikuju RIJECIMA, a ne samo brojem: `_ocisti_pdf` broji
    ucestalost nad retkom u kojem su znamenke svedene na '#', pa bi se
    odlomci koji se razlikuju samo rednim brojem sveli na isti kljuc.
    """
    rnd = random.Random(20260806)
    for _ in range(od * 40):              # premotaj da `od` doista mijenja tekst
        rnd.random()
    izlaz = []
    for i in range(n):
        recenica = " ".join(rnd.choice(RIJECI) for _ in range(40))
        izlaz.append(recenica.capitalize() + ".")
    return " ".join(izlaz)


class TestGranicaModela(unittest.TestCase):
    """Granica od 1600 znakova vrijedi i za doktrinu."""

    def test_granica_se_postuje(self):
        tekst = "3.2. Dosjelost nekretnina\n" + prelomi(tijelo(40))
        for i, c in enumerate(vektor.cankiraj(tekst, "doktrina")):
            self.assertLessEqual(
                len(c), vektor.MAX_ZNAKOVA,
                "cank #%d ima %d znakova, granica je %d"
                % (i, len(c), vektor.MAX_ZNAKOVA))

    def test_prazan_ulaz(self):
        self.assertEqual(vektor.cankiraj("", "doktrina"), [])
        self.assertEqual(vektor.cankiraj("   \n \n ", "doktrina"), [])


class TestRastavljeneRijeci(unittest.TestCase):
    """Rijec prelomljena na kraju retka mora se sastaviti natrag."""

    def _s_rastavljenom(self, sav):
        """Clanak u kojem je rijec 'vlasnistva' prelomljena zadanim savom."""
        return (prelomi(tijelo(3)) + "\nStjecanje prava " + sav
                + " temeljem dosjelosti trazi zakonit posjed.\n"
                + prelomi(tijelo(3, od=3)))

    def test_obicna_crtica(self):
        tekst = self._s_rastavljenom("vlas-\nnistva")
        spojeno = " ".join(vektor.cankiraj(tekst, "doktrina"))
        self.assertIn("vlasnistva", spojeno)
        self.assertNotIn("vlas- nistva", spojeno)

    def test_razmak_ispred_crtice(self):
        # cest artefakt izvlacenja: "vlas -\nnistva"
        tekst = self._s_rastavljenom("vlas -\nnistva")
        spojeno = " ".join(vektor.cankiraj(tekst, "doktrina"))
        self.assertIn("vlasnistva", spojeno)

    def test_velikim_slovom_se_ne_spaja(self):
        # crtica kao interpunkcija ispred vlastitog imena nije rastavljanje
        self.assertIsNone(
            vektor.RE_RASTAVLJENO.search("stranka -\nTuzitelj"))


class TestTekuceZaglavlje(unittest.TestCase):
    """Zaglavlje i broj stranice ne smiju zavrsiti u cancima."""

    def test_ponovljeno_zaglavlje_ispada(self):
        zaglavlje = "ZBORNIK PRAVNOG FAKULTETA U RIJECI"
        stranice = []
        # svaka stranica ima svoj tekst; ponavlja se samo zaglavlje
        for i in range(6):
            stranice.append("%d\n%s\n%s" % (i + 1, zaglavlje,
                                            prelomi(tijelo(3, od=i * 3))))
        cankovi = vektor.cankiraj("\n".join(stranice), "doktrina")
        spojeno = " ".join(cankovi)
        self.assertTrue(cankovi)
        self.assertNotIn(zaglavlje, spojeno)

    def test_broj_stranice_ispada(self):
        self.assertTrue(vektor.RE_BROJ_STRANICE.match("  12  "))
        self.assertTrue(vektor.RE_BROJ_STRANICE.match("- 7 -"))
        self.assertFalse(vektor.RE_BROJ_STRANICE.match("12. Dosjelost"))


class TestPopisLiterature(unittest.TestCase):
    """Popis literature na kraju clanka je za dohvat buka."""

    def test_literatura_se_odsijeca(self):
        clanak = prelomi(tijelo(20))
        rep = ("LITERATURA\n"
               "Gavella, N., Stvarno pravo, Zagreb, 2007.\n"
               "Simonetti, P., Prava na gradevinskom zemljistu, Rijeka, 2008.")
        spojeno = " ".join(vektor.cankiraj(clanak + "\n" + rep, "doktrina"))
        self.assertNotIn("Gavella", spojeno)

    def test_literatura_na_pocetku_se_ne_dira(self):
        # rijec "literatura" u prvoj trecini je tema, a ne popis na kraju
        tekst = "LITERATURA\n" + prelomi(tijelo(20))
        self.assertTrue(vektor.cankiraj(tekst, "doktrina"))


class TestPodnaslovi(unittest.TestCase):
    """Podnaslov nosi cank, i to tocno jednom."""

    def test_podnaslov_stoji_na_celu(self):
        tekst = "3.2. Dosjelost nekretnina\n" + prelomi(tijelo(6))
        cankovi = vektor.cankiraj(tekst, "doktrina")
        self.assertTrue(cankovi)
        self.assertTrue(cankovi[0].startswith("3.2. Dosjelost nekretnina"))

    def test_podnaslov_se_ne_ponavlja_u_istom_canku(self):
        naslov = "3.2. Dosjelost nekretnina"
        tekst = naslov + "\n" + prelomi(tijelo(8))
        for c in vektor.cankiraj(tekst, "doktrina"):
            self.assertLessEqual(c.count(naslov), 1)

    def test_prepoznavanje(self):
        self.assertTrue(vektor._je_podnaslov("3.2. Dosjelost nekretnina"))
        self.assertTrue(vektor._je_podnaslov("UVOD"))
        self.assertTrue(vektor._je_podnaslov("1. Uvod"))
        self.assertFalse(vektor._je_podnaslov(
            "Dosjelost je stjecanje prava vlasnistva na temelju posjeda."))


class TestGranaSeBira(unittest.TestCase):
    """`gradivo` bira granu; presuda mora ostati na starom putu."""

    def test_zadano_je_odluka(self):
        presuda = "\n".join("%d. %s" % (i, ODLOMAK) for i in range(1, 12))
        self.assertEqual(vektor.cankiraj(presuda),
                         vektor.cankiraj_odluku(presuda))

    def test_doktrina_ide_svojom_granom(self):
        clanak = prelomi(tijelo(10))
        self.assertEqual(vektor.cankiraj(clanak, "doktrina"),
                         vektor.cankiraj_clanak(clanak))

    def test_grane_daju_razlicit_rezultat(self):
        # tvrdo prelomljen tekst: grana za presude lomi po retcima, grana za
        # doktrinu ga najprije sastavi u odlomke
        clanak = prelomi(tijelo(10))
        self.assertNotEqual(vektor.cankiraj(clanak, "doktrina"),
                            vektor.cankiraj(clanak, "odluka"))


if __name__ == "__main__":
    unittest.main()
