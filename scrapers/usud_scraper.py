# -*- coding: utf-8 -*-
"""
USTAVNI SUD RH — pretraga prakse (sljeme.usud.hr) + dohvat punog teksta odluka.

Baza odluka Ustavnog suda je stari Lotus-Notes sustav (praksaw.nsf) koji, za
razliku od SupraNove, radi preko običnih GET URL-ova pa je scraping jednostavan.

Ako se struktura promijeni: otvori https://www.usud.hr -> "Praksa Ustavnog suda"
-> napravi pretragu i prekopiraj URL obrazac u SEARCH_URL.

Primjeri:
    python usud_scraper.py search "zamjena šumskog zemljišta"
    python usud_scraper.py search "zakon o šumama"
    python usud_scraper.py fetch <puni-URL-odluke>
"""
from __future__ import annotations

import sys
import urllib.parse

from common import get, soup, save_md

BASE = "https://sljeme.usud.hr"
# Notes full-text pretraga: SearchView s parametrom Query
SEARCH_URL = (BASE + "/usud/praksaw.nsf/Praksa?SearchView&Query={q}"
                     "&SearchMax=100&SearchOrder=4")


def usud_search(upit: str) -> list[dict]:
    q = urllib.parse.quote(f'"{upit}"')
    html = get(SEARCH_URL.format(q=q))
    s = soup(html)
    rez = []
    for a in s.select("a[href*='praksaw.nsf']"):
        href = urllib.parse.urljoin(BASE, a.get("href", ""))
        txt = a.get_text(" ", strip=True)
        if txt and "SearchView" not in href and href not in [r["url"] for r in rez]:
            rez.append({"naslov": txt, "url": href})
    if not rez:
        print("  (0 rezultata — provjeri SEARCH_URL obrazac, vidi docstring)")
    return rez


def usud_fetch(url: str) -> None:
    html = get(url)
    s = soup(html)
    for tag in s(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    tijelo = s.get_text("\n", strip=True)
    naslov_tag = s.find(["h1", "h2", "title"])
    naslov = naslov_tag.get_text(" ", strip=True) if naslov_tag else "Odluka USUD"
    save_md(f"RH_USUD_{naslov[:60]}", naslov=naslov, tijelo=tijelo,
            izvor_url=url, meta={"Vrsta": "odluka Ustavnog suda RH"})


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "search":
        for upit in args:
            print(f"== USUD pretraga: {upit!r}")
            for r in usud_search(upit):
                print(f"  {r['naslov']}\n    {r['url']}")
    elif cmd == "fetch":
        for u in args:
            usud_fetch(u)
    else:
        print(__doc__)
