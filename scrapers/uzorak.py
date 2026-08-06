# -*- coding: utf-8 -*-
"""
Gradi mali, ponovljiv uzorak korpusa (data/uzorak.sqlite) za temu suma i
zamjene zemljista.

Uzorak ima istu shemu kao puni korpus (store.SHEMA + store.FTS_SHEMA), pa nad
njim rade isti alati (store.trazi, store.statistika). Sluzi da netko moze
isprobati pretragu odmah, bez skidanja ijedne odluke s portala.

Izbor je determiniran: za svaku tematsku FTS5 frazu uzima se najboljih N
pogodaka po BM25 rangu, uz stabilan tie-break po ID-u. Isti korpus daje isti
uzorak pri svakom pokretanju.

Izvorna baza se otvara read-only i nikada se ne mijenja.

    ./venv/bin/python uzorak.py                      # izgradi uzorak iz korpusa
    ./venv/bin/python uzorak.py --ukupno 25          # ciljni broj odluka
    ./venv/bin/python uzorak.py --trazi "sumsko zemljiste"   # pretrazi uzorak
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys

from common import DATA_DIR
import store

IZVOR_DB = DATA_DIR / "corpus.sqlite"
UZORAK_DB = DATA_DIR / "uzorak.sqlite"

# (FTS5 upit, koliko najboljih uzeti). Redoslijed je i prioritet pri punjenju
# kvote: prve teme su najuze vezane uz zamjenu zemljista.
TEME: list[tuple[str, int]] = [
    ('"zamjena zemljista" OR "zamjeni zemljista" OR "zamjenu zemljista"', 6),
    ('zamjen* AND "sumskog zemljista"', 6),
    ('"izdvajanje iz sumskogospodarskog podrucja"', 4),
    ('"clanka 55" AND suma', 4),
    ('"suma i sumskih zemljista"', 4),
    ('komasacij*', 3),
]

# Gornja granica duljine teksta jedne odluke; nekoliko odluka u korpusu ima
# preko 700 kB i same bi napuhale uzorak preko granice od 5 MB.
MAX_ZNAKOVA = 120_000


def odaberi(con: sqlite3.Connection, ukupno: int) -> list[str]:
    """Vraca determiniran popis ID-eva odluka za uzorak."""
    odabrani: list[str] = []
    vidjeni: set[str] = set()

    for upit, kvota in TEME:
        redci = con.execute(
            """SELECT o.id, bm25(odluke_fts) AS rang
                 FROM odluke_fts JOIN odluke o ON o.rowid = odluke_fts.rowid
                WHERE odluke_fts MATCH ?
                  AND length(o.tekst) BETWEEN 500 AND ?
                ORDER BY rang, o.id
                LIMIT ?""",
            (upit, MAX_ZNAKOVA, kvota * 4),
        ).fetchall()

        uzeto = 0
        for r in redci:
            if uzeto >= kvota or len(odabrani) >= ukupno:
                break
            if r["id"] in vidjeni:
                continue
            vidjeni.add(r["id"])
            odabrani.append(r["id"])
            uzeto += 1
        print(f"  {upit[:52]:<54} +{uzeto}")

    return odabrani[:ukupno]


def izgradi(izvor: pathlib.Path, izlaz: pathlib.Path, ukupno: int) -> int:
    if not izvor.exists():
        sys.exit(f"Izvorna baza ne postoji: {izvor}")

    # read-only, da se puni korpus ni slucajno ne dira. store.otvori_ro
    # registrira i `odzipaj`, bez kojeg pogled `odluke` ne moze citati
    # komprimirani tekst.
    src = store.otvori_ro(izvor)

    print(f"Izvor: {izvor}")
    ids = odaberi(src, ukupno)
    if not ids:
        sys.exit("Nijedna odluka ne odgovara temama; uzorak nije izgraden.")

    # ponovljivost: uvijek gradimo iz nule
    for sufiks in ("", "-wal", "-shm"):
        p = izlaz.with_name(izlaz.name + sufiks)
        if p.exists():
            p.unlink()

    dst = store.veza(izlaz)
    upisano = 0
    for doc_id in ids:
        r = src.execute("SELECT * FROM odluke WHERE id=?", (doc_id,)).fetchone()
        rec = {k: r[k] for k in r.keys() if k not in ("meta_json", "dohvaceno")}
        try:
            rec["meta"] = json.loads(r["meta_json"] or "{}")
        except (TypeError, ValueError):
            rec["meta"] = {}
        store.spremi(dst, rec)
        upisano += 1

    dst.execute("INSERT INTO odluke_fts(odluke_fts) VALUES ('optimize')")
    dst.commit()
    dst.execute("VACUUM")
    dst.close()
    src.close()

    mb = izlaz.stat().st_size / 1024 / 1024
    print(f"\nUzorak: {izlaz}")
    print(f"Odluka: {upisano}   velicina: {mb:.2f} MB")
    return upisano


def pretrazi(baza: pathlib.Path, upit: str, limit: int = 5) -> int:
    """Pretraga uzorka, da se moze isprobati bez ostatka alata."""
    if not baza.exists():
        sys.exit(f"Uzorak ne postoji: {baza}\nIzgradi ga s: python uzorak.py")
    con = store.veza(baza)
    redci = store.trazi(con, upit, limit=limit)
    print(f"{len(redci)} pogodaka za {upit!r} u {baza.name}\n")
    for i, r in enumerate(redci, 1):
        datum = r["datum"] or "?"
        print(f"#{i}  {r['sud']}, {r['broj']} ({datum})")
        print(f"     {(r['isjecak'] or '').strip()}\n")
    con.close()
    return len(redci)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--izvor", type=pathlib.Path, default=IZVOR_DB)
    p.add_argument("--izlaz", type=pathlib.Path, default=UZORAK_DB)
    p.add_argument("--ukupno", type=int, default=25, help="ciljni broj odluka")
    p.add_argument("--trazi", metavar="UPIT",
                   help="ne gradi nista, nego pretrazi postojeci uzorak")
    a = p.parse_args()
    if a.trazi:
        pretrazi(a.izlaz.resolve(), a.trazi)
    else:
        izgradi(a.izvor.resolve(), a.izlaz.resolve(), a.ukupno)


if __name__ == "__main__":
    main()
