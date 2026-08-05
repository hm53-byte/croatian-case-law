# -*- coding: utf-8 -*-
"""
ANON — Tražilica odluka sudova RH (https://odluke.sudovi.hr)

SLUŽBENI izvor sudske prakse Republike Hrvatske od gašenja starog Portala
sudske prakse (sudskapraksa.csp.vsrh.hr — taj host danas odbija vezu).
Vodi ga Ministarstvo pravosuđa, uprave i digitalne transformacije; sadrži
sve javno objavljene odluke iz starog portala u anonimiziranom obliku
i dopunjuje se dnevno (>1,17 mil. odluka).

Reverse-engineerirano sučelje (obična server-rendered ASP.NET aplikacija,
nema JSON API-ja — zato se parsira HTML):

    pretraga   GET /Document/DisplayList?q=<upit>&page=<n>     (10 rezultata/str.)
    filtri     &sk=<stvarno kazalo>  &zk=<zakon>  &prm=pravomocna
    odluka     GET /Document/View?id=<uuid>                     (<div class="decision-text">)
    PDF        GET /Document/DownloadPDF?id=<uuid>

Napomena: tražilica vraća najviše 10.000 pogodaka po upitu (1000 stranica),
pa se šire teme razbijaju na više užih upita.

Primjeri:
    python anon.py search "zamjena šumskog zemljišta"
    python anon.py doc 05c6cdd3-1486-4903-b85f-eda703b4e5e0
    python anon.py harvest "zamjena šuma" --max 200
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.parse

from common import get, get_bytes, soup, save_md, log, DATA_DIR
import store

BASE = "https://odluke.sudovi.hr"
SEARCH_URL = f"{BASE}/Document/DisplayList"
DOC_URL = f"{BASE}/Document/View"
PDF_URL = f"{BASE}/Document/DownloadPDF"

PO_STRANICI = 10
MAX_STRANICA = 1000          # tvrdo ograničenje tražilice (10.000 pogodaka)

HR_MJESECI = {
    "siječnja": 1, "veljače": 2, "ožujka": 3, "travnja": 4, "svibnja": 5,
    "lipnja": 6, "srpnja": 7, "kolovoza": 8, "rujna": 9, "listopada": 10,
    "studenoga": 11, "studenog": 11, "prosinca": 12,
}


def _iso_datum(s: str | None) -> str:
    """'22.2.2019.' -> '2019-02-22'; '16. listopada 2018.' -> '2018-10-16'."""
    if not s:
        return ""
    s = s.strip()
    m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", s)
    if m:
        d, mj, g = (int(x) for x in m.groups())
        return f"{g:04d}-{mj:02d}-{d:02d}"
    m = re.search(r"(\d{1,2})\.\s*([a-zšđčćž]+)\s*(\d{4})", s, re.I)
    if m and m.group(2).lower() in HR_MJESECI:
        return f"{int(m.group(3)):04d}-{HR_MJESECI[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return ""


def _tekst(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""


# ---------------------------------------------------------------- pretraga --

def search(upit: str, *, page: int = 1, sk: str = "", zk: str = "",
           samo_pravomocne: bool = False, cache: bool = True) -> dict:
    """Jedna stranica rezultata. Vraća {'ukupno': int, 'rezultati': [...]}."""
    params = {"q": upit, "page": page}
    if sk:
        params["sk"] = sk
    if zk:
        params["zk"] = zk
    if samo_pravomocne:
        params["prm"] = "pravomocna"

    html = get(SEARCH_URL, params=params, cache=cache)
    s = soup(html)

    ukupno = 0
    br = s.select_one(".number-of-rslts")
    if br:
        m = re.search(r"([\d.\s]+)\s*rezultat", _tekst(br))
        if m:
            ukupno = int(re.sub(r"\D", "", m.group(1)) or 0)

    rezultati = []
    for a in s.select("a.search-result"):
        href = a.get("href", "")
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
        doc_id = (qs.get("id") or [""])[0]
        if not doc_id:
            continue
        rezultati.append({
            "id": doc_id,
            "url": urllib.parse.urljoin(BASE, href),
            "broj": _tekst(a.select_one(".decision-number")),
            "sud": _tekst(a.select_one(".decision-court")),
            "datum_prikaz": _tekst(a.select_one(".decision-date")),
            "datum": _iso_datum(_tekst(a.select_one(".decision-date"))),
            "pravomocnost": _tekst(a.select_one(".final-decision")),
            "isjecak": _tekst(a.select_one(".result-snippet")),
        })
    return {"ukupno": ukupno, "rezultati": rezultati}


def search_all(upit: str, *, max_rezultata: int = 100, **kw):
    """Generator kroz stranice rezultata, uz poštovanje limita tražilice."""
    dohvaceno = 0
    for page in range(1, MAX_STRANICA + 1):
        r = search(upit, page=page, **kw)
        if page == 1:
            log(f"  tražilica javlja: {r['ukupno']} pogodaka za {upit!r}")
        if not r["rezultati"]:
            return
        for item in r["rezultati"]:
            yield item
            dohvaceno += 1
            if dohvaceno >= max_rezultata:
                return
        if r["ukupno"] and page * PO_STRANICI >= min(r["ukupno"], max_rezultata):
            return


# ----------------------------------------------------------------- odluka ---

def doc(doc_id: str, *, cache: bool = True) -> dict:
    """Puni tekst + metapodaci jedne odluke."""
    url = f"{DOC_URL}?id={doc_id}"
    html = get(DOC_URL, params={"id": doc_id}, cache=cache)
    s = soup(html)

    body = s.select_one(".decision-text")
    if body:
        for tag in body(["style", "script"]):
            tag.decompose()
        tekst = body.get_text("\n", strip=True)
        tekst = re.sub(r"\n{3,}", "\n\n", tekst)
    else:
        tekst = ""

    # metapodaci su parovi labela/vrijednost u modalu "Metapodatci odluke"
    meta: dict[str, str] = {}
    plosnato = re.sub(r"\s+", " ", s.get_text(" ", strip=True))
    # Zadnja oznaka u modalu nema oznake iza sebe, pa bi regex nastavio gutati
    # sve do kraja stranice — a ondje je banner o kolačićima. Odrezati ga.
    plosnato = re.split(r"U svrhu pružanja boljeg korisničkog iskustva", plosnato)[0]
    # Popis MORA sadrzavati sve oznake koje portal koristi. Ako jedna nedostaje,
    # regex prethodne oznake guta njezin sadrzaj do sljedece poznate. Tako je
    # "Vrsta odluke" dugo progutala cijelo "Zakonsko kazalo" i "EuroVoc".
    OZNAKE = (
        "Broj odluke", "Sud", "Datum odluke", "Pravomoćnost", "Datum objave",
        "Upisnik", "Vrsta odluke", "ECLI broj", "Prethodne odluke",
        "Naknadne odluke", "Zakonsko kazalo", "Stvarno kazalo", "EuroVoc",
        "Europska pravna stečevina", "Propisi",
    )
    granica = "|".join(re.escape(o) + r"\s*:" for o in OZNAKE)
    for oznaka in OZNAKE:
        m = re.search(re.escape(oznaka) + r"\s*:\s*(.{0,1200}?)(?=(?:" + granica + r")|$)",
                      plosnato)
        if m:
            meta[oznaka] = m.group(1).strip(" .;")

    return {
        "id": doc_id,
        "izvor": "anon",
        "url": url,
        "broj": meta.get("Broj odluke", ""),
        "sud": meta.get("Sud", ""),
        "datum": _iso_datum(meta.get("Datum odluke", "")),
        "vrsta": meta.get("Vrsta odluke", ""),
        "upisnik": meta.get("Upisnik", ""),
        "ecli": meta.get("ECLI broj", ""),
        "pravomocnost": meta.get("Pravomoćnost", ""),
        "kazalo": meta.get("Stvarno kazalo", ""),
        "zakonsko_kazalo": meta.get("Zakonsko kazalo", ""),
        "eurovoc": meta.get("EuroVoc", ""),
        "propisi": meta.get("Propisi", ""),
        "tekst": tekst,
        "meta": meta,
    }


def pdf(doc_id: str, cilj=None):
    cilj = cilj or (DATA_DIR / "pdf" / f"{doc_id}.pdf")
    cilj.parent.mkdir(parents=True, exist_ok=True)
    cilj.write_bytes(get_bytes(f"{PDF_URL}?id={doc_id}"))
    return cilj


# ---------------------------------------------------------------- harvest ---

def harvest(upiti: list[str], *, max_po_upitu: int = 100, con=None,
            samo_pravomocne: bool = False) -> dict:
    """Pretraži -> preuzmi puni tekst -> spremi u lokalni korpus. Inkrementalno."""
    con = con or store.veza()
    zbroj = {"pronadeno": 0, "novo": 0, "preskoceno": 0, "greske": 0}

    for upit in upiti:
        log(f"\n== ANON: {upit!r}")
        pogodaka = 0
        for item in search_all(upit, max_rezultata=max_po_upitu,
                               samo_pravomocne=samo_pravomocne):
            pogodaka += 1
            zbroj["pronadeno"] += 1
            if store.ima(con, item["id"]):
                zbroj["preskoceno"] += 1
                continue
            try:
                rec = doc(item["id"])
                if not rec["tekst"]:
                    rec["tekst"] = item.get("isjecak", "")
                for k in ("broj", "sud", "datum", "pravomocnost"):
                    rec[k] = rec.get(k) or item.get(k, "")
                if store.spremi(con, rec):
                    zbroj["novo"] += 1
                    log(f"  + {rec['sud']} {rec['broj']} ({rec['datum']})")
            except Exception as e:  # noqa: BLE001
                zbroj["greske"] += 1
                log(f"  [!] {item['id']}: {e}")
        store.zabiljezi_pretragu(con, upit, "anon", 0, pogodaka)

    log(f"\nGotovo: {zbroj['novo']} novih, {zbroj['preskoceno']} već u bazi, "
        f"{zbroj['greske']} grešaka.")
    return zbroj


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("search", help="pretraži portal i ispiši pogotke")
    ps.add_argument("upit", nargs="+")
    ps.add_argument("--max", type=int, default=30)
    ps.add_argument("--pravomocne", action="store_true")

    pd = sub.add_parser("doc", help="dohvati puni tekst odluke po UUID-u")
    pd.add_argument("id", nargs="+")
    pd.add_argument("--md", action="store_true", help="spremi i kao Markdown")

    ph = sub.add_parser("harvest", help="pretraži + preuzmi + spremi u korpus")
    ph.add_argument("upit", nargs="+")
    ph.add_argument("--max", type=int, default=100, help="max pogodaka po upitu")
    ph.add_argument("--pravomocne", action="store_true")

    a = p.parse_args()

    if a.cmd == "search":
        for upit in a.upit:
            log(f"\n== {upit!r}")
            for r in search_all(upit, max_rezultata=a.max,
                                samo_pravomocne=a.pravomocne):
                log(f"  {r['sud']} — {r['broj']} ({r['datum_prikaz']}) [{r['pravomocnost']}]")
                log(f"    id={r['id']}")
                if r["isjecak"]:
                    log(f"    {r['isjecak'][:220]}")
    elif a.cmd == "doc":
        for d in a.id:
            rec = doc(d)
            log(f"# {rec['sud']} {rec['broj']} ({rec['datum']}) — {rec['vrsta']}")
            log(f"ECLI: {rec['ecli']} | {rec['pravomocnost']}")
            log(f"Kazalo: {rec['kazalo'][:300]}")
            log("-" * 70)
            log(rec["tekst"][:4000])
            if a.md:
                pth = save_md(f"ANON_{rec['sud']}_{rec['broj']}", naslov=f"{rec['sud']} {rec['broj']}",
                              tijelo=rec["tekst"], izvor_url=rec["url"],
                              meta={k: v for k, v in rec["meta"].items()})
                log(f"[spremljeno] {pth}")
    elif a.cmd == "harvest":
        harvest(a.upit, max_po_upitu=a.max, samo_pravomocne=a.pravomocne)


if __name__ == "__main__":
    sys.exit(main())
