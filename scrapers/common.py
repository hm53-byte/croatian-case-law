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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
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
    _throttle(url)
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def post(url: str, data=None, json=None, *, timeout: int = 45) -> requests.Response:
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
