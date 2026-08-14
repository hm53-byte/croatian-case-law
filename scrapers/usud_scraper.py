# -*- coding: utf-8 -*-
"""
USTAVNI SUD RH - praksa Ustavnog suda (sljeme.usud.hr/usud/praksaw.nsf).

Portal je IBM Domino 9 / XPages (Dojo 1.9.7), a ne klasični Notes web. Zbog
toga NE postoji nijedan GET oblik pretrage ni pregleda: sve se vrti oko
djelomičnog osvježavanja (partial refresh) POST-om na .xsp stranicu, uz
$$viewid i kolačić SessionID vezane uz jednu sesiju.

ŠTO RADI (provjereno na terenu, kolovoz 2026.)

  Stablo pregleda "signatura -> godina -> odluke", tri koraka:
    1. GET  vSignaturaPoGodiniZap.xsp        -> $$viewid, kolačići, 20 signatura
    2. POST ?$$ajaxid=<prefiks>divContent    -> godine te signature (npr. U-I: 1987-2026)
    3. POST ?$$ajaxid=<prefiks>divContent    -> SVE odluke te signature i godine
  Treći korak vraća cijeli popis odjednom, bez paginacije (U-I/2020 = 85 odluka).

  Metapodaci i puni tekst idu OBIČNIM GET-om, bez sesije i bez kolačića:
    fOdluka.xsp?action=openDocument&documentId=<UNID>   -> metapodaci + privitci
    /Usud/Praksaw.nsf/<UNID>/%24FILE/<oznaka>.pdf       -> puni tekst (ima tekstualni sloj)

  Puni tekst odluke NIJE u HTML-u: stranica odluke daje samo signaturu, vrstu,
  datum, način odlučivanja i jednoredni zaključak. Tekst se vadi iz PDF privitka
  (pypdf), pa je pypdf ovdje stvarna ovisnost, a ne pomoćni alat.

ŠTO NE RADI (ne troši vrijeme na ponovnu provjeru)

  ?SearchView&Query=...            -> 404 "Couldn't find design note - Praksa"
  <view>?OpenView / ?ReadViewEntries -> 404
  /api/data/collections, /documents  -> 403 (Domino Access Services isključen)
  fSearchNew.xsp                     -> POST prolazi, ali vSearchResults.xsp
                                        uvijek vrati "Nema rezultata pretrage";
                                        rezultati ovise o stanju sesije koje se
                                        izvan preglednika ne rekonstruira.

  Zato se po pojmu NE pretražuje portal nego lokalni korpus: prvo se pokupi
  indeks (naredba korpus), a onda se traži naredbom trazi ili preko vektor.py.

Cijena obilaska: oko 20 signatura x do 40 godina = do ~800 POST zahtjeva za
cijeli indeks, plus 2 GET-a po odluci. Uz rate-limit od 1,5 s iz common.py
indeks je gotov za dvadesetak minuta; korpus ovisi o broju odluka.

Narodne novine (zakoni.py) NISU zamjena: u NN se objavljuju samo odluke koje se
moraju objaviti (ocjena ustavnosti propisa), a ne i odluke o ustavnim tužbama
(U-III), kojih je većina prakse.

ROBOTS. robots.txt hosta sljeme.usud.hr glasi 'Disallow: /' bez ijedne
iznimke (provjereno 14.8.2026.). Zato svaki mrežni zahtjev (GET i POST)
prolazi kroz tvrdu zapreku u common.py: bez oznake pisanog dopuštenja izvora
(PRESUDE_DOPUSTENJE ili --dopustenje) proces završava izlaznim kodom 3 prije
prvog zahtjeva. Već keširani odgovori čitaju se s diska i dalje.

Primjeri:
    python usud_scraper.py signature
    python usud_scraper.py godine U-I
    python usud_scraper.py index U-I 2020
    python usud_scraper.py fetch C12570D30061CE54C1258642002DF404
    python usud_scraper.py korpus U-I --od 2018 --do 2020
    python usud_scraper.py trazi "šumsko zemljište"
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import urllib.parse

import common
from common import get, get_bytes, soup, save_md, log
import store

BASE = "https://sljeme.usud.hr"
VIEW_URL = f"{BASE}/usud/praksaw.nsf/vSignaturaPoGodiniZap.xsp"
DOC_URL = f"{BASE}/usud/praksaw.nsf/fOdluka.xsp"

SUD = "Ustavni sud Republike Hrvatske"

# XPages generira ID-eve komponenata iz stabla stranice; ovi prefiksi su
# stabilni dok se dizajn baze ne promijeni. Ako partial refresh počne vraćati
# cijelu stranicu umjesto ulomka, prvo provjeri jesu li se _id-evi pomaknuli.
PREF_SIG = "view:_id1:_id2:_id3:callbackContent:fctView:_id38:rpView:{i}:_id45:"
PREF_GOD = "facetContent:rpCategory:{j}:_id49:"
SUBMIT_SIG = "_id46"     # gumb koji širi signaturu (1. razina)
SUBMIT_GOD = "_id50"     # gumb koji širi godinu (2. razina) - drugi _id, ne greška


# ------------------------------------------------------------ XPages sloj ---

def _post_partial(prefiks: str, submit_id: str, viewid: str) -> str:
    """Djelomično osvježavanje jednog čvora stabla. Vraća HTML ulomak.

    Šalje se kao multipart/form-data jer je takav i enctype obrasca; s
    application/x-www-form-urlencoded Domino zna vratiti cijelu stranicu.
    """
    url = VIEW_URL + "?$$ajaxid=" + urllib.parse.quote(prefiks + "divContent", safe="")
    # Ide mimo common.post (multipart), pa zapreka mora biti i ovdje.
    common.zapreka_robots(url)
    polja = {
        "$$viewid": viewid,
        "$$xspsubmitid": prefiks + submit_id,
        "$$xspexecid": prefiks + "divCategoryContainer",
        "$$xspsubmitvalue": "",
        "$$xspsubmitscroll": "0|0",
        "view:_id1": "view:_id1",
        "view:_id1:_id2:_id3:ebSearchGlobal": "",
    }
    datoteke = {k: (None, v.encode("utf-8")) for k, v in polja.items()}

    zadnja = None
    for pokusaj in range(1, common.MAX_RETRIES + 1):
        try:
            # Ide preko common.session (isti kolačići kao GET) i common._throttle
            # da POST-ovi ulaze u isti rate-limit po hostu kao i ostali moduli;
            # common.post ne podržava multipart, pa se zahtjev slaže ovdje.
            common._throttle(url)
            r = common.session.post(
                url, files=datoteke, timeout=90,
                headers={"Referer": VIEW_URL, "X-Requested-With": "XMLHttpRequest"})
            r.raise_for_status()
            if not r.encoding or r.encoding.lower() == "iso-8859-1":
                r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception as e:  # noqa: BLE001
            zadnja = e
            if pokusaj < common.MAX_RETRIES:
                log(f"    [retry {pokusaj}] partial refresh: {e}")
    raise RuntimeError(f"Partial refresh nije uspio: {prefiks} - {zadnja}")


def _kategorije(html: str, uzorak: str) -> dict[int, str]:
    """Iz HTML-a (cijele stranice ili ulomka) vadi oznake kategorija i njihove indekse."""
    s = soup(html)
    rez: dict[int, str] = {}
    for span in s.select("span[id$=':lblNazivKategorije']"):
        m = re.search(uzorak, span.get("id", ""))
        naziv = span.get_text(" ", strip=True)
        if m and naziv and int(m.group(1)) not in rez:
            rez[int(m.group(1))] = naziv
    return rez


class Stablo:
    """Jedna XPages sesija nad stablom pregleda. Čuva $$viewid i otvoreni čvor.

    Server pamti koja je grana proširena, pa se prije spuštanja na godinu uvijek
    mora (ponovno) proširiti njezina signatura; zato objekt pamti što je otvoreno
    i ne troši zahtjeve na ono što je već otvorio.
    """

    def __init__(self) -> None:
        self.viewid = ""
        self.signature: dict[int, str] = {}
        self._godine: dict[str, dict[int, str]] = {}
        self._otvorena: str = ""

    def otvori(self, *, ponovno: bool = False) -> None:
        if self.viewid and not ponovno:
            return
        # Bez keširanja: $$viewid iz keša je mrtav i partial refresh bi pao.
        html = get(VIEW_URL, cache=False)
        m = re.search(r'name="\$\$viewid"[^>]*value="([^"]+)"', html)
        if not m:
            raise RuntimeError("Nema $$viewid na ulaznoj stranici - dizajn baze se promijenio.")
        self.viewid = m.group(1)
        self.signature = _kategorije(html, r"rpView:(\d+):_id45:lblNazivKategorije$")
        self._godine.clear()
        self._otvorena = ""
        if not self.signature:
            raise RuntimeError("Ulazna stranica ne daje popis signatura.")

    def _indeks_signature(self, signatura: str) -> int:
        self.otvori()
        for i, naziv in self.signature.items():
            if naziv.upper() == signatura.upper():
                return i
        raise KeyError(f"Nepoznata signatura {signatura!r}. Poznate: "
                       f"{', '.join(sorted(self.signature.values()))}")

    def prosiri_signaturu(self, signatura: str) -> str:
        """Otvara granu signature i vraća njezin prefiks; usput popuni godine."""
        i = self._indeks_signature(signatura)
        prefiks = PREF_SIG.format(i=i)
        if self._otvorena == signatura and signatura in self._godine:
            return prefiks
        ulomak = _post_partial(prefiks, SUBMIT_SIG, self.viewid)
        godine = _kategorije(ulomak, r"rpCategory:(\d+):_id49:lblNazivKategorije$")
        self._godine[signatura] = {j: g for j, g in godine.items() if re.fullmatch(r"\d{4}", g)}
        self._otvorena = signatura
        return prefiks

    def godine(self, signatura: str) -> list[str]:
        self.prosiri_signaturu(signatura)
        return [g for _, g in sorted(self._godine[signatura].items())]

    def odluke(self, signatura: str, godina: str | int) -> list[dict]:
        godina = str(godina)
        prefiks = self.prosiri_signaturu(signatura)
        j = next((k for k, v in self._godine[signatura].items() if v == godina), None)
        if j is None:
            raise KeyError(f"Za signaturu {signatura} nema godine {godina}. "
                           f"Dostupno: {', '.join(self.godine(signatura))}")
        ulomak = _post_partial(prefiks + PREF_GOD.format(j=j), SUBMIT_GOD, self.viewid)
        return _redci_odluka(ulomak)


_stablo: Stablo | None = None


def stablo() -> Stablo:
    """Zajednička sesija za cijeli proces - jedan $$viewid, jedan skup kolačića."""
    global _stablo
    if _stablo is None:
        _stablo = Stablo()
        _stablo.otvori()
    return _stablo


# --------------------------------------------------------------- parsiranje ---

def _iso_datum(s: str) -> str:
    """'15.12.2020' -> '2020-12-15'."""
    m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", s or "")
    if not m:
        return ""
    d, mj, g = (int(x) for x in m.groups())
    return f"{g:04d}-{mj:02d}-{d:02d}"


def _unid(cilj: str) -> str:
    """Prima UNID ili puni URL odluke; vraća UNID."""
    cilj = (cilj or "").strip()
    if re.fullmatch(r"[0-9A-Fa-f]{32}", cilj):
        return cilj.upper()
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(cilj).query)
    for kljuc in ("documentId", "documentid", "DocumentId"):
        if q.get(kljuc):
            return q[kljuc][0].upper()
    m = re.search(r"/([0-9A-Fa-f]{32})/", cilj)
    if m:
        return m.group(1).upper()
    raise ValueError(f"Iz {cilj!r} ne mogu izvući UNID odluke.")


def url_odluke(unid: str) -> str:
    return f"{DOC_URL}?action=openDocument&documentId={unid}"


def _razlomi_naslov(txt: str) -> dict:
    """'U-I-146/2020 - 15.12.2020 - odbačaj - nenadležnost (primjena) - rješenje'.

    Ishod sam sadrži crtice, pa se ne cijepa naslijepo: prvi dio je oznaka,
    drugi datum, posljednji vrsta odluke, a sve između je način odlučivanja.
    """
    dijelovi = [d.strip() for d in re.split(r"\s+-\s+", txt.strip()) if d.strip()]
    if not dijelovi:
        return {"oznaka": txt.strip(), "datum": "", "nacin": "", "vrsta": ""}
    oznaka, ostatak = dijelovi[0], dijelovi[1:]
    datum = ""
    if ostatak and re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}", ostatak[0]):
        datum, ostatak = ostatak[0], ostatak[1:]
    vrsta = ostatak.pop() if ostatak else ""
    return {"oznaka": oznaka, "datum": datum, "nacin": " - ".join(ostatak), "vrsta": vrsta}


def _redci_odluka(html: str) -> list[dict]:
    s = soup(html)
    rez, vidjeni = [], set()
    for a in s.select("a[id$=':lnkOdluka']"):
        href = a.get("href", "")
        if "fOdluka.xsp" not in href:
            continue
        try:
            unid = _unid(href)
        except ValueError:
            continue
        if unid in vidjeni:
            continue
        vidjeni.add(unid)
        stavka = _razlomi_naslov(a.get_text(" ", strip=True))
        stavka.update({"unid": unid, "url": url_odluke(unid),  # link u HTML-u je http://
                       "datum_iso": _iso_datum(stavka["datum"])})
        rez.append(stavka)
    return rez


def _polje(s, sufiks: str) -> str:
    el = s.select_one(f"span[id$=':{sufiks}']")
    return el.get_text(" ", strip=True) if el else ""


# ------------------------------------------------------- pojedina odluka ---

def usud_index(signatura: str, godina: str | int) -> list[dict]:
    """Popis svih odluka jedne signature i godine (bez paginacije)."""
    return stablo().odluke(signatura, godina)


def usud_signature() -> list[str]:
    s = stablo()
    return [naziv for _, naziv in sorted(s.signature.items())]


def usud_godine(signatura: str) -> list[str]:
    return stablo().godine(signatura)


def usud_meta(cilj: str) -> dict:
    """Metapodaci odluke sa stranice fOdluka.xsp (običan GET, bez sesije)."""
    unid = _unid(cilj)
    url = url_odluke(unid)
    s = soup(get(url))

    privitci = []
    for a in s.select("a[href*='FILE'], a[href*='%24FILE']"):
        href = a.get("href", "")
        if not href:
            continue
        ime = a.get_text(" ", strip=True) or href.rsplit("/", 1)[-1]
        privitci.append({"ime": ime, "url": urllib.parse.urljoin(url, href)})

    datum = _polje(s, "cfDatum")
    return {
        "unid": unid,
        "url": url,
        "tip": _polje(s, "cfTip").rstrip(":"),          # npr. "Ocjena propisa"
        "oznaka": _polje(s, "cfSignatura"),
        "vrsta": _polje(s, "cfOdluka").rstrip(", "),    # rješenje / odluka
        "datum": datum,
        "datum_iso": _iso_datum(datum),
        "nacin": _polje(s, "cfVrstaOdluke"),            # odbačaj, neprihvaćanje...
        "zakljucak": _polje(s, "cfZakljucak"),
        "privitci": privitci,
    }


def _pdf_tekst(bajtovi: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        log("  [!] pypdf nije instaliran (pip install pypdf) - bez punog teksta.")
        return ""
    stranice = [(str(st.extract_text() or "")) for st in PdfReader(io.BytesIO(bajtovi)).pages]
    txt = "\n".join(stranice)
    txt = re.sub(r"[ \t]+\n", "\n", txt)
    return re.sub(r"\n{3,}", "\n\n", txt).strip()


def usud_fetch(cilj: str, *, md: bool = True, con=None) -> dict:
    """Metapodaci + puni tekst iz PDF privitka. Vraća zapis spreman za store.py.

    `cilj` je UNID ili puni URL odluke. Ako `con` nije None, odluka se sprema i
    u lokalni korpus.
    """
    m = usud_meta(cilj)
    pdf = next((p for p in m["privitci"] if p["ime"].lower().endswith(".pdf")), None)
    tekst = ""
    if pdf:
        try:
            tekst = _pdf_tekst(get_bytes(pdf["url"]))
        except Exception as e:  # noqa: BLE001
            log(f"  [!] PDF {pdf['ime']}: {e}")
    if not tekst:
        # Bolje išta nego ništa: barem zaključak, da odluka bude pretraživa lokalno.
        tekst = " ".join(x for x in (m["tip"], m["nacin"], m["zakljucak"]) if x)

    naslov = f"{m['oznaka']} ({m['datum']}) - {m['vrsta']}".strip(" -")
    rec = {
        "id": f"usud:{m['unid']}",
        "izvor": "usud",
        "url": m["url"],
        "broj": m["oznaka"],
        "sud": SUD,
        "datum": m["datum_iso"],
        "vrsta": m["vrsta"],
        "upisnik": (m["oznaka"].split("-")[0] if m["oznaka"] else ""),
        "ecli": "",
        "pravomocnost": "",
        "kazalo": m["zakljucak"],
        "propisi": "",
        "tekst": tekst,
        "meta": {k: v for k, v in m.items() if k != "privitci"},
    }

    if md:
        rec["md"] = str(save_md(
            f"RH_USUD_{m['oznaka'] or m['unid']}", naslov=f"{SUD}: {naslov}",
            tijelo=tekst, izvor_url=m["url"],
            meta={"Vrsta postupka": m["tip"], "Oznaka": m["oznaka"],
                  "Vrsta odluke": m["vrsta"], "Datum": m["datum"],
                  "Način odlučivanja": m["nacin"], "Zaključak": m["zakljucak"],
                  "Privitci": ", ".join(p["ime"] for p in m["privitci"])}))
    if con is not None:
        store.spremi(con, rec)
    return rec


# ------------------------------------------------------------------ korpus ---

def usud_korpus(signatura: str, *, od: int | None = None, do: int | None = None,
                max_odluka: int = 0, con=None) -> dict:
    """Indeks -> puni tekst -> lokalni korpus, inkrementalno (preskače poznato)."""
    con = con or store.veza()
    zbroj = {"pronadeno": 0, "novo": 0, "preskoceno": 0, "greske": 0}

    godine = [g for g in usud_godine(signatura)
              if (od is None or int(g) >= od) and (do is None or int(g) <= do)]
    log(f"== USUD {signatura}: godine {godine[0] if godine else '-'}"
        f"..{godine[-1] if godine else '-'} ({len(godine)})")

    for g in godine:
        popis = usud_index(signatura, g)
        log(f"  {signatura}/{g}: {len(popis)} odluka")
        for stavka in popis:
            if max_odluka and zbroj["novo"] >= max_odluka:
                log(f"  (stop: dosegnut --max {max_odluka})")
                return zbroj
            zbroj["pronadeno"] += 1
            if store.ima(con, f"usud:{stavka['unid']}"):
                zbroj["preskoceno"] += 1
                continue
            try:
                rec = usud_fetch(stavka["unid"], md=False, con=con)
                zbroj["novo"] += 1
                log(f"    + {rec['broj']} ({rec['datum']}) {len(rec['tekst']):,} znakova")
            except Exception as e:  # noqa: BLE001
                zbroj["greske"] += 1
                log(f"    [!] {stavka['oznaka']}: {e}")

    log(f"Gotovo: {zbroj['novo']} novih, {zbroj['preskoceno']} već u bazi, "
        f"{zbroj['greske']} grešaka.")
    return zbroj


def usud_trazi(upit: str, limit: int = 20) -> list:
    """Pretraga LOKALNOG korpusa - portal headless pretragu nema (vidi docstring)."""
    con = store.veza()
    return [r for r in store.trazi(con, upit, limit=limit * 4)
            if (r["izvor"] or "") == "usud"][:limit]


# --------------------------------------------------------------------- CLI ---

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dopustenje",
                   help="oznaka pisanog dopustenja izvora (klasa/urbroj); "
                        "bez nje se mrezni dohvat s portala odbija (robots.txt)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("signature", help="popis signatura (U-I, U-III, ...)")

    pg = sub.add_parser("godine", help="godine dostupne za signaturu")
    pg.add_argument("signatura")

    pi = sub.add_parser("index", help="popis odluka jedne signature i godine")
    pi.add_argument("signatura")
    pi.add_argument("godina")

    pf = sub.add_parser("fetch", help="metapodaci + puni tekst odluke (UNID ili URL)")
    pf.add_argument("cilj", nargs="+")
    pf.add_argument("--bez-md", action="store_true", help="ne spremaj Markdown u nalazi/")
    pf.add_argument("--korpus", action="store_true", help="spremi i u lokalni korpus")

    pk = sub.add_parser("korpus", help="pokupi cijelu signaturu u lokalni korpus")
    pk.add_argument("signatura")
    pk.add_argument("--od", type=int, default=None)
    pk.add_argument("--do", type=int, default=None)
    pk.add_argument("--max", type=int, default=0, help="stani nakon N novih odluka")

    pt = sub.add_parser("trazi", help="pretraga lokalnog korpusa (ne portala)")
    pt.add_argument("upit", nargs="+")
    pt.add_argument("--max", type=int, default=20)

    a = p.parse_args()
    if a.dopustenje:
        common.DOPUSTENJE = a.dopustenje.strip()

    if a.cmd == "signature":
        for sig in usud_signature():
            log(f"  {sig}")
    elif a.cmd == "godine":
        log("  " + ", ".join(usud_godine(a.signatura)))
    elif a.cmd == "index":
        popis = usud_index(a.signatura, a.godina)
        log(f"== {a.signatura}/{a.godina}: {len(popis)} odluka")
        for r in popis:
            log(f"  {r['oznaka']:<18} {r['datum']:<12} {r['vrsta']:<10} {r['nacin']}")
            log(f"    {r['unid']}")
    elif a.cmd == "fetch":
        con = store.veza() if a.korpus else None
        for c in a.cilj:
            rec = usud_fetch(c, md=not a.bez_md, con=con)
            log(f"# {rec['broj']} ({rec['datum']}) - {rec['vrsta']}")
            log(f"Zaključak: {rec['kazalo']}")
            log("-" * 70)
            log(rec["tekst"][:3000])
            if rec.get("md"):
                log(f"[spremljeno] {rec['md']}")
    elif a.cmd == "korpus":
        usud_korpus(a.signatura, od=a.od, do=a.do, max_odluka=a.max)
    elif a.cmd == "trazi":
        for upit in a.upit:
            redci = usud_trazi(upit, limit=a.max)
            log(f"\n== {upit!r}: {len(redci)} pogodaka u lokalnom korpusu")
            for r in redci:
                log(f"  {r['broj']} ({r['datum']}) {r['vrsta']}")
                log(f"    {(r['isjecak'] or '')[:220]}")


if __name__ == "__main__":
    sys.exit(main())
