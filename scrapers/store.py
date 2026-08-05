# -*- coding: utf-8 -*-
"""
Lokalni korpus presuda — SQLite + FTS5 (puni tekst).

Ovo je "ius-info kod kuće": jednom preuzeta odluka ostaje zauvijek na disku,
crawl je inkrementalan (ne dohvaća ponovno ono što već imaš), a nad cijelim
korpusom radi trenutna full-text pretraga bez ijednog mrežnog zahtjeva.

Baza: PESUDE/data/corpus.sqlite
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
import unicodedata

from common import DATA_DIR

DB_PATH = DATA_DIR / "corpus.sqlite"

SHEMA = """
CREATE TABLE IF NOT EXISTS odluke (
    id            TEXT PRIMARY KEY,      -- stabilni ID izvora (uuid ANON-a / URL hash)
    izvor         TEXT NOT NULL,         -- 'anon' | 'usud' | 'nn'
    url           TEXT,
    broj          TEXT,                  -- oznaka predmeta, npr. Rev-533/2015-2
    sud           TEXT,
    datum         TEXT,                  -- ISO YYYY-MM-DD ako je razlučivo
    vrsta         TEXT,                  -- presuda / rješenje / odluka
    upisnik       TEXT,
    ecli          TEXT,
    pravomocnost  TEXT,
    kazalo        TEXT,                  -- stvarno kazalo (hijerarhija pojmova)
    propisi       TEXT,                  -- citirani propisi
    tekst         TEXT NOT NULL,         -- puni tekst odluke
    meta_json     TEXT,                  -- sve ostalo, doslovno
    dohvaceno     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_odluke_sud   ON odluke(sud);
CREATE INDEX IF NOT EXISTS ix_odluke_datum ON odluke(datum);
CREATE INDEX IF NOT EXISTS ix_odluke_izvor ON odluke(izvor);

-- evidencija odrađenih pretraga (da crawl zna gdje je stao)
CREATE TABLE IF NOT EXISTS pretrage (
    upit       TEXT,
    izvor      TEXT,
    stranica   INTEGER,
    pogodaka   INTEGER,
    obavljeno  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (upit, izvor, stranica)
);
"""

FTS_SHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS odluke_fts USING fts5(
    id UNINDEXED, broj, sud, kazalo, tekst,
    content='odluke', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS odluke_ai AFTER INSERT ON odluke BEGIN
    INSERT INTO odluke_fts(rowid, id, broj, sud, kazalo, tekst)
    VALUES (new.rowid, new.id, new.broj, new.sud, new.kazalo, new.tekst);
END;
CREATE TRIGGER IF NOT EXISTS odluke_ad AFTER DELETE ON odluke BEGIN
    INSERT INTO odluke_fts(odluke_fts, rowid, id, broj, sud, kazalo, tekst)
    VALUES ('delete', old.rowid, old.id, old.broj, old.sud, old.kazalo, old.tekst);
END;
CREATE TRIGGER IF NOT EXISTS odluke_au AFTER UPDATE ON odluke BEGIN
    INSERT INTO odluke_fts(odluke_fts, rowid, id, broj, sud, kazalo, tekst)
    VALUES ('delete', old.rowid, old.id, old.broj, old.sud, old.kazalo, old.tekst);
    INSERT INTO odluke_fts(rowid, id, broj, sud, kazalo, tekst)
    VALUES (new.rowid, new.id, new.broj, new.sud, new.kazalo, new.tekst);
END;
"""


def veza(path: pathlib.Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(path or DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SHEMA)
    try:
        con.executescript(FTS_SHEMA)
    except sqlite3.OperationalError as e:      # SQLite bez FTS5
        print(f"  [!] FTS5 nedostupan ({e}) — koristi se LIKE pretraga.")
    con.commit()
    return con


def ima(con: sqlite3.Connection, doc_id: str) -> bool:
    return con.execute("SELECT 1 FROM odluke WHERE id=?", (doc_id,)).fetchone() is not None


def spremi(con: sqlite3.Connection, rec: dict) -> bool:
    """Upsert jedne odluke. Vraća True ako je nova."""
    nova = not ima(con, rec["id"])
    con.execute(
        """INSERT INTO odluke (id, izvor, url, broj, sud, datum, vrsta, upisnik,
                               ecli, pravomocnost, kazalo, propisi, tekst, meta_json)
           VALUES (:id,:izvor,:url,:broj,:sud,:datum,:vrsta,:upisnik,
                   :ecli,:pravomocnost,:kazalo,:propisi,:tekst,:meta_json)
           ON CONFLICT(id) DO UPDATE SET
               tekst=excluded.tekst, kazalo=excluded.kazalo,
               propisi=excluded.propisi, meta_json=excluded.meta_json""",
        {
            "id": rec["id"], "izvor": rec.get("izvor", "anon"), "url": rec.get("url"),
            "broj": rec.get("broj"), "sud": rec.get("sud"), "datum": rec.get("datum"),
            "vrsta": rec.get("vrsta"), "upisnik": rec.get("upisnik"),
            "ecli": rec.get("ecli"), "pravomocnost": rec.get("pravomocnost"),
            "kazalo": rec.get("kazalo"), "propisi": rec.get("propisi"),
            "tekst": rec.get("tekst") or "",
            "meta_json": json.dumps(rec.get("meta") or {}, ensure_ascii=False),
        },
    )
    con.commit()
    return nova


def zabiljezi_pretragu(con: sqlite3.Connection, upit: str, izvor: str,
                       stranica: int, pogodaka: int) -> None:
    con.execute("INSERT OR REPLACE INTO pretrage (upit, izvor, stranica, pogodaka) "
                "VALUES (?,?,?,?)", (upit, izvor, stranica, pogodaka))
    con.commit()


def _bez_dijakritika(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def trazi(con: sqlite3.Connection, upit: str, limit: int = 50) -> list[sqlite3.Row]:
    """Full-text pretraga lokalnog korpusa (FTS5, s fallbackom na LIKE)."""
    try:
        return con.execute(
            """SELECT o.*, snippet(odluke_fts, 4, '»', '«', ' … ', 24) AS isjecak,
                      bm25(odluke_fts) AS rang
               FROM odluke_fts JOIN odluke o ON o.rowid = odluke_fts.rowid
               WHERE odluke_fts MATCH ?
               ORDER BY rang LIMIT ?""", (upit, limit)).fetchall()
    except sqlite3.OperationalError:
        pojam = f"%{_bez_dijakritika(re.sub(chr(34), '', upit))}%"
        return con.execute(
            "SELECT *, substr(tekst,1,300) AS isjecak, 0 AS rang FROM odluke "
            "WHERE tekst LIKE ? LIMIT ?", (pojam, limit)).fetchall()


def statistika(con: sqlite3.Connection) -> dict:
    r = {}
    r["ukupno"] = con.execute("SELECT COUNT(*) FROM odluke").fetchone()[0]
    r["po_izvoru"] = dict(con.execute(
        "SELECT izvor, COUNT(*) FROM odluke GROUP BY izvor").fetchall())
    r["po_sudu"] = dict(con.execute(
        "SELECT COALESCE(sud,'?'), COUNT(*) c FROM odluke GROUP BY 1 ORDER BY c DESC LIMIT 15"
    ).fetchall())
    r["raspon"] = con.execute(
        "SELECT MIN(datum), MAX(datum) FROM odluke WHERE datum IS NOT NULL AND datum<>''"
    ).fetchone()
    return r


if __name__ == "__main__":
    con = veza()
    s = statistika(con)
    print(f"Baza: {DB_PATH}")
    print(f"Ukupno odluka: {s['ukupno']}")
    print(f"Po izvoru: {s['po_izvoru']}")
    if s["ukupno"]:
        print(f"Raspon datuma: {s['raspon'][0]} … {s['raspon'][1]}")
        print("Najzastupljeniji sudovi:")
        for sud, c in s["po_sudu"].items():
            print(f"  {c:6d}  {sud}")
