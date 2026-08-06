# -*- coding: utf-8 -*-
"""
vektor: snop upita (multi-query), ugradnja proizvoljnog teksta (HyDE),
podrijetlo pogotka i indeksiranje odabranog podskupa odluka.

Testovi ne diraju pravi model. `vektor._model` se podmece deterministicnim
nadomjestkom (torbica rijeci u DIM koseva), pa je poredak ponovljiv i ne
trazi se ni mreza ni sentence_transformers.
"""
import io
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mreza_straza  # noqa: E402,F401  postavlja putanje i zabranjuje mrezu

import store  # noqa: E402
import vektor  # noqa: E402


def _kos(rijec):
    """
    Gruba zamjena za korjenovatelja: prva cetiri znaka rijeci u jedan kos.
    Bez toga bi se "prolaz" i "prolaza" razlikovali kao dvije rijeci, a
    nadomjestak bi mjerio nesto sto e5 ne mjeri.
    """
    return zlib.crc32(rijec[:4].encode("utf-8")) % vektor.DIM


class LazniModel(object):
    """Nadomjestak za e5. Biljezi tocan tekst koji je dobio na ugradnju."""

    def __init__(self):
        self.pozivi = []
        self.max_seq_length = 512

    def encode(self, tekstovi, batch_size=None, normalize_embeddings=True,
               show_progress_bar=False):
        tekstovi = list(tekstovi)
        self.pozivi.append({"tekstovi": tekstovi, "napredak": show_progress_bar})
        V = np.zeros((len(tekstovi), vektor.DIM), dtype=np.float32)
        for i, t in enumerate(tekstovi):
            for rijec in re.findall(r"\w+", t.lower()):
                V[i, _kos(rijec)] += 1.0
            norma = float(np.linalg.norm(V[i]))
            if norma:
                V[i] /= norma
        return V


def tocke(*recenice):
    """Numerirane tocke obrazlozenja, dovoljno duge da prezive prag od 60."""
    return "\n".join(
        "%d. %s" % (i, r * 8) for i, r in enumerate(recenice, 1))


PROLAZ = tocke(
    "Predlagatelj trazi osnivanje nuznog prolaza preko sumskog zemljista. ",
    "Nekretnina predlagatelja je enklava bez veze s javnom cestom. ",
    "Vjestak geodetske struke izmjerio je trasu prolaza u sirini od tri metra. ")

DOSJELOST = tocke(
    "Tuzitelj tvrdi da je dosjeloscu stekao pravo vlasnistva nekretnine. ",
    "Posjed je bio savjestan i zakonit kroz cijelo razdoblje od cetrdeset godina. ",
    "Uracunavanje posjeda prednika cijeni se prema clanku 388. Zakona o vlasnistvu. ")

ZAMJENA = tocke(
    "Stranke su sklopile ugovor o zamjeni nekretnina uz doplatu razlike. ",
    "Ministarstvo poljoprivrede odbilo je prijedlog za zamjenu sumskog zemljista. ",
    "Vrijednost zamijenjenih cestica utvrdena je procjembenim elaboratom. ")

MJESOVITA = tocke(
    "Sud je odlucivao o prolazu i o dosjelosti u istom postupku. ",
    "Predlagatelj se pozvao i na zamjenu i na dosjelost kao osnovu stjecanja. ",
    "Zahtjev je odbijen jer trasa prolaza nije bila oznacena u elaboratu. ")


def odluka(doc_id, broj, tekst, sud="Opcinski sud u Zadru"):
    return {
        "id": doc_id,
        "izvor": "anon",
        "url": "https://odluke.sudovi.hr/Document/View?id=" + doc_id,
        "broj": broj,
        "sud": sud,
        "datum": "2023-05-11",
        "vrsta": "presuda",
        "upisnik": broj.split("-")[0],
        "pravomocnost": "pravomocna",
        "tekst": tekst,
    }


KORPUS = [
    odluka("d-prolaz", "R1-11/2023-4", PROLAZ),
    odluka("d-dosjelost", "P-22/2023-9", DOSJELOST),
    odluka("d-zamjena", "P-33/2023-7", ZAMJENA),
    odluka("d-mjesovita", "Gz-44/2023-3", MJESOVITA),
    odluka("d-prazna", "P-55/2023-1", ""),
]


