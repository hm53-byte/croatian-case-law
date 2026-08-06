# -*- coding: utf-8 -*-
"""
VEKTORSKA (semantička) pretraga korpusa presuda + HIBRID s BM25.

Zašto uopće: hrvatski pravni jezik isti pojam izriče na više načina — "zamjena",
"razmjena", "zamijeniti", "ustupanje uz protučinidbu", "prijenos uz naknadu u
zemljištu". Pretraga po točnoj frazi (FTS5) sve to promaši. Vektorska pretraga
hvata značenje, ali zato promaši brojeve članaka i oznake predmeta, gdje je
doslovno podudaranje presudno. Zato je zadani način rada HIBRID.

Arhitektura
-----------
    odluke (SQLite)  ->  čankiranje po točkama obrazloženja  ->  embeddingi
                                     |                              |
                              chunks + chunks_fts (BM25)      BLOB u chunks
                                     \\____________  ______________/
                                                  \\/
                                     RRF fuzija -> rangirani isječci

- Čankiranje poštuje strukturu presude: obrazloženja su numerirana ("1.", "13.",
  "2.1."), pa se lomi na tim granicama, a ne nasred rečenice.
- Doktrina (znanstveni članci s Hrčka) ima svoju granu čankiranja. Članak nije
  numeriran, dolazi iz PDF-a i nosi tvrde prijelome retka, rastavljene riječi i
  tekuće zaglavlje, pa se najprije sastavlja u odlomke, a lomi po podnaslovima.
  Granu bira `gradivo` iz pohrane; granica od 1600 znakova vrijedi za obje jer
  je to granica modela, a ne svojstvo dokumenta. Vidi `cankiraj()`.
- Inkrementalno: već indeksirane odluke se preskaču, kao i kod harvesta.
- Model: intfloat/multilingual-e5-small (384 dim). Traži prefikse
  "query: " / "passage: " — bez njih kvaliteta osjetno pada.

Snop upita (sloj 2 iz docs/lov-na-presude.md)
---------------------------------------------
Jedan upit je pretpostavka, a ne postupak. `pretrazi()` prima SNOP upita i
spaja ih istim RRF-om kojim spaja BM25 i vektor, pa svaki `Pogodak` nosi
`podrijetlo`: iz kojeg je upita, iz koje grane i s kojim rangom došao.

`Upit(tekst, prefiks="passage")` ugrađuje proizvoljan tekst kao pseudodokument
(HyDE). Takav upit ide ISKLJUČIVO u vektorsku granu: ulomak je izmišljen, pa je
pogrešan broj članka u vektorskom prostoru sitan pomak, a u BM25 izravan lažni
pogodak s visokim rangom.

Pokretanje
----------
    python vektor.py index                     # čankiraj + vektoriziraj (inkrementalno)
    python vektor.py index-skup ID1 ID2 ...    # samo odabrane odluke (zlatni skup)
    python vektor.py index-skup --iz-datoteke zlatni.txt --ponovno
    python vektor.py query "zamjena škart zemljišta za građevinsko" -k 8
    python vektor.py query "..." --nacin vektor     # samo semantički
    python vektor.py query "..." --nacin bm25       # samo doslovno
    python vektor.py query "..." --upit "drugi kut" --upit "treći kut"
    python vektor.py query "..." --hyde "Iz nalaza vještaka proizlazi da ..."
    python vektor.py query "..." --objasni          # iz kojeg upita dolazi pogodak
    python vektor.py stat
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sqlite3
import struct
import sys

import numpy as np

from common import log
import store

MODEL_NAME = "intfloat/multilingual-e5-small"
DIM = 384
CILJ_ZNAKOVA = 1100          # ciljana veličina čanka
MAX_ZNAKOVA = 1600           # tvrda granica — iznad nje model reže tekst
PREKLOP = 200                # preklop među čancima (da se ne izgubi kontekst na šavu)
BATCH = 16                   # mali batch — ovo je Intel CPU, ne GPU

RRF_K = 60                   # konstanta RRF-a; ne podešavati na 17 primjera
DUBINA_MNOZITELJ = 5         # koliko se dubljih kandidata vuče po grani
GRANE = ("hibrid", "vektor", "bm25")
PREFIKSI = ("query", "passage")

SHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id       INTEGER PRIMARY KEY,
    doc_id   TEXT NOT NULL,
    ord      INTEGER NOT NULL,
    tekst    TEXT NOT NULL,
    emb      BLOB,
    UNIQUE(doc_id, ord)
);
CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(doc_id);
"""
FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    tekst, content='chunks', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
"""


# ------------------------------------------------------------- čankiranje --

# granica: novi red pa broj točke ("12.", "2.1.", "13 ") na početku odlomka
RE_TOCKA = re.compile(r"(?m)^\s*\d{1,3}(?:\.\d{1,2})*\.?\s")


def cankiraj(tekst: str, gradivo: str = "odluka") -> list[str]:
    """
    Lomi dokument na čanke. Grana ovisi o vrsti gradiva.

    Presuda je numerirana ("1.", "2.1.") i dolazi iz HTML-a, pa se lomi po
    tockama obrazlozenja. Znanstveni clanak nema tu numeraciju, dolazi iz
    PDF-a i nosi tvrde prijelome retka, rastavljene rijeci i tekuce zaglavlje
    na svakoj stranici, pa ide svojim putem. Granica MAX_ZNAKOVA vrijedi za
    obje grane jer je to granica modela, a ne svojstvo dokumenta.
    """
    if (gradivo or "odluka") == "doktrina":
        return cankiraj_clanak(tekst)
    return cankiraj_odluku(tekst)


def cankiraj_odluku(tekst: str) -> list[str]:
    """Lomi presudu na čanke poštujući numerirane točke obrazloženja."""
    tekst = re.sub(r"[ \t]+", " ", tekst or "").strip()
    if not tekst:
        return []

    granice = [m.start() for m in RE_TOCKA.finditer(tekst)]
    if len(granice) >= 3:
        segmenti = []
        for i, g in enumerate(granice):
            kraj = granice[i + 1] if i + 1 < len(granice) else len(tekst)
            segmenti.append(tekst[g:kraj].strip())
        if granice[0] > 0:                      # uvod prije prve točke (izreka!)
            segmenti.insert(0, tekst[:granice[0]].strip())
    else:
        segmenti = [p.strip() for p in tekst.split("\n") if p.strip()]

    return _spakiraj(segmenti)


def _spakiraj(segmenti: list[str]) -> list[str]:
    """
    Slaze gotove segmente u canke ciljane velicine, s preklopom na savu.

    Zajednicko objema granama: presuda i clanak razlicito nalaze granice, ali
    granicu modela postuju isto.
    """
    cankovi, buf = [], ""
    for seg in segmenti:
        if not seg:
            continue
        # e5-small prima 512 tokena (~1800 znakova za hrvatski); sve preko toga
        # model bi tiho odsjekao, pa segment radije razbijamo sami
        if len(seg) > MAX_ZNAKOVA:              # predugačak segment — razbij tvrdo
            if buf:
                cankovi.append(buf.strip()); buf = ""
            korak = CILJ_ZNAKOVA - PREKLOP
            for i in range(0, len(seg), korak):
                cankovi.append(seg[i:i + CILJ_ZNAKOVA].strip())
            continue
        if len(buf) + len(seg) + 1 > CILJ_ZNAKOVA and buf:
            cankovi.append(buf.strip())
            buf = buf[-PREKLOP:] if len(buf) > PREKLOP else ""
        buf += ("\n" if buf else "") + seg
    if buf.strip():
        cankovi.append(buf.strip())

    # završna zaštita: preklop se dodaje NA segment, pa čanak može premašiti
    # MAX_ZNAKOVA i biti tiho odsječen u modelu — takve ovdje tvrdo razbijamo
    sigurni = []
    for c in cankovi:
        if len(c) <= MAX_ZNAKOVA:
            sigurni.append(c)
        else:
            korak = MAX_ZNAKOVA - PREKLOP
            sigurni += [c[i:i + MAX_ZNAKOVA] for i in range(0, len(c), korak)]
    return [c.strip() for c in sigurni if len(c.strip()) > 60]


# ------------------------------------------------- čankiranje doktrine -----
#
# Clanak nije presuda. Iz PDF-a stize tekst koji ima cetiri smetnje zbog kojih
# je cankiranje po retcima besmisleno:
#
#   1. tvrdi prijelom retka svakih ~60 znakova, nasred recenice;
#   2. rastavljanje rijeci na kraju retka ("gra-\ndenje", cesto i "gra -\n");
#   3. tekuce zaglavlje i broj stranice, ponovljeni na svakoj stranici;
#   4. popis literature na kraju, koji je za dohvat cista buka.
#
# Zato se tekst najprije sastavlja natrag u odlomke, pa tek onda lomi. Granice
# su podnaslovi (numerirani "3.2." ili verzalom) i odlomci, a ne brojevi tocaka.

# Rijec rastavljena na kraju retka. Izvlacenje iz PDF-a cesto ubaci razmak
# ispred crtice ("move -\nment"), pa je i on dopusten. Oba kraja moraju biti
# mala slova, cime otpada crtica kao interpunkcija ("stranka -\nTuzitelj").
#
# Ostaje jedna nerazlucivost koju ovo pravilo grijesi svjesno: polusloznica
# prelomljena na kraju retka ("pravno-\npoliticki") spaja se u "pravnopoliticki".
# Razlikovati je od rastavljene rijeci trazilo bi rjecnik. Prelamanje je u
# ovim PDF-ovima redovito, polusloznica bas na savu retka rijetka, pa se
# uzima cesci slucaj.
RE_RASTAVLJENO = re.compile(r"([a-zà-ž])\s*[-­]\s*\n\s*([a-zà-ž])")
# redak koji je samo broj stranice, moguce u crticama ili zagradama
RE_BROJ_STRANICE = re.compile(r"^\s*[^\w\s]{0,2}\s*\d{1,4}\s*[^\w\s]{0,2}\s*$")
# podnaslov s brojem: "3.", "3.2.", "3.2.1." pa razmak pa slovo
RE_PODNASLOV_BROJ = re.compile(r"^\s*\d{1,2}(?:\.\d{1,2}){0,3}\.?\s+\S")
# pocetak popisa literature; od njega nadalje se rez
RE_LITERATURA = re.compile(
    r"^\s*(?:\d{1,2}\.?\s*)?(?:popis\s+)?"
    r"(?:literatur\w*|bibliografij\w*|reference\w*|references|"
    r"izvori\s+i\s+literatura|pravni\s+izvori)\s*:?\s*$", re.I)
# podnaslovi koje clanci nose i kad nisu numerirani
RIJECI_PODNASLOVA = (
    "uvod", "zakljucak", "zaključak", "sazetak", "sažetak", "summary",
    "abstract", "introduction", "conclusion", "keywords", "kljucne rijeci",
    "ključne riječi",
)


def _je_podnaslov(redak: str) -> bool:
    """
    Prepoznaje podnaslov. Namjerno strogo: laznim podnaslovom lomi se odlomak
    nasred recenice, a to je gore od propustenog podnaslova.
    """
    r = redak.strip()
    if not (3 <= len(r) <= 100):
        return False
    if r.endswith((".", ",", ";", ":")) and not RE_PODNASLOV_BROJ.match(r):
        # recenica, a ne naslov; iznimka je naslov pisan verzalom
        if not r.rstrip(".").isupper():
            return False
    if r.lower().strip(" :.") in RIJECI_PODNASLOVA:
        return True
    if RE_PODNASLOV_BROJ.match(r) and len(r) <= 90 and not r.endswith((",", ";")):
        return True
    slova = [z for z in r if z.isalpha()]
    if len(slova) >= 4 and sum(z.isupper() for z in slova) / len(slova) > 0.8:
        return True
    return False


def _ocisti_pdf(tekst: str) -> list[str]:
    """
    Vraca retke bez tekuceg zaglavlja, broja stranice i rastavljenih rijeci.

    Tekuce zaglavlje se ne prepoznaje po sadrzaju nego po ponavljanju: kratak
    redak koji se u clanku pojavljuje tri i vise puta dolazi s vrha ili dna
    stranice. Prag je 3 da se ne pobrise podnaslov ponovljen u sadrzaju.
    """
    tekst = RE_RASTAVLJENO.sub(r"\1\2", tekst or "")
    tekst = tekst.replace("­", "")
    retci = [r.strip() for r in tekst.split("\n")]

    ucestalost: dict[str, int] = {}
    for r in retci:
        k = re.sub(r"\d+", "#", r.lower())
        if 8 <= len(k) <= 120:
            ucestalost[k] = ucestalost.get(k, 0) + 1

    # Osigurac: pravilo "ponovljeno tri puta znaci zaglavlje" vrijedi jer se
    # redak tekuceg teksta u clanku ne ponavlja doslovno. Ako ipak pokusa
    # pojesti vise od cetvrtine redaka, promasilo je (tablica, popis, tekst s
    # refrenom), pa se odustaje od filtra umjesto da se izgubi tijelo clanka.
    sumnjivi = {k for k, n in ucestalost.items() if n >= 3}
    koliko_bi_palo = sum(1 for r in retci
                         if re.sub(r"\d+", "#", r.lower()) in sumnjivi)
    filtriraj = koliko_bi_palo <= max(3, len(retci) // 4)

    cisti = []
    for r in retci:
        if not r or RE_BROJ_STRANICE.match(r):
            continue
        k = re.sub(r"\d+", "#", r.lower())
        if filtriraj and k in sumnjivi:
            continue                      # tekuce zaglavlje ili podnozje
        cisti.append(r)
    return cisti


def _u_odlomke(retci: list[str]) -> list[tuple[str, bool]]:
    """
    Sastavlja tvrdo prelomljene retke natrag u odlomke.

    PDF lomi redak na sirini stupca, pa je duljina retka signal: redak osjetno
    kraci od uobicajenog zavrsava odlomak. Prag je 0,75 medijana, mjeren na
    samom clanku, jer sirina stupca varira od casopisa do casopisa.

    Vraca parove (tekst, je_podnaslov).
    """
    duljine = sorted(len(r) for r in retci if len(r) > 20)
    if not duljine:
        return [(r, _je_podnaslov(r)) for r in retci if r]
    medijan = duljine[len(duljine) // 2]
    prag = max(28, int(medijan * 0.75))

    odlomci: list[tuple[str, bool]] = []
    buf = ""

    def zatvori():
        nonlocal buf
        if buf.strip():
            odlomci.append((re.sub(r"\s+", " ", buf).strip(), False))
        buf = ""

    for r in retci:
        if _je_podnaslov(r):
            zatvori()
            odlomci.append((r, True))
            continue
        buf += (" " if buf else "") + r
        if len(r) < prag:                 # kratak redak zatvara odlomak
            zatvori()
    zatvori()
    return odlomci


def cankiraj_clanak(tekst: str) -> list[str]:
    """
    Lomi znanstveni clanak na canke po podnaslovima i odlomcima.

    Svakom canku se na celo stavlja najblizi podnaslov, ako ga canak vec ne
    sadrzi. Bez toga canak iz sredine clanka gubi kontekst: recenica "u tom je
    slucaju rok deset godina" ne kaze o kojem se roku radi, a podnaslov
    "3.2. Dosjelost nekretnina" to popravlja uz desetak znakova troska.
    """
    retci = _ocisti_pdf(tekst)
    if not retci:
        return []

    # odsijeci popis literature, ali samo ako je u zadnjem dijelu clanka
    for i, r in enumerate(retci):
        if RE_LITERATURA.match(r) and i > len(retci) * 0.4:
            retci = retci[:i]
            break

    odlomci = _u_odlomke(retci)

    # svakom odlomku pridruzi podnaslov ispod kojega stoji
    parovi: list[tuple[str, str]] = []
    zadnji_naslov = ""
    for txt, je_naslov in odlomci:
        if je_naslov:
            zadnji_naslov = txt.strip()
            continue
        if len(txt) < 40:                 # ostatak izvlacenja, a ne odlomak
            continue
        parovi.append((zadnji_naslov, txt))

    if not parovi:                        # nista se nije slozilo; ne gubi tekst
        parovi = [("", t) for t, _ in odlomci if len(t) >= 40]
    return _spakiraj_doktrinu(parovi)


def _spakiraj_doktrinu(parovi: list[tuple[str, str]]) -> list[str]:
    """
    Kao `_spakiraj`, ali podnaslov ide na celo canka i to tocno jednom.

    Prefiksiranje svakog odlomka posebno bi isti podnaslov ponovilo tri ili
    cetiri puta unutar jednog canka, sto trosi granicu modela i razrjeduje
    embedding. Zato naslov nosi canak, a ne odlomak.
    """
    def celo(naslov: str, tijelo: str) -> str:
        if naslov and naslov.lower() not in tijelo[:120].lower():
            return f"{naslov}\n{tijelo}"
        return tijelo

    cankovi: list[str] = []
    buf, naslov_buf = "", ""

    for naslov, seg in parovi:
        if not seg:
            continue
        # odlomak koji sam po sebi prelazi granicu razbija se tvrdo
        if len(seg) + len(naslov) + 1 > MAX_ZNAKOVA:
            if buf:
                cankovi.append(celo(naslov_buf, buf.strip()))
                buf = ""
            korak = CILJ_ZNAKOVA - PREKLOP
            for i in range(0, len(seg), korak):
                cankovi.append(celo(naslov, seg[i:i + CILJ_ZNAKOVA].strip()))
            naslov_buf = naslov
            continue
        if not buf:
            naslov_buf = naslov
        if len(buf) + len(seg) + len(naslov_buf) + 2 > CILJ_ZNAKOVA and buf:
            cankovi.append(celo(naslov_buf, buf.strip()))
            buf = buf[-PREKLOP:] if len(buf) > PREKLOP else ""
            naslov_buf = naslov
        buf += ("\n" if buf else "") + seg
    if buf.strip():
        cankovi.append(celo(naslov_buf, buf.strip()))

    sigurni = []
    for c in cankovi:
        if len(c) <= MAX_ZNAKOVA:
            sigurni.append(c)
        else:
            korak = MAX_ZNAKOVA - PREKLOP
            sigurni += [c[i:i + MAX_ZNAKOVA] for i in range(0, len(c), korak)]
    return [c.strip() for c in sigurni if len(c.strip()) > 60]


# ----------------------------------------------------------------- model ---

_model = None


def model():
    global _model
    if _model is None:
        import os
        from sentence_transformers import SentenceTransformer
        import torch
        # izmjereno na ovom stroju (4 jezgre / 8 dretvi): 8 dretvi ~210 ms/čanak,
        # 2 dretve ~263 ms — uzimamo sve što ima
        torch.set_num_threads(os.cpu_count() or 4)
        log(f"[i] učitavam model {MODEL_NAME} (CPU, x86_64)…")
        _model = SentenceTransformer(MODEL_NAME, device="cpu")
        _model.max_seq_length = 512
    return _model


def ugradi(tekstovi: list[str], *, upit: bool = False,
           prefiks: str | None = None, napredak: bool | None = None) -> np.ndarray:
    """
    e5 traži prefikse: 'query: ' za upit, 'passage: ' za dokument.

    `prefiks` nadjačava `upit` i time dopušta ugradnju proizvoljnog teksta pod
    bilo kojim prefiksom. Za HyDE ulomak to je 'passage', jer se pseudodokument
    uspoređuje s dokumentima; zamjena prefiksa mjerljivo kvari e5.
    """
    p = prefiks if prefiks is not None else ("query" if upit else "passage")
    if p not in PREFIKSI:
        raise ValueError(f"Nepoznat prefiks {p!r}; dopušteno: {PREFIKSI}")
    prikazi = (not upit) if napredak is None else bool(napredak)
    v = model().encode([p + ": " + t for t in tekstovi], batch_size=BATCH,
                       normalize_embeddings=True, show_progress_bar=prikazi)
    return np.asarray(v, dtype=np.float32)


def _pack(v: np.ndarray) -> bytes:
    return struct.pack(f"<{len(v)}f", *v.astype(np.float32))


def _unpack(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype="<f4")


def _u_grupama(niz, n: int):
    """SQLite ima strop na broj parametara, pa IN (...) ide u obrocima."""
    for i in range(0, len(niz), n):
        yield niz[i:i + n]


# --------------------------------------------------------------- indeks ----

def priprema(con: sqlite3.Connection) -> None:
    con.executescript(SHEMA)
    try:
        con.executescript(FTS)
    except sqlite3.OperationalError as e:
        log(f"  [!] FTS5 nedostupan ({e}) — hibrid će raditi samo vektorski.")
    con.commit()


def _vec_indeksirani(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT DISTINCT doc_id FROM chunks")}


def _odaberi_za_indeks(con: sqlite3.Connection, *, doc_ids=None,
                       limit: int | None = None, ponovno: bool = False):
    """
    Vraća (novi, vec, ukupno, nedostaju).

    Bez `doc_ids` gleda cijeli korpus, kao i dosad. S `doc_ids` gleda samo te
    odluke i čuva redoslijed kojim su zadane, da se zlatni skup indeksira
    predvidljivim redom.
    """
    vec = _vec_indeksirani(con)
    if doc_ids is None:
        red = con.execute("SELECT id, tekst, gradivo FROM odluke").fetchall()
        ukupno, nedostaju = len(red), []
    else:
        trazeni = list(dict.fromkeys(
            str(x).strip() for x in doc_ids if str(x).strip()))
        po_id = {}
        for grupa in _u_grupama(trazeni, 400):
            ozn = ",".join("?" * len(grupa))
            for r in con.execute(
                    f"SELECT id, tekst, gradivo FROM odluke WHERE id IN ({ozn})",
                    grupa):
                po_id[r["id"]] = r
        red = [po_id[i] for i in trazeni if i in po_id]
        ukupno = len(trazeni)
        nedostaju = [i for i in trazeni if i not in po_id]

    novi = [r for r in red
            if (r["tekst"] or "").strip() and (ponovno or r["id"] not in vec)]
    if limit:
        novi = novi[:limit]
    return novi, vec, ukupno, nedostaju


def index(*, limit: int | None = None, doc_ids=None, ponovno: bool = False,
          con: sqlite3.Connection | None = None) -> int:
    """
    Čankira i vektorizira odluke. Vraća broj upisanih čankova.

    doc_ids  samo te odluke (podskup: zlatni skup, kandidati jednog instituta)
    ponovno  briše postojeće čanke tih odluka i gradi ih iznova
    con      već otvorena veza; bez nje se otvara zadani korpus
    """
    if con is None:
        con = store.veza()
    priprema(con)

    novi, vec, ukupno, nedostaju = _odaberi_za_indeks(
        con, doc_ids=doc_ids, limit=limit, ponovno=ponovno)
    if nedostaju:
        log(f"  [!] {len(nedostaju)} id-eva nije u korpusu: "
            f"{', '.join(nedostaju[:5])}{' ...' if len(nedostaju) > 5 else ''}")

    naslov = ("Korpus" if doc_ids is None else "Podskup")
    log(f"{naslov}: {ukupno} odluka | već indeksirano: {len(vec)} | novo: {len(novi)}")
    if not novi:
        log("Nema novih odluka za indeksiranje.")
        return 0

    if ponovno:
        stari = [r["id"] for r in novi if r["id"] in vec]
        for grupa in _u_grupama(stari, 400):
            ozn = ",".join("?" * len(grupa))
            con.execute(f"DELETE FROM chunks WHERE doc_id IN ({ozn})", grupa)
        if stari:
            con.commit()
            log(f"  [i] obrisani čankovi {len(stari)} odluka za ponovno građenje.")

    # Kodiramo grupirano PREKO odluka, ne po odluci: odluka s 4 čanka inače daje
    # sitan batch i režija modela pojede dobitak. Mjereno ~210 ms/čanak.
    import time

    def isprazni(spremnik: list[tuple[str, int, str]]) -> int:
        if not spremnik:
            return 0
        embs = ugradi([c for _, _, c in spremnik])
        con.executemany(
            "INSERT OR REPLACE INTO chunks (doc_id, ord, tekst, emb) VALUES (?,?,?,?)",
            [(d, o, c, _pack(embs[i])) for i, (d, o, c) in enumerate(spremnik)])
        con.commit()
        return len(spremnik)

    GRUPA = 128
    spremnik: list[tuple[str, int, str]] = []
    ukupno_ch, obradeno, t0 = 0, 0, time.time()

    for n, r in enumerate(novi, 1):
        # gradivo bira granu cankiranja; stare baze bez tog stupca daju 'odluka'
        vrsta = (r["gradivo"] if "gradivo" in r.keys() else None) or "odluka"
        for i, c in enumerate(cankiraj(r["tekst"], vrsta)):
            spremnik.append((r["id"], i, c))
        obradeno = n
        if len(spremnik) >= GRUPA:
            ukupno_ch += isprazni(spremnik)
            spremnik = []
            proteklo = time.time() - t0
            brzina = ukupno_ch / max(proteklo, 1e-6)
            preostalo = (len(novi) - n) / max(n, 1) * proteklo
            log(f"  [{n}/{len(novi)} odluka] {ukupno_ch} čankova | "
                f"{brzina:.1f} čankova/s | preostalo ~{preostalo/60:.0f} min")

    ukupno_ch += isprazni(spremnik)
    log(f"  [{obradeno}/{len(novi)} odluka] {ukupno_ch} čankova ukupno "
        f"za {(time.time()-t0)/60:.1f} min")

    # napuni FTS nad čancima
    try:
        con.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        con.commit()
        log("  [i] BM25 indeks nad čancima obnovljen.")
    except sqlite3.OperationalError:
        pass
    log(f"Gotovo: +{ukupno_ch} čankova.")
    return ukupno_ch


def index_skup(doc_ids, *, ponovno: bool = False, limit: int | None = None,
               con: sqlite3.Connection | None = None) -> int:
    """
    Indeksira SAMO zadane odluke. Zlatni skup i kandidati jednog instituta
    time se dobiju u minutama umjesto da se čeka cijeli korpus (~4,2 h).
    """
    doc_ids = list(doc_ids or [])
    if not doc_ids:
        log("[!] Nije zadan nijedan id.")
        return 0
    return index(doc_ids=doc_ids, ponovno=ponovno, limit=limit, con=con)


def ucitaj_ideve(putanja: str) -> list[str]:
    """
    Čita id-eve iz datoteke: jedan po retku, ili JSON (popis nizova, ili
    popis zapisa s poljem "id"). '#' uvodi komentar, '-' čita sa stdin-a.
    """
    if putanja == "-":
        sadrzaj = sys.stdin.read()
    else:
        with open(putanja, encoding="utf-8") as f:
            sadrzaj = f.read()
    try:
        podatak = json.loads(sadrzaj)
    except ValueError:
        podatak = None
    if isinstance(podatak, dict):
        podatak = podatak.get("id") or podatak.get("odluke") or []
    if isinstance(podatak, list):
        izlaz = []
        for e in podatak:
            if isinstance(e, dict):
                e = e.get("id") or e.get("doc_id") or ""
            if str(e).strip():
                izlaz.append(str(e).strip())
        return list(dict.fromkeys(izlaz))

    izlaz = []
    for redak in sadrzaj.splitlines():
        redak = redak.split("#", 1)[0]
        for komad in re.split(r"[\s,;]+", redak):
            if komad.strip():
                izlaz.append(komad.strip())
    return list(dict.fromkeys(izlaz))


# --------------------------------------------------------------- upiti ----

def _sazmi(t: str, n: int = 56) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[:n - 3].rstrip() + "..."


@dataclasses.dataclass
class Upit:
    """
    Jedan upit u snopu.

    tekst    ono što se traži
    grana    "hibrid" | "vektor" | "bm25"
    prefiks  "query" (pitanje) | "passage" (pseudodokument, HyDE)
    tezina   množitelj RRF doprinosa; 1.0 je neutralno
    oznaka   ime upita u objašnjenju (npr. institut iz sloja 1)

    Ograda: prefiks "passage" nikad ne ide u BM25. Uz "hibrid" se tiho svodi na
    vektorsku granu, uz izričit "bm25" je greška.
    """
    tekst: str
    grana: str = "hibrid"
    prefiks: str = "query"
    tezina: float = 1.0
    oznaka: str = ""

    def __post_init__(self) -> None:
        self.tekst = (self.tekst or "").strip()
        if not self.tekst:
            raise ValueError("Upit bez teksta.")
        if self.grana not in GRANE:
            raise ValueError(f"Nepoznata grana {self.grana!r}; dopušteno: {GRANE}")
        if self.prefiks not in PREFIKSI:
            raise ValueError(f"Nepoznat prefiks {self.prefiks!r}; dopušteno: {PREFIKSI}")
        self.tezina = float(self.tezina)
        if self.prefiks == "passage":
            if self.grana == "bm25":
                raise ValueError(
                    "Ulomak s prefiksom 'passage' je izmišljen tekst i ne smije "
                    "u BM25 granu; ondje bi pogrešan broj članka bio lažni "
                    "pogodak s visokim rangom.")
            self.grana = "vektor"
        if not self.oznaka:
            self.oznaka = _sazmi(self.tekst)

    @classmethod
    def hyde(cls, tekst: str, *, oznaka: str = "", tezina: float = 1.0) -> "Upit":
        """Hipotetski ulomak obrazloženja: ugrađuje se kao pseudodokument."""
        return cls(tekst, grana="vektor", prefiks="passage",
                   tezina=tezina, oznaka=oznaka or "hyde: " + _sazmi(tekst, 44))

    @property
    def kljuc(self) -> tuple:
        return (self.tekst, self.grana, self.prefiks)


def upiti_od(x) -> list[Upit]:
    """
    Normalizira ulaz u popis Upit-a. Prima niz znakova, Upit, rječnik s poljima
    Upit-a, ili bilo koju kombinaciju tih u popisu. Istovjetni upiti (isti
    tekst, grana i prefiks) se odbacuju, jer bi u RRF-u dvostruko bodovali isti
    čanak i tiho iskrivili poredak.
    """
    if x is None:
        return []
    if isinstance(x, (str, Upit, dict)):
        x = [x]
    izlaz, vidjeni = [], set()
    for e in x:
        if isinstance(e, Upit):
            u = e
        elif isinstance(e, dict):
            u = Upit(**e)
        else:
            u = Upit(str(e))
        if u.kljuc in vidjeni:
            continue
        vidjeni.add(u.kljuc)
        izlaz.append(u)
    return izlaz


# -------------------------------------------------------------- pretraga --

@dataclasses.dataclass
class Podrijetlo:
    """Odakle je jedan pogodak došao: koji upit, koja grana, koji rang."""
    upit: str
    grana: str
    rang: int
    doprinos: float
    sirovo: float
    tekst_upita: str = ""


@dataclasses.dataclass
class Pogodak:
    cank_id: int
    ocjena: float
    podrijetlo: list
    doc_id: str = ""
    ord: int = -1
    tekst: str = ""
    sud: str = ""
    broj: str = ""
    datum: str = ""
    url: str = ""
    pravomocnost: str = ""

    @property
    def upiti(self) -> list[str]:
        """Oznake upita koji su doveli ovaj čanak, po padajućem doprinosu."""
        return list(dict.fromkeys(
            p.upit for p in sorted(self.podrijetlo, key=lambda p: -p.doprinos)))

    @property
    def grane(self) -> list[str]:
        return list(dict.fromkeys(
            p.grana for p in sorted(self.podrijetlo, key=lambda p: -p.doprinos)))

    def objasnjenje(self, n: int = 3) -> str:
        """Jedan redak: 'upit [grana #rang]' za n najjačih doprinosa."""
        redom = sorted(self.podrijetlo, key=lambda p: -p.doprinos)[:n]
        return " + ".join(f"{p.upit} [{p.grana} #{p.rang}]" for p in redom)


def _bm25(con, q: str, k: int) -> list[tuple[int, float]]:
    try:
        rows = con.execute(
            "SELECT rowid, bm25(chunks_fts) r FROM chunks_fts "
            "WHERE chunks_fts MATCH ? ORDER BY r LIMIT ?", (q, k)).fetchall()
        return [(int(x[0]), float(x[1])) for x in rows]
    except sqlite3.OperationalError as e:
        # nepostojeći chunks_fts je uredno stanje (SQLite bez FTS5); loša
        # sintaksa upita nije, i ne smije nestati bez traga
        if "no such table" not in str(e).lower():
            log(f"  [!] BM25 upit odbijen ({e}): {_sazmi(q)}")
        return []


def _ucitaj_embeddinge(con) -> tuple[np.ndarray | None, np.ndarray | None]:
    rows = con.execute("SELECT id, emb FROM chunks WHERE emb IS NOT NULL").fetchall()
    if not rows:
        return None, None
    ids = np.array([r[0] for r in rows])
    M = np.vstack([_unpack(r[1]) for r in rows])
    return ids, M


def _rangiraj(ids, M, qv: np.ndarray, k: int) -> list[tuple[int, float]]:
    if ids is None or M is None or len(ids) == 0:
        return []
    sims = M @ qv
    top = np.argsort(-sims)[:k]
    return [(int(ids[i]), float(sims[i])) for i in top]


def _vektor(con, q: str, k: int, *, prefiks: str = "query") -> list[tuple[int, float]]:
    ids, M = _ucitaj_embeddinge(con)
    if ids is None:
        return []
    qv = ugradi([q], prefiks=prefiks, napredak=False)[0]
    return _rangiraj(ids, M, qv, k)


def _broj_chunkova(con) -> int:
    try:
        return con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def _ugradi_snop(upiti: list[Upit]) -> dict[int, np.ndarray]:
    """Ugrađuje sve vektorske upite odjednom, grupirano po prefiksu."""
    po_prefiksu: dict[str, list[int]] = {}
    for i, u in enumerate(upiti):
        if u.grana in ("hibrid", "vektor"):
            po_prefiksu.setdefault(u.prefiks, []).append(i)
    vektori: dict[int, np.ndarray] = {}
    for pref, mjesta in po_prefiksu.items():
        E = ugradi([upiti[i].tekst for i in mjesta], prefiks=pref, napredak=False)
        for i, v in zip(mjesta, E):
            vektori[i] = v
    return vektori


def pretrazi(upiti, k: int = 8, *, con: sqlite3.Connection | None = None,
             dubina: int | None = None, rrf_k: int = RRF_K,
             meta: bool = True) -> list[Pogodak]:
    """
    Snop upita -> rangirani čankovi, spojeni RRF-om PREKO upita i grana.

    Ocjena čanka je zbroj tezina/(rrf_k + rang) po svakoj listi u kojoj se
    pojavio. Isti postupak koji spaja BM25 i vektor spaja i upite, pa je jedan
    upit poseban slučaj snopa i poredak je istovjetan starom ponašanju.

    Svaki Pogodak nosi `podrijetlo`: popis Podrijetlo zapisa s oznakom upita,
    granom, rangom i doprinosom. To je jedini način da se poslije zna KOJI je
    upit donio koju presudu, bez čega ablacije iz sloja 6 nemaju što mjeriti.

    con   već otvorena veza (npr. store.otvori_ro za mjerenje, bez migracije);
          bez nje se otvara zadani korpus i priprema shema
    """
    snop = upiti_od(upiti)
    if not snop:
        return []
    if con is None:
        con = store.veza()
        priprema(con)
    if _broj_chunkova(con) == 0:
        return []

    d = max(int(dubina or k * DUBINA_MNOZITELJ), 1)
    vektori = _ugradi_snop(snop)
    ids, M = _ucitaj_embeddinge(con) if vektori else (None, None)

    bod: dict[int, float] = {}
    trag: dict[int, list[Podrijetlo]] = {}

    def dodaj(cid: int, u: Upit, grana: str, rang: int, sirovo: float) -> None:
        doprinos = u.tezina / (rrf_k + rang)
        bod[cid] = bod.get(cid, 0.0) + doprinos
        trag.setdefault(cid, []).append(
            Podrijetlo(upit=u.oznaka, grana=grana, rang=rang,
                       doprinos=doprinos, sirovo=sirovo, tekst_upita=u.tekst))

    for i, u in enumerate(snop):
        if u.grana in ("hibrid", "bm25"):
            for rang, (cid, s) in enumerate(_bm25(con, u.tekst, d), 1):
                dodaj(cid, u, "bm25", rang, s)
        if u.grana in ("hibrid", "vektor"):
            for rang, (cid, s) in enumerate(_rangiraj(ids, M, vektori[i], d), 1):
                dodaj(cid, u, "vektor", rang, s)

    poredak = sorted(bod.items(), key=lambda x: -x[1])[:k]
    if not poredak:
        return []

    redovi = {}
    if meta:
        for grupa in _u_grupama([cid for cid, _ in poredak], 400):
            ozn = ",".join("?" * len(grupa))
            for r in con.execute(
                    f"""SELECT c.id, c.doc_id, c.ord, c.tekst, o.sud, o.broj,
                               o.datum, o.url, o.pravomocnost
                          FROM chunks c JOIN odluke o ON o.id = c.doc_id
                         WHERE c.id IN ({ozn})""", grupa):
                redovi[r["id"]] = r

    izlaz = []
    for cid, ocjena in poredak:
        r = redovi.get(cid)
        if meta and r is None:          # čanak bez odluke: preskačemo, kao i dosad
            continue
        p = Pogodak(cank_id=cid, ocjena=ocjena,
                    podrijetlo=sorted(trag[cid], key=lambda x: -x.doprinos))
        if r is not None:
            p.doc_id = r["doc_id"]; p.ord = r["ord"]; p.tekst = r["tekst"]
            p.sud = r["sud"] or ""; p.broj = r["broj"] or ""
            p.datum = r["datum"] or ""; p.url = r["url"] or ""
            p.pravomocnost = r["pravomocnost"] or ""
        izlaz.append(p)
    return izlaz


def objasni(pogotci) -> list[dict]:
    """
    Podrijetlo pogodaka u obliku spremnom za JSON i za mjerne tablice:
    za svaki čanak koja ga je odluka, koji upiti i koje grane donijele.

    Ovo je ulaz u ablacije iz sloja 6: bez podatka koji je upit donio kojeg
    zlatnog, isključivanje sloja mjeri samo zbroj, a ne uzrok.
    """
    if isinstance(pogotci, Pogodak):
        pogotci = [pogotci]
    izlaz = []
    for rang, p in enumerate(pogotci, 1):
        izlaz.append({
            "rang": rang,
            "cank_id": p.cank_id,
            "doc_id": p.doc_id,
            "ord": p.ord,
            "ocjena": round(p.ocjena, 6),
            "sud": p.sud,
            "broj": p.broj,
            "upiti": p.upiti,
            "grane": p.grane,
            "podrijetlo": [dataclasses.asdict(x) for x in p.podrijetlo],
        })
    return izlaz


def query(q: str | None, k: int = 8, nacin: str = "hibrid", *,
          upiti=None, hyde=None, objasnjenje: bool = False,
          con: sqlite3.Connection | None = None) -> list[Pogodak]:
    """
    Ispisuje pogotke. `q` je vodeći upit, `upiti` dodatni upiti iste grane,
    `hyde` hipotetski ulomci koji idu samo u vektorsku granu.
    """
    if con is None:
        con = store.veza()
        priprema(con)

    n_ch = _broj_chunkova(con)
    if n_ch == 0:
        log("[!] Indeks je prazan — prvo: python vektor.py index")
        return []

    snop: list[Upit] = []
    if q:
        snop.append(Upit(q, grana=nacin))
    for t in (upiti or []):
        snop.append(t if isinstance(t, Upit) else Upit(str(t), grana=nacin))
    for t in (hyde or []):
        snop.append(t if isinstance(t, Upit) else Upit.hyde(str(t)))
    snop = upiti_od(snop)
    if not snop:
        log("[!] Nema nijednog upita.")
        return []

    pogotci = pretrazi(snop, k, con=con)
    if not pogotci:
        log("Nema pogodaka.")
        return []

    if len(snop) == 1:
        log(f"\n=== {nacin.upper()} — {snop[0].tekst!r} — "
            f"{len(pogotci)} isječaka ===")
    else:
        log(f"\n=== {nacin.upper()} — snop od {len(snop)} upita — "
            f"{len(pogotci)} isječaka ===")
        for u in snop:
            log(f"     - [{u.grana}/{u.prefiks} x{u.tezina:g}] {u.oznaka}")

    for rang, p in enumerate(pogotci, 1):
        log(f"\n#{rang}  [{p.ocjena:.4f}]  {p.sud} — {p.broj} ({p.datum})")
        log(f"     {p.pravomocnost}")
        log(f"     {p.url}")
        if objasnjenje:
            log(f"     iz: {p.objasnjenje()}")
        isj = re.sub(r"\s+", " ", p.tekst)[:600]
        log(f"     »{isj}«")
    return pogotci


def stat(con: sqlite3.Connection | None = None) -> None:
    if con is None:
        con = store.veza()
        priprema(con)
    n_od = con.execute("SELECT COUNT(*) FROM odluke").fetchone()[0]
    n_ch = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    n_dok = con.execute("SELECT COUNT(DISTINCT doc_id) FROM chunks").fetchone()[0]
    log(f"Odluka u korpusu:        {n_od}")
    log(f"Odluka indeksirano:      {n_dok}")
    log(f"Čankova:                 {n_ch}")
    if n_ch:
        log(f"Prosj. čankova/odluci:   {n_ch / max(1, n_dok):.1f}")
        log(f"Veličina embeddinga:     ~{n_ch * DIM * 4 / 1024 / 1024:.1f} MB")
        log(f"Pokrivenost korpusa:     {100.0 * n_dok / max(1, n_od):.1f} %")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("index"); pi.add_argument("--limit", type=int)

    ps = sub.add_parser("index-skup",
                        help="indeksiraj SAMO zadane odluke (po id-u)")
    ps.add_argument("id", nargs="*", help="id odluke; može ih biti više")
    ps.add_argument("--iz-datoteke", dest="datoteka",
                    help="datoteka s id-evima (redak po redak ili JSON); '-' je stdin")
    ps.add_argument("--ponovno", action="store_true",
                    help="obriši postojeće čanke tih odluka i izgradi ih iznova")
    ps.add_argument("--limit", type=int)

    pq = sub.add_parser("query")
    pq.add_argument("text", nargs="?")
    pq.add_argument("-k", type=int, default=8)
    pq.add_argument("--nacin", choices=["hibrid", "vektor", "bm25"], default="hibrid")
    pq.add_argument("--upit", action="append", default=[],
                    help="dodatni upit u snopu; može se ponoviti")
    pq.add_argument("--hyde", action="append", default=[],
                    help="hipotetski ulomak (passage); ide samo u vektorsku granu")
    pq.add_argument("--objasni", action="store_true",
                    help="uz svaki pogodak ispiši iz kojeg je upita došao")
    sub.add_parser("stat")
    a = ap.parse_args()

    if a.cmd == "index":
        index(limit=a.limit)
    elif a.cmd == "index-skup":
        ideve = list(a.id)
        if a.datoteka:
            ideve += ucitaj_ideve(a.datoteka)
        ideve = [x for komad in ideve for x in re.split(r"[\s,;]+", komad) if x]
        if not ideve:
            ap.error("index-skup traži barem jedan id ili --iz-datoteke")
        index_skup(ideve, ponovno=a.ponovno, limit=a.limit)
    elif a.cmd == "query":
        if not (a.text or a.upit or a.hyde):
            ap.error("query traži tekst upita, --upit ili --hyde")
        query(a.text, a.k, a.nacin, upiti=a.upit, hyde=a.hyde,
              objasnjenje=a.objasni)
    else:
        stat()


if __name__ == "__main__":
    sys.exit(main())
