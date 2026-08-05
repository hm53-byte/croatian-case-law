# -*- coding: utf-8 -*-
"""
analiza_cl55.ocijeni: klasifikator mora razlikovati cl. 55. Zakona o sumama
od cl. 55. Zakona o naknadi (denacionalizacija).

To je cijela svrha modula: puko trazenje "clanak 55" daje mnostvo laznih
pogodaka jer isti broj clanka postoji u vise propisa.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mreza_straza  # noqa: E402,F401  postavlja putanje i zabranjuje mrezu

import analiza_cl55  # noqa: E402


# --- umjetni tekst 1: prava stvar, cl. 55. Zakona o sumama -----------------
SUME = (
    u"Odbija se tužbeni zahtjev tužitelja kao neosnovan. Obrazloženje: "
    u"Prvostupanjski sud utvrdio je da su stranke pregovarale o zamjeni "
    u"šumskog zemljišta u vlasništvu Republike Hrvatske, a sve na temelju "
    u"članka 55. Zakona o šumama, radi okrupnjivanja šuma unutar iste "
    u"gospodarske jedinice. Prema odredbi navedenog propisa ministar sklapa "
    u"ugovor o zamjeni nekretnina samo ako je razlika u vrijednosti unutar "
    u"srazmjerne vrijednosti, odnosno uz odstupanje od 5 %. Odluka o zamjeni "
    u"šuma nije donesena, pa ni ugovor o zamjeni nekretnina nije mogao biti "
    u"sklopljen. Hrvatske šume d.o.o. kao javni šumoposjednik nisu bile "
    u"stranka postupka."
)

# --- umjetni tekst 2: lazni pogodak, cl. 55. Zakona o naknadi -------------
NAKNADA = (
    u"Odbija se žalba kao neosnovana. Obrazloženje: Predmet postupka je "
    u"zahtjev za povrat oduzete imovine podnesen na temelju članka 55. "
    u"Zakona o naknadi za imovinu oduzetu za vrijeme jugoslavenske "
    u"komunističke vladavine. Tijelo prvog stupnja pravilno je utvrdilo da "
    u"podnositeljica nije dokazala svojstvo ovlaštenika naknade, niti je u "
    u"zakonskom roku dostavila ispravu o vlasništvu prednika. Naknada se u "
    u"takvom slučaju ne dosuđuje ni u obveznicama ni u dionicama."
)


def zapis(tekst):
    """Minimalni redak korpusa; ocijeni() cita samo kljuc 'tekst'."""
    return {"tekst": tekst}


class TestRazlikovanjePropisa(unittest.TestCase):

    def setUp(self):
        self.sume = analiza_cl55.ocijeni(zapis(SUME))
        self.naknada = analiza_cl55.ocijeni(zapis(NAKNADA))

    def test_sume_su_iznad_zadanog_praga(self):
        """Zadani prag u main() je 6 bodova."""
        self.assertGreaterEqual(self.sume["bodovi"], 6)

    def test_naknada_je_duboko_ispod_praga(self):
        self.assertLess(self.naknada["bodovi"], 6)
        self.assertLessEqual(self.naknada["bodovi"], 0)

    def test_sume_bodovanije_od_naknade(self):
        self.assertGreater(self.sume["bodovi"], self.naknada["bodovi"])
        # razlika mora biti velika, ne za dlaku
        self.assertGreaterEqual(self.sume["bodovi"] - self.naknada["bodovi"], 10)

    def test_blizina_cl55_i_zakona_o_sumama(self):
        self.assertIn(u"čl.55 + Zakon o šumama (blizina)", self.sume["signali"])
        self.assertTrue(self.sume["konteksti"])

    def test_naknada_nema_signal_blizine(self):
        self.assertNotIn(u"čl.55 + Zakon o šumama (blizina)", self.naknada["signali"])
        self.assertEqual(self.naknada["konteksti"], [])

    def test_naknada_dobiva_kaznu(self):
        self.assertTrue(
            any(u"Zakona o naknadi" in s for s in self.naknada["signali"]),
            "nedostaje upozorenje na drugi propis: %r" % self.naknada["signali"])


class TestMaterijalniSignali(unittest.TestCase):

    def setUp(self):
        self.sume = analiza_cl55.ocijeni(zapis(SUME))

    def test_prepoznati_signali(self):
        ocekivani = [
            u"okrupnjivanje šuma",
            u"gospodarska jedinica",
            u"ugovor o zamjeni nekretnina",
            u"odluka o zamjeni šuma",
            u"srazmjerna vrijednost / 5 %",
            u"zamjena + šumsko zemljište",
            u"Hrvatske šume / javni šumoposjednik",
            u"ministar sklapa ugovor",
        ]
        for ime in ocekivani:
            self.assertIn(ime, self.sume["signali"])

    def test_signali_se_ne_broje_dvaput(self):
        self.assertEqual(len(self.sume["signali"]), len(set(self.sume["signali"])))

    def test_zbroj_bodova_odgovara_tezinama(self):
        ocekivano = 6  # blizina cl.55 + Zakon o sumama
        for ime, (_rx, w) in analiza_cl55.SIGNALI.items():
            if ime in self.sume["signali"]:
                ocekivano += w
        self.assertEqual(self.sume["bodovi"], ocekivano)

    def test_neutralan_tekst_ne_dobiva_bodove(self):
        neutralno = zapis(
            u"Odbija se tužbeni zahtjev. Predmet spora je naknada štete zbog "
            u"prometne nezgode na raskrižju u naselju.")
        o = analiza_cl55.ocijeni(neutralno)
        self.assertEqual(o["bodovi"], 0)
        self.assertEqual(o["signali"], [])


class TestIshod(unittest.TestCase):

    def test_odbijen(self):
        o = analiza_cl55.ocijeni(zapis(u"Odbija se tužbeni zahtjev kao neosnovan."))
        self.assertEqual(o["ishod"], "zahtjev ODBIJEN")

    def test_usvojen(self):
        o = analiza_cl55.ocijeni(zapis(u"Usvaja se tužbeni zahtjev tužitelja."))
        self.assertEqual(o["ishod"], "zahtjev USVOJEN (barem djelomično)")

    def test_ponistenje_rjesenja(self):
        o = analiza_cl55.ocijeni(zapis(u"Poništava se rješenje tuženika od 1.1.2020."))
        self.assertEqual(o["ishod"], "zahtjev USVOJEN (barem djelomično)")

    def test_nerazlucen(self):
        o = analiza_cl55.ocijeni(zapis(u"Postupak se prekida do pravomoćnosti."))
        self.assertEqual(o["ishod"], "")


class TestRubniSlucajevi(unittest.TestCase):

    def test_prazan_tekst(self):
        o = analiza_cl55.ocijeni(zapis(u""))
        self.assertEqual(o["bodovi"], 0)
        self.assertEqual(o["signali"], [])
        self.assertEqual(o["konteksti"], [])

    def test_tekst_none(self):
        o = analiza_cl55.ocijeni(zapis(None))
        self.assertEqual(o["bodovi"], 0)

    def test_cl55_predaleko_od_zakona_o_sumama(self):
        """Prozor blizine je 400 znakova; izvan njega nema veze."""
        daleko = (u"članka 55. stavka 1." + u" nebitan tekst" * 100 +
                  u" Zakona o šumama")
        o = analiza_cl55.ocijeni(zapis(daleko))
        self.assertNotIn(u"čl.55 + Zakon o šumama (blizina)", o["signali"])

    def test_najvise_tri_konteksta(self):
        gust = (u"članak 55. Zakona o šumama. " * 20)
        o = analiza_cl55.ocijeni(zapis(gust))
        self.assertLessEqual(len(o["konteksti"]), 3)

    def test_kazna_izostaje_kad_su_oba_propisa_spomenuta(self):
        """Odluka koja usporeduje oba propisa ne smije biti kaznjena."""
        oba = (u"Sud je razmotrio članak 55. Zakona o šumama, a tuženik se "
               u"pozvao i na Zakon o naknadi za oduzetu imovinu.")
        o = analiza_cl55.ocijeni(zapis(oba))
        self.assertFalse(any(u"drugi propis" in s for s in o["signali"]))


if __name__ == "__main__":
    unittest.main()