class VektorTest(unittest.TestCase):
    """Privremena baza, podmetnut model, uhvacen ispis."""

    indeksiraj = ()          # id-evi koje setUp odmah indeksira

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="presude_vektor_")
        self.db = os.path.join(self.dir, "corpus_test.sqlite")
        self.con = store.veza(self.db)
        for rec in KORPUS:
            store.spremi(self.con, rec)

        self.lazni = LazniModel()
        self._stari_model = vektor._model
        vektor._model = self.lazni

        self.zapisi = []
        self._stari_log = vektor.log
        vektor.log = self.zapisi.append

        if self.indeksiraj:
            vektor.index(con=self.con, doc_ids=list(self.indeksiraj))

    def tearDown(self):
        vektor.log = self._stari_log
        vektor._model = self._stari_model
        self.con.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def dnevnik(self):
        return "\n".join(self.zapisi)

    def indeksirane(self):
        try:
            return {r[0] for r in
                    self.con.execute("SELECT DISTINCT doc_id FROM chunks")}
        except sqlite3.OperationalError:      # indeksiranje nije ni pokrenuto
            return set()

    def cankova(self, doc_id):
        return self.con.execute(
            "SELECT COUNT(*) FROM chunks WHERE doc_id=?", (doc_id,)).fetchone()[0]


# ------------------------------------------------------------------ Upit ---

class TestUpit(unittest.TestCase):

    def test_zadano_je_hibrid_i_query(self):
        u = vektor.Upit("nuzni prolaz")
        self.assertEqual(u.grana, "hibrid")
        self.assertEqual(u.prefiks, "query")
        self.assertEqual(u.tezina, 1.0)

    def test_oznaka_se_izvede_iz_teksta(self):
        u = vektor.Upit("nuzni prolaz preko sumskog zemljista")
        self.assertEqual(u.oznaka, "nuzni prolaz preko sumskog zemljista")
        dugacak = vektor.Upit("rijec " * 40)
        self.assertLessEqual(len(dugacak.oznaka), 56)
        self.assertTrue(dugacak.oznaka.endswith("..."))

    def test_zadana_oznaka_se_postuje(self):
        u = vektor.Upit("bilo sto", oznaka="nuzni prolaz")
        self.assertEqual(u.oznaka, "nuzni prolaz")

    def test_prazan_upit_pada(self):
        self.assertRaises(ValueError, vektor.Upit, "")
        self.assertRaises(ValueError, vektor.Upit, "   \n ")

    def test_nepoznata_grana_pada(self):
        self.assertRaises(ValueError, vektor.Upit, "x", "sunce")

    def test_nepoznat_prefiks_pada(self):
        self.assertRaises(ValueError, lambda: vektor.Upit("x", prefiks="doc"))

    def test_passage_uz_bm25_je_greska(self):
        """Ograda iz docs/lov-na-presude.md: izmisljen ulomak ne ide u BM25."""
        with self.assertRaises(ValueError) as k:
            vektor.Upit("hipotetski ulomak", grana="bm25", prefiks="passage")
        self.assertIn("BM25", str(k.exception))

    def test_passage_uz_hibrid_pada_na_vektorsku_granu(self):
        u = vektor.Upit("hipotetski ulomak", prefiks="passage")
        self.assertEqual(u.grana, "vektor")

    def test_hyde_konstruktor(self):
        u = vektor.Upit.hyde("Iz nalaza vjestaka proizlazi da nema veze s cestom.")
        self.assertEqual(u.prefiks, "passage")
        self.assertEqual(u.grana, "vektor")
        self.assertTrue(u.oznaka.startswith("hyde:"))

    def test_kljuc_razlikuje_granu_i_prefiks(self):
        a = vektor.Upit("isti tekst", grana="vektor")
        b = vektor.Upit("isti tekst", grana="bm25")
        self.assertNotEqual(a.kljuc, b.kljuc)


