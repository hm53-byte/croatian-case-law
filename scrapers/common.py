# -*- coding: utf-8 -*-
"""
Zajednički HTTP sloj za sve scrapere u PESUDE/scrapers.

- pristojan rate-limit po hostu (ne ruši javne servise)
- keširanje odgovora na disk (cache/<host>/<sha1>.html)
- automatski retry uz eksponencijalni backoff na 5xx i mrežne greške
- spremanje rezultata kao Markdown u PESUDE/nalazi/

Ovisnosti: pip install requests beautifulsoup4 lxml
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import random
import re
import sys
import time
import unicodedata
import urllib.parse

import requests
from bs4 import BeautifulSoup

BASE_DIR = pathlib.Path(__file__).resolve().parent          # .../PESUDE/scrapers
PROJECT_DIR = BASE_DIR.parent                                # .../PESUDE
OUT_DIR = PROJECT_DIR / "nalazi"
DATA_DIR = PROJECT_DIR / "data"
CACHE_DIR = BASE_DIR / "cache"
for _d in (OUT_DIR, DATA_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# User-Agent govori istinu: ovo je skripta, ne preglednik. Tko smo i gdje je
# kod vidi se iz URL-a repozitorija; operater posluzitelja po tome moze
# prepoznati i blokirati alat, i to je namjerno.
HEADERS = {
    "User-Agent": "croatian-case-law/1.0 (istrazivacki alat; "
                  "+https://github.com/hm53-byte/croatian-case-law)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "hr-HR,hr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
}

RATE_LIMIT_S = 1.5      # min. razmak između zahtjeva na isti host
MAX_RETRIES = 4
_last_hit: dict[str, float] = {}

session = requests.Session()
session.headers.update(HEADERS)


def log(msg: str) -> None:
    print(msg, flush=True)


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc or url


# ------------------------------------------------------------ tvrda zapreka --
# Hostovi ciji robots.txt zabranjuje dohvat (provjereno 14.8.2026.):
#
#   odluke.sudovi.hr   "Disallow: /"; dopustene su samo informativne rute
#                      navedene nize, sto NE ukljucuje /Document/*
#   sljeme.usud.hr     "Disallow: /" bez ijedne iznimke
#
# Svaki mrezni zahtjev prema tim hostovima odbija se izlaznim kodom 3 prije
# nego sto je poslan, osim ako je navedena oznaka pisanog dopustenja izvora:
# varijablom okoline PRESUDE_DOPUSTENJE ili opcijom --dopustenje u CLI-ju
# modula. Ista zapreka, s istim izlaznim kodom, postoji u enumeratoru koji
# nije u repozitoriju (docs/mjerenje.md, odjeljak 8.1). Citanje vec keširanih
# odgovora s diska nije mrezni zahtjev i ne prolazi kroz zapreku.
ROBOTS_ZABRANJENI: dict[str, tuple[str, ...]] = {
    "odluke.sudovi.hr": ("/", "/robots.txt", "/Home/Privacy", "/Home/About",
                         "/Home/Cookies", "/Home/Accessibility",
                         "/Home/UserManual"),
    "sljeme.usud.hr": ("/robots.txt",),
}

DOPUSTENJE = os.environ.get("PRESUDE_DOPUSTENJE", "").strip()
_dopustenje_zabiljezeno = False


def zapreka_robots(url: str) -> None:
    """Odbija mrezni zahtjev prema robots-zabranjenom hostu bez dopustenja.

    Tvrda je namjerno: dize SystemExit(3), koji retry petlje (osim Exception)
    ne hvataju, pa nema tihog zaobilazenja.
    """
    global _dopustenje_zabiljezeno
    host = _host(url).lower()
    dopustene = ROBOTS_ZABRANJENI.get(host)
    if dopustene is None:
        return
    putanja = urllib.parse.urlsplit(url).path or "/"
    if putanja in dopustene:
        return
    if DOPUSTENJE:
        if not _dopustenje_zabiljezeno:
            log(f"[dopustenje] {host}: nastavljam uz oznaku pisanog "
                f"dopustenja {DOPUSTENJE!r}")
            _dopustenje_zabiljezeno = True
        return
    print(
        f"ZAPREKA: robots.txt hosta {host} glasi 'Disallow: /', "
        f"a trazila se ruta {putanja}.\n"
        "Dohvat se ne pokrece bez pisanog dopustenja izvora "
        "(za odluke.sudovi.hr: Ministarstva pravosuda, uprave i digitalne "
        "transformacije).\n"
        "Ako dopustenje postoji, navedi njegovu oznaku (klasa/urbroj):\n"
        "  PRESUDE_DOPUSTENJE='klasa/urbroj' u okolini, ili --dopustenje u CLI-ju.",
        file=sys.stderr)
    raise SystemExit(3)


def _throttle(url: str) -> None:
    host = _host(url)
    dt = time.time() - _last_hit.get(host, 0.0)
    if dt < RATE_LIMIT_S:
        time.sleep(RATE_LIMIT_S - dt)
    _last_hit[host] = time.time()


def _cache_path(url: str, params) -> pathlib.Path:
    key = hashlib.sha1((url + "|" + str(sorted((params or {}).items()))).encode()).hexdigest()
    d = CACHE_DIR / re.sub(r"[^a-z0-9.]+", "_", _host(url).lower())
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.html"


def get(url: str, *, params=None, cache: bool = True, timeout: int = 45) -> str:
    """GET s keširanjem, rate-limitom i retryjem; vraća tekst odgovora."""
    cached = _cache_path(url, params)
    if cache and cached.exists() and cached.stat().st_size > 0:
        return cached.read_text(encoding="utf-8", errors="replace")

    zapreka_robots(url)
    last_err = None
    for pokusaj in range(1, MAX_RETRIES + 1):
        try:
            _throttle(url)
            r = session.get(url, params=params, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            if not r.encoding or r.encoding.lower() == "iso-8859-1":
                r.encoding = r.apparent_encoding or "utf-8"
            text = r.text
            if cache:
                cached.write_text(text, encoding="utf-8")
            return text
        except Exception as e:  # noqa: BLE001
            last_err = e
            if pokusaj < MAX_RETRIES:
                pauza = (2 ** pokusaj) + random.uniform(0, 1.0)
                log(f"    [retry {pokusaj}/{MAX_RETRIES - 1}] {e} — čekam {pauza:.1f}s")
                time.sleep(pauza)
    raise RuntimeError(f"GET nije uspio nakon {MAX_RETRIES} pokušaja: {url} — {last_err}")


def get_bytes(url: str, *, timeout: int = 60) -> bytes:
    """GET binarnog sadržaja (PDF) — bez keširanja u HTML cache."""
    zapreka_robots(url)
    _throttle(url)
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def post(url: str, data=None, json=None, *, timeout: int = 45) -> requests.Response:
    zapreka_robots(url)
    _throttle(url)
    r = session.post(url, data=data, json=json, timeout=timeout)
    r.raise_for_status()
    return r


def soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001
        return BeautifulSoup(html, "html.parser")


def slugify(text: str, maxlen: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text[:maxlen] or "dokument"


def save_md(filename_stem: str, *, naslov: str, tijelo: str, izvor_url: str,
            meta: dict | None = None, subdir: str = "") -> pathlib.Path:
    """Sprema dokument kao PESUDE/nalazi/[subdir/]<stem>.md sa standardnim zaglavljem."""
    d = OUT_DIR / subdir if subdir else OUT_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{slugify(filename_stem)}.md"
    lines = [f"# {naslov}", ""]
    for k, v in (meta or {}).items():
        if v:
            lines.append(f"- **{k}:** {v}")
    lines += [f"- **Izvor:** {izvor_url}", "", "---", "", (tijelo or "").strip(), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def progress(i: int, ukupno: int, prefix: str = "") -> None:
    """Jednoredni pokazatelj napretka za duge crawlove."""
    if ukupno <= 0:
        return
    pct = 100.0 * i / ukupno
    sys.stdout.write(f"\r  {prefix}{i}/{ukupno} ({pct:5.1f}%)   ")
    sys.stdout.flush()
    if i >= ukupno:
        sys.stdout.write("\n")
