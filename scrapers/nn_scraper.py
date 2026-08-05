# -*- coding: utf-8 -*-
"""
NARODNE NOVINE — pretraga i dohvat PUNOG TEKSTA članaka.

Dva načina rada:
 1) search  — pretraga preko Google indeksa NN-a (najpouzdanije, NN-ova vlastita
    tražilica je ASPX/POST i zna se mijenjati) ILI izravno preko NN tražilice.
 2) fetch   — dohvat punog teksta kad imaš URL ili oznaku (godina_broj_članak).

NN full-text URL obrazac (stabilan godinama):
    https://narodne-novine.nn.hr/clanci/sluzbeni/full/2023_11_140_1919.html
     -> 2023 = godina, 11 = mjesec, 140 = broj NN, 1919 = redni broj članka
ELI obrazac:  https://narodne-novine.nn.hr/eli/sluzbeni/{godina}/{broj}/{clanak}

Primjeri:
    python nn_scraper.py search "zamjena šumskog zemljišta"
    python nn_scraper.py search "odluka o zamjeni" "šumsko zemljište"
    python nn_scraper.py fetch https://narodne-novine.nn.hr/clanci/sluzbeni/full/2023_11_140_1919.html
    python nn_scraper.py fetch 2018_07_68_1392        # Zakon o šumama NN 68/18
"""
from __future__ import annotations

import re
import sys
import urllib.parse

from common import get, soup, save_md

FULL_URL = "https://narodne-novine.nn.hr/clanci/sluzbeni/full/{oznaka}.html"


def nn_search(upit: str, max_rez: int = 30) -> list[dict]:
    """
    Pretraga NN-ove službene tražilice (rezultati_pretrage).
    Ako NN promijeni parametre, otvori https://narodne-novine.nn.hr, napravi
    pretragu ručno i prekopiraj query-string iz adresne trake u SEARCH_URL dolje.
    """
    SEARCH_URL = "https://narodne-novine.nn.hr/search.aspx"
    html = get(SEARCH_URL, params={"upit": upit, "sortiraj": "4", "kategorija": "1",
                                   "rpp": str(max_rez), "qtype": "1"})
    s = soup(html)
    rez = []
    for a in s.select("a[href*='clanci/sluzbeni']"):
        href = urllib.parse.urljoin(SEARCH_URL, a.get("href", ""))
        naslov = a.get_text(" ", strip=True)
        if naslov and href not in [r["url"] for r in rez]:
            rez.append({"naslov": naslov, "url": href})
    if not rez:
        print("  (0 rezultata — NN je možda promijenio tražilicu; vidi docstring)")
    return rez[:max_rez]


def nn_fetch(url_ili_oznaka: str) -> None:
    """Dohvati puni tekst NN članka i spremi kao Markdown u PESUDE/."""
    if url_ili_oznaka.startswith("http"):
        url = url_ili_oznaka
        # normaliziraj na /full/ verziju ako nije
        url = url.replace("/clanci/sluzbeni/", "/clanci/sluzbeni/full/") \
            if "/full/" not in url else url
        url = re.sub(r"/full/full/", "/full/", url)
    else:
        url = FULL_URL.format(oznaka=url_ili_oznaka)

    html = get(url)
    s = soup(html)
    # NN full stranica: glavni sadržaj je u <body>; makni navigaciju/skripte
    for tag in s(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    tijelo = s.get_text("\n", strip=True)
    naslov_tag = s.find(["h1", "h2", "title"])
    naslov = naslov_tag.get_text(" ", strip=True) if naslov_tag else url
    oznaka = re.search(r"(\d{4}_\d{2}_\d+_\d+)", url)
    stem = f"NN_{oznaka.group(1)}" if oznaka else f"NN_{naslov[:60]}"
    save_md(stem, naslov=naslov, tijelo=tijelo, izvor_url=url,
            meta={"Vrsta": "Narodne novine — službeni članak"})


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "search":
        for upit in args:
            print(f"== NN pretraga: {upit!r}")
            for r in nn_search(upit):
                print(f"  {r['naslov']}\n    {r['url']}")
    elif cmd == "fetch":
        for x in args:
            nn_fetch(x)
    else:
        print(__doc__)