class TestUpitiOd(unittest.TestCase):

    def test_niz_znakova_postaje_upit(self):
        snop = vektor.upiti_od("nuzni prolaz")
        self.assertEqual(len(snop), 1)
        self.assertIsInstance(snop[0], vektor.Upit)

    def test_rjecnik_postaje_upit(self):
        snop = vektor.upiti_od({"tekst": "dosjelost", "grana": "bm25", "tezina": 2})
        self.assertEqual(snop[0].grana, "bm25")
        self.assertEqual(snop[0].tezina, 2.0)

    def test_mjesovit_popis(self):
        snop = vektor.upiti_od(["a b c", vektor.Upit("d e f", grana="vektor"),
                                {"tekst": "g h i"}])
        self.assertEqual(len(snop), 3)

    def test_istovjetni_upiti_se_odbacuju(self):
        """Isti upit dvaput bi u RRF-u dvostruko bodovao isti cank."""
        snop = vektor.upiti_od(["dosjelost", "dosjelost", " dosjelost "])
        self.assertEqual(len(snop), 1)

    def test_ista_rijec_u_drugoj_grani_nije_duplikat(self):
        snop = vektor.upiti_od([vektor.Upit("dosjelost", grana="bm25"),
                                vektor.Upit("dosjelost", grana="vektor")])
        self.assertEqual(len(snop), 2)

    def test_none_i_prazno(self):
        self.assertEqual(vektor.upiti_od(None), [])
        self.assertEqual(vektor.upiti_od([]), [])


# ---------------------------------------------------------------- ugradi ---

class TestUgradi(unittest.TestCase):

    def setUp(self):
        self.lazni = LazniModel()
        self._stari = vektor._model
        vektor._model = self.lazni

    def tearDown(self):
        vektor._model = self._stari

    def zadnji(self):
        return self.lazni.pozivi[-1]["tekstovi"]

    def test_zadano_je_passage(self):
        vektor.ugradi(["tekst odluke"])
        self.assertEqual(self.zadnji(), ["passage: tekst odluke"])

    def test_upit_true_daje_query(self):
        vektor.ugradi(["pitanje"], upit=True)
        self.assertEqual(self.zadnji(), ["query: pitanje"])

    def test_prefiks_nadjacava_upit(self):
        """HyDE ulomak je pseudodokument, pa ide s 'passage:'."""
        vektor.ugradi(["hipotetski ulomak"], upit=True, prefiks="passage")
        self.assertEqual(self.zadnji(), ["passage: hipotetski ulomak"])
        vektor.ugradi(["pitanje"], prefiks="query")
        self.assertEqual(self.zadnji(), ["query: pitanje"])

    def test_nepoznat_prefiks_pada(self):
        self.assertRaises(ValueError, vektor.ugradi, ["x"], prefiks="dokument")

    def test_napredak_se_moze_ugasiti(self):
        vektor.ugradi(["a"])
        self.assertTrue(self.lazni.pozivi[-1]["napredak"])
        vektor.ugradi(["a"], napredak=False)
        self.assertFalse(self.lazni.pozivi[-1]["napredak"])

    def test_oblik_i_tip(self):
        V = vektor.ugradi(["prvi tekst", "drugi tekst"])
        self.assertEqual(V.shape, (2, vektor.DIM))
        self.assertEqual(V.dtype, np.float32)


# --------------------------------------------------- indeksiranje podskupa --

