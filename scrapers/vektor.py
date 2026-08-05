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
- Inkrementalno: već indeksirane odluke se preskaču, kao i kod harvesta.
- Model: intfloat/multilingual-e5-small (384 dim). Traži prefikse
  "query: " / "passage: " — bez njih kvaliteta osjetno pada.

Pokretanje
----------
    python vektor.py index                     # čankiraj + vektoriziraj (inkrementalno)
    python vektor.py query "zamjena škart zemljišta za građevinsko" -k 8
    python vektor.py query "..." --nacin vektor     # samo semantički
    python vektor.py query "..." --nacin bm25       # samo doslovno
    python vektor.py stat
"""
from __future__ import annotations

import argparse
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


def cankiraj(tekst: str) -> list[str]:
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

    # spakiraj segmente u čanke ciljane veličine
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


def ugradi(tekstovi: list[str], *, upit: bool = False) -> np.ndarray:
    """e5 traži prefikse: 'query: ' za upit, 'passage: ' za dokument."""
    pref = "query: " if upit else "passage: "
    v = model().encode([pref + t for t in tekstovi], batch_size=BATCH,
                       normalize_embeddings=True, show_progress_bar=not upit)
    return np.asarray(v, dtype=np.float32)


def _pack(v: np.ndarray) -> bytes:
    return struct.pack(f"<{len(v)}f", *v.astype(np.float32))


def _unpack(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype="<f4")


# --------------------------------------------------------------- indeks ----

def priprema(con: sqlite3.Connection) -> None:
    con.executescript(SHEMA)
    try:
        con.executescript(FTS)
    except sqlite3.OperationalError as e:
        log(f"  [!] FTS5 nedostupan ({e}) — hibrid će raditi samo vektorski.")
    con.commit()


def index(*, limit: int | None = None) -> None:
    con = store.veza()
    priprema(con)

    vec = con.execute("SELECT DISTINCT doc_id FROM chunks").fetchall()
    vec = {r[0] for r in vec}
    red = con.execute("SELECT id, tekst FROM odluke").fetchall()
    novi = [r for r in red if r["id"] not in vec and (r["tekst"] or "").strip()]
    if limit:
        novi = novi[:limit]

    log(f"Korpus: {len(red)} odluka | već indeksirano: {len(vec)} | novo: {len(novi)}")
    if not novi:
        log("Nema novih odluka za indeksiranje.")
        return

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
    ukupno, obradeno, t0 = 0, 0, time.time()

    for n, r in enumerate(novi, 1):
        for i, c in enumerate(cankiraj(r["tekst"])):
            spremnik.append((r["id"], i, c))
        obradeno = n
        if len(spremnik) >= GRUPA:
            ukupno += isprazni(spremnik)
            spremnik = []
            proteklo = time.time() - t0
            brzina = ukupno / max(proteklo, 1e-6)
            preostalo = (len(novi) - n) / max(n, 1) * proteklo
            log(f"  [{n}/{len(novi)} odluka] {ukupno} čankova | "
                f"{brzina:.1f} čankova/s | preostalo ~{preostalo/60:.0f} min")

    ukupno += isprazni(spremnik)
    log(f"  [{obradeno}/{len(novi)} odluka] {ukupno} čankova ukupno "
        f"za {(time.time()-t0)/60:.1f} min")

    # napuni FTS nad čancima
    try:
        con.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        con.commit()
        log("  [i] BM25 indeks nad čancima obnovljen.")
    except sqlite3.OperationalError:
        pass
    log(f"Gotovo: +{ukupno} čankova.")


# -------------------------------------------------------------- pretraga --

def _bm25(con, q: str, k: int) -> list[tuple[int, float]]:
    try:
        rows = con.execute(
            "SELECT rowid, bm25(chunks_fts) r FROM chunks_fts "
            "WHERE chunks_fts MATCH ? ORDER BY r LIMIT ?", (q, k)).fetchall()
        return [(int(x[0]), float(x[1])) for x in rows]
    except sqlite3.OperationalError:
        return []


def _vektor(con, q: str, k: int) -> list[tuple[int, float]]:
    rows = con.execute("SELECT id, emb FROM chunks WHERE emb IS NOT NULL").fetchall()
    if not rows:
        return []
    ids = np.array([r[0] for r in rows])
    M = np.vstack([_unpack(r[1]) for r in rows])
    qv = ugradi([q], upit=True)[0]
    sims = M @ qv
    top = np.argsort(-sims)[:k]
    return [(int(ids[i]), float(sims[i])) for i in top]


def query(q: str, k: int = 8, nacin: str = "hibrid") -> None:
    con = store.veza()
    priprema(con)

    n_ch = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    if n_ch == 0:
        log("[!] Indeks je prazan — prvo: python vektor.py index")
        return

    kandidati: dict[int, float] = {}
    if nacin in ("hibrid", "bm25"):
        for rank, (cid, _) in enumerate(_bm25(con, q, k * 5), 1):
            kandidati[cid] = kandidati.get(cid, 0.0) + 1.0 / (60 + rank)   # RRF
    if nacin in ("hibrid", "vektor"):
        for rank, (cid, _) in enumerate(_vektor(con, q, k * 5), 1):
            kandidati[cid] = kandidati.get(cid, 0.0) + 1.0 / (60 + rank)

    if not kandidati:
        log("Nema pogodaka.")
        return

    poredak = sorted(kandidati.items(), key=lambda x: -x[1])[:k]
    log(f"\n=== {nacin.upper()} — {q!r} — {len(poredak)} isječaka ===")
    for rang, (cid, score) in enumerate(poredak, 1):
        r = con.execute(
            "SELECT c.tekst, c.ord, o.sud, o.broj, o.datum, o.url, o.pravomocnost "
            "FROM chunks c JOIN odluke o ON o.id = c.doc_id WHERE c.id=?",
            (cid,)).fetchone()
        if not r:
            continue
        log(f"\n#{rang}  [{score:.4f}]  {r['sud']} — {r['broj']} ({r['datum']})")
        log(f"     {r['pravomocnost']}")
        log(f"     {r['url']}")
        isj = re.sub(r"\s+", " ", r["tekst"])[:600]
        log(f"     »{isj}«")


def stat() -> None:
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("index"); pi.add_argument("--limit", type=int)
    pq = sub.add_parser("query")
    pq.add_argument("text")
    pq.add_argument("-k", type=int, default=8)
    pq.add_argument("--nacin", choices=["hibrid", "vektor", "bm25"], default="hibrid")
    sub.add_parser("stat")
    a = ap.parse_args()
    if a.cmd == "index":
        index(limit=a.limit)
    elif a.cmd == "query":
        query(a.text, a.k, a.nacin)
    else:
        stat()


if __name__ == "__main__":
    sys.exit(main())