class TestIndeksSkupa(VektorTest):

    def test_indeksira_samo_zadane_odluke(self):
        vektor.index_skup(["d-prolaz", "d-zamjena"], con=self.con)
        self.assertEqual(self.indeksirane(), {"d-prolaz", "d-zamjena"})

    def test_redoslijed_id_eva_se_postuje(self):
        vektor.index_skup(["d-zamjena", "d-prolaz"], con=self.con)
        prvi = self.con.execute(
            "SELECT doc_id FROM chunks ORDER BY id LIMIT 1").fetchone()[0]
        self.assertEqual(prvi, "d-zamjena")

    def test_nepostojeci_id_ne_rusi_nego_se_javlja(self):
        vektor.index_skup(["d-prolaz", "nema-me"], con=self.con)
        self.assertEqual(self.indeksirane(), {"d-prolaz"})
        self.assertIn("nije u korpusu", self.dnevnik())
        self.assertIn("nema-me", self.dnevnik())

    def test_prazan_tekst_se_preskace(self):
        vektor.index_skup(["d-prazna"], con=self.con)
        self.assertEqual(self.indeksirane(), set())

    def test_bez_ideva_ne_radi_nista(self):
        self.assertEqual(vektor.index_skup([], con=self.con), 0)
        self.assertEqual(self.indeksirane(), set())

    def test_ponovni_poziv_ne_udvostrucuje(self):
        n1 = vektor.index_skup(["d-prolaz"], con=self.con)
        koliko = self.cankova("d-prolaz")
        n2 = vektor.index_skup(["d-prolaz"], con=self.con)
        self.assertGreater(n1, 0)
        self.assertEqual(n2, 0)
        self.assertEqual(self.cankova("d-prolaz"), koliko)

    def test_ponovno_brise_zastarjele_cankove(self):
        """Skraceni tekst ne smije ostaviti stare cankove za sobom."""
        vektor.index_skup(["d-mjesovita"], con=self.con)
        prije = self.cankova("d-mjesovita")
        self.assertGreater(prije, 1)
        kratka = dict(KORPUS[3])
        kratka["tekst"] = ("1. Jedna jedina tocka obrazlozenja, dovoljno duga "
                           "da prezive prag od sezdeset znakova. ")
        store.spremi(self.con, kratka)
        vektor.index_skup(["d-mjesovita"], ponovno=True, con=self.con)
        self.assertEqual(self.cankova("d-mjesovita"), 1)

    def test_ponovno_bez_zastave_ne_dira_postojece(self):
        vektor.index_skup(["d-prolaz"], con=self.con)
        prije = self.cankova("d-prolaz")
        kratka = dict(KORPUS[0])
        kratka["tekst"] = "1. Kratki tekst koji ima vise od sezdeset znakova ukupno."
        store.spremi(self.con, kratka)
        vektor.index_skup(["d-prolaz"], con=self.con)
        self.assertEqual(self.cankova("d-prolaz"), prije)

    def test_puni_index_i_dalje_uzima_cijeli_korpus(self):
        vektor.index(con=self.con)
        self.assertEqual(self.indeksirane(),
                         {"d-prolaz", "d-dosjelost", "d-zamjena", "d-mjesovita"})

    def test_puni_index_je_inkrementalan_nakon_podskupa(self):
        vektor.index_skup(["d-prolaz"], con=self.con)
        koliko = self.cankova("d-prolaz")
        self.zapisi[:] = []
        vektor.index(con=self.con)
        self.assertIn("novo: 3", self.dnevnik())
        self.assertEqual(self.cankova("d-prolaz"), koliko)

    def test_limit_reze_podskup(self):
        vektor.index_skup(["d-prolaz", "d-dosjelost", "d-zamjena"],
                          limit=2, con=self.con)
        self.assertEqual(len(self.indeksirane()), 2)

    def test_bm25_indeks_je_obnovljen(self):
        vektor.index_skup(["d-dosjelost"], con=self.con)
        redovi = vektor._bm25(self.con, "dosjeloscu", 10)
        self.assertTrue(redovi)


class TestUcitajIdeve(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="presude_ideve_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def zapisi(self, ime, sadrzaj):
        putanja = os.path.join(self.dir, ime)
        with io.open(putanja, "w", encoding="utf-8") as f:
            f.write(sadrzaj)
        return putanja

    def test_redak_po_redak_s_komentarima(self):
        p = self.zapisi("ids.txt", "# zlatni skup\nd-prolaz\n\nd-zamjena  # jako\n")
        self.assertEqual(vektor.ucitaj_ideve(p), ["d-prolaz", "d-zamjena"])

    def test_ponovljeni_id_se_odbacuje(self):
        p = self.zapisi("ids.txt", "d-prolaz\nd-prolaz\n")
        self.assertEqual(vektor.ucitaj_ideve(p), ["d-prolaz"])

    def test_json_popis_nizova(self):
        p = self.zapisi("ids.json", '["d-prolaz", "d-zamjena"]')
        self.assertEqual(vektor.ucitaj_ideve(p), ["d-prolaz", "d-zamjena"])

    def test_json_popis_zapisa(self):
        p = self.zapisi("ids.json",
                        '[{"id": "d-prolaz", "razred": "JAKO"}, {"id": "d-zamjena"}]')
        self.assertEqual(vektor.ucitaj_ideve(p), ["d-prolaz", "d-zamjena"])


# --------------------------------------------------------- snop upita ------

class TestSnopUpita(VektorTest):

    indeksiraj = ("d-prolaz", "d-dosjelost", "d-zamjena", "d-mjesovita")

    # rijeci koje stoje samo u odluci d-prolaz, da poredak ne ovisi o sreci
    UPIT_PROLAZ = dict(tekst="nuznog prolaza enklava vjestak geodetske trase",
                       grana="vektor", oznaka="nuzni prolaz")

    def svi(self, upiti, k=50):
        return vektor.pretrazi(upiti, k, con=self.con, dubina=50)

    def test_jedan_upit_vraca_pogotke_s_podrijetlom(self):
        pogotci = self.svi([vektor.Upit(**self.UPIT_PROLAZ)])
        self.assertTrue(pogotci)
        p = pogotci[0]
        self.assertTrue(p.doc_id)
        self.assertTrue(p.podrijetlo)
        self.assertEqual(p.podrijetlo[0].grana, "vektor")
        self.assertEqual(p.podrijetlo[0].upit, "nuzni prolaz")
        self.assertEqual(p.podrijetlo[0].rang, 1)

    def test_metapodaci_odluke_su_uz_pogodak(self):
        pogotci = self.svi([vektor.Upit(**self.UPIT_PROLAZ)])
        p = pogotci[0]
        self.assertEqual(p.doc_id, "d-prolaz")
        self.assertEqual(p.broj, "R1-11/2023-4")
        self.assertEqual(p.sud, "Opcinski sud u Zadru")
        self.assertTrue(p.url.startswith("https://"))

    def test_rrf_zbraja_doprinose_preko_upita(self):
        """
        Ocjena iz snopa mora biti tocno zbroj 1/(60+rang) po pojedinom upitu.
        To je jedina provjera koja dokazuje da se upiti spajaju RRF-om, a ne
        nekim tihim preklapanjem.
        """
        a = vektor.Upit("nuzni prolaz preko sumskog zemljista", grana="vektor")
        b = vektor.Upit("dosjelost i uracunavanje posjeda prednika", grana="vektor")
        sami_a = {p.cank_id: r for r, p in enumerate(self.svi([a]), 1)}
        sami_b = {p.cank_id: r for r, p in enumerate(self.svi([b]), 1)}
        zajedno = self.svi([a, b])
        self.assertTrue(zajedno)
        for p in zajedno:
            ocekivano = 0.0
            if p.cank_id in sami_a:
                ocekivano += 1.0 / (vektor.RRF_K + sami_a[p.cank_id])
            if p.cank_id in sami_b:
                ocekivano += 1.0 / (vektor.RRF_K + sami_b[p.cank_id])
            self.assertAlmostEqual(p.ocjena, ocekivano, places=9)

    def test_snop_je_poredan_padajuce(self):
        a = vektor.Upit("nuzni prolaz", grana="vektor")
        b = vektor.Upit("dosjelost", grana="vektor")
        ocjene = [p.ocjena for p in self.svi([a, b])]
        self.assertEqual(ocjene, sorted(ocjene, reverse=True))

    def test_cank_iz_oba_upita_nosi_oba_podrijetla(self):
        a = vektor.Upit("prolaz", grana="vektor", oznaka="kut-stvarnopravni")
        b = vektor.Upit("dosjelost", grana="vektor", oznaka="kut-procesni")
        dvostruki = [p for p in self.svi([a, b]) if len(p.upiti) == 2]
        self.assertTrue(dvostruki, "nijedan cank nije dosao iz oba upita")
        self.assertEqual(set(dvostruki[0].upiti),
                         {"kut-stvarnopravni", "kut-procesni"})

    def test_tezina_mijenja_doprinos(self):
        lagan = vektor.Upit("nuznog prolaza", grana="vektor")
        tezak = vektor.Upit("nuznog prolaza", grana="vektor", tezina=3.0)
        p1 = self.svi([lagan])[0]
        p2 = self.svi([tezak])[0]
        self.assertAlmostEqual(p2.ocjena, 3.0 * p1.ocjena, places=9)

    def test_hibrid_spaja_obje_grane(self):
        pogotci = self.svi([vektor.Upit("dosjelost", grana="hibrid")])
        grane = set()
        for p in pogotci:
            grane.update(p.grane)
        self.assertEqual(grane, {"bm25", "vektor"})

    def test_hyde_ulomak_nikad_ne_dira_bm25(self):
        ulomak = ("Iz nalaza i misljenja vjestaka geodetske struke proizlazi da "
                  "nekretnina predlagatelja predstavlja enklavu unutar sumskog "
                  "kompleksa te da nema nikakve veze s javnom cestom.")
        pogotci = self.svi([vektor.Upit.hyde(ulomak)])
        self.assertTrue(pogotci)
        for p in pogotci:
            self.assertEqual(p.grane, ["vektor"])

    def test_hyde_se_ugraduje_kao_pseudodokument(self):
        self.lazni.pozivi[:] = []
        self.svi([vektor.Upit.hyde("Sud je utvrdio da su ispunjene pretpostavke.")])
        upitni = [z for z in self.lazni.pozivi if len(z["tekstovi"]) == 1]
        self.assertTrue(upitni)
        self.assertTrue(upitni[-1]["tekstovi"][0].startswith("passage: "))

    def test_obicno_pitanje_se_ugraduje_kao_upit(self):
        self.lazni.pozivi[:] = []
        self.svi([vektor.Upit("kako doci do kuce preko sumskog zemljista",
                              grana="vektor")])
        self.assertTrue(self.lazni.pozivi[-1]["tekstovi"][0].startswith("query: "))

    def test_snop_ugraduje_po_prefiksu_u_jednom_pozivu(self):
        """Dva pitanja i dva ulomka daju dva poziva modelu, ne cetiri."""
        self.lazni.pozivi[:] = []
        self.svi([vektor.Upit("prvo pitanje", grana="vektor"),
                  vektor.Upit("drugo pitanje", grana="vektor"),
                  vektor.Upit.hyde("Prvi hipotetski ulomak obrazlozenja."),
                  vektor.Upit.hyde("Drugi hipotetski ulomak obrazlozenja.")])
        self.assertEqual(len(self.lazni.pozivi), 2)
        duljine = sorted(len(z["tekstovi"]) for z in self.lazni.pozivi)
        self.assertEqual(duljine, [2, 2])

    def test_bm25_upit_ne_ugraduje_nista(self):
        self.lazni.pozivi[:] = []
        self.svi([vektor.Upit("dosjelost", grana="bm25")])
        self.assertEqual(self.lazni.pozivi, [])

    def test_k_reze_izlaz(self):
        a = vektor.Upit("prolaz", grana="vektor")
        self.assertLessEqual(len(vektor.pretrazi([a], 2, con=self.con)), 2)

    def test_prazan_snop(self):
        self.assertEqual(vektor.pretrazi([], con=self.con), [])
        self.assertEqual(vektor.pretrazi(None, con=self.con), [])

    def test_niz_znakova_je_valjan_snop(self):
        self.assertTrue(vektor.pretrazi("dosjelost", 5, con=self.con))

    def test_radi_na_vezi_samo_za_citanje(self):
        """Mjerenje otvara bazu preko otvori_ro; pretraga ne smije pisati."""
        self.con.commit()
        ro = store.otvori_ro(self.db)
        try:
            pogotci = vektor.pretrazi(
                [vektor.Upit("dosjelost", grana="hibrid")], 5, con=ro)
            self.assertTrue(pogotci)
        finally:
            ro.close()


class TestPrazanIndeks(VektorTest):

    def test_pretraga_bez_ijednog_canka(self):
        self.assertEqual(vektor.pretrazi("dosjelost", con=self.con), [])

    def test_query_javlja_prazan_indeks(self):
        vektor.query("dosjelost", con=self.con)
        self.assertIn("Indeks je prazan", self.dnevnik())


# ------------------------------------------------------------- objasni -----

class TestObjasni(VektorTest):

    indeksiraj = ("d-prolaz", "d-dosjelost", "d-mjesovita")

    def test_objasni_imenuje_upit_granu_i_rang(self):
        a = vektor.Upit("prolaz", grana="vektor", oznaka="nuzni prolaz")
        b = vektor.Upit("dosjelost", grana="bm25", oznaka="dosjelost")
        redci = vektor.objasni(vektor.pretrazi([a, b], 5, con=self.con))
        self.assertTrue(redci)
        self.assertEqual(redci[0]["rang"], 1)
        self.assertTrue(redci[0]["doc_id"])
        for r in redci:
            self.assertTrue(set(r["upiti"]) <= {"nuzni prolaz", "dosjelost"})
            self.assertTrue(set(r["grane"]) <= {"vektor", "bm25"})
            for p in r["podrijetlo"]:
                self.assertIn("rang", p)
                self.assertIn("doprinos", p)
                self.assertIn("tekst_upita", p)

    def test_objasni_prima_i_jedan_pogodak(self):
        pogotci = vektor.pretrazi("prolaz", 3, con=self.con)
        self.assertEqual(len(vektor.objasni(pogotci[0])), 1)

    def test_objasnjenje_je_jedan_redak(self):
        pogotci = vektor.pretrazi(
            [vektor.Upit("prolaz", grana="vektor", oznaka="nuzni prolaz")],
            3, con=self.con)
        redak = pogotci[0].objasnjenje()
        self.assertIn("nuzni prolaz", redak)
        self.assertIn("[vektor #1]", redak)

    def test_upiti_su_poredani_po_doprinosu(self):
        jak = vektor.Upit("prolaz", grana="vektor", oznaka="jak", tezina=5.0)
        slab = vektor.Upit("prolaz i dosjelost", grana="vektor", oznaka="slab")
        dvostruki = [p for p in vektor.pretrazi([jak, slab], 20, con=self.con)
                     if len(p.upiti) == 2]
        self.assertTrue(dvostruki)
        self.assertEqual(dvostruki[0].upiti[0], "jak")


# --------------------------------------------------------------- query -----

class TestQuery(VektorTest):

    indeksiraj = ("d-prolaz", "d-dosjelost", "d-zamjena", "d-mjesovita")

    def test_jedan_upit_ispisuje_stari_oblik_zaglavlja(self):
        vektor.query("dosjelost", 3, con=self.con)
        d = self.dnevnik()
        self.assertIn("=== HIBRID", d)
        self.assertIn("'dosjelost'", d)
        self.assertIn(u"isječaka ===", d)
        self.assertNotIn("snop od", d)

    def test_snop_iz_naredbenog_retka(self):
        pogotci = vektor.query("dosjelost", 5, upiti=["nuzni prolaz"],
                               hyde=["Sud je utvrdio da nema veze s javnom cestom."],
                               con=self.con)
        self.assertTrue(pogotci)
        self.assertIn("snop od 3 upita", self.dnevnik())

    def test_objasnjenje_se_ispisuje_na_zahtjev(self):
        vektor.query("dosjelost", 3, con=self.con)
        self.assertNotIn("     iz: ", self.dnevnik())
        self.zapisi[:] = []
        vektor.query("dosjelost", 3, objasnjenje=True, con=self.con)
        self.assertIn("     iz: ", self.dnevnik())

    def test_nacin_bm25_ne_dira_model(self):
        self.lazni.pozivi[:] = []
        vektor.query("dosjelost", 3, "bm25", con=self.con)
        self.assertEqual(self.lazni.pozivi, [])

    def test_query_bez_ijednog_upita(self):
        self.assertEqual(vektor.query(None, con=self.con), [])
        self.assertIn("Nema nijednog upita", self.dnevnik())

    def test_query_vraca_iste_pogotke_koje_ispisuje(self):
        pogotci = vektor.query("dosjelost", 3, con=self.con)
        self.assertTrue(all(isinstance(p, vektor.Pogodak) for p in pogotci))
        self.assertEqual([p.cank_id for p in pogotci],
                         [p.cank_id for p in
                          vektor.pretrazi("dosjelost", 3, con=self.con)])


class TestStat(VektorTest):

    indeksiraj = ("d-prolaz",)

    def test_stat_broji_pokrivenost(self):
        self.zapisi[:] = []
        vektor.stat(con=self.con)
        d = self.dnevnik()
        self.assertIn("Odluka u korpusu:        5", d)
        self.assertIn("Odluka indeksirano:      1", d)
        self.assertIn("Pokrivenost korpusa:", d)


if __name__ == "__main__":
    unittest.main()
