# -*- coding: utf-8 -*-
"""
Preuzimanje PUNIH TEKSTOVA propisa u PRESUDE/SUME55/zakoni/.

Izvori:
  - narodne-novine.nn.hr  — izvorni službeni tekstovi (svaki NN broj zasebno)
  - zakon.hr              — pročišćeni (konsolidirani) tekst

Pokretanje:
    python zakoni.py            # skine sve iz popisa POPIS
    python zakoni.py --popis    # samo ispiše što bi skinuo
"""
from __future__ import annotations

import argparse
import re

from common import get, soup, PROJECT_DIR, log

ZAKONI_DIR = PROJECT_DIR / "SUME55" / "zakoni"

NN_FULL = "https://narodne-novine.nn.hr/clanci/sluzbeni/{oznaka}.html"

# oznaka NN = GODINA_MJESEC_BROJ_REDNIBROJ
POPIS_NN = [
    ("2018_07_68_1392",  "Zakon o šumama (NN 68/18) — izvorni tekst"),
    ("2024_03_36_576",   "Zakon o izmjenama i dopunama Zakona o šumama (NN 36/24)"),
    ("2019_05_55_1045",  "Uredba o zakupu šumskog zemljišta u vlasništvu RH (NN 55/19)"),
    ("2019_09_87_1752",  "Uredba o osnivanju prava građenja i služnosti na šumi i "
                         "šumskom zemljištu u vlasništvu RH (NN 87/19)"),
    ("2000_01_8_89",     "Odluka Ustavnog suda RH U-I-374/1998 od 12.1.2000. — "
                         "ukidanje zabrane dosjelosti na državnim šumama (NN 8/00)"),
    ("2005_11_140_2642", "Zakon o šumama (NN 140/05) — PRETHODNI zakon, izvorni tekst"),
    ("1990_12_52_969",   "Zakon o šumama (NN 52/90) — pročišćeni tekst starog zakona"),
    ("2018_12_115_2249", "Zakon o izmjenama i dopuni Zakona o šumama (NN 115/18)"),
    ("2008_11_129_3681", "Zakon o izmjeni i dopunama Zakona o šumama (NN 129/08)"),
    ("2014_07_94_1884",  "Zakon o izmjenama i dopunama Zakona o šumama (NN 94/14)"),
]

POPIS_ZAKON_HR = [
    ("https://www.zakon.hr/z/294/zakon-o-sumama",
     "Zakon o šumama — pročišćeni tekst (zakon.hr)"),
]


def ocisti(html: str, selektor: str | None = None) -> str:
    s = soup(html)
    for tag in s(["script", "style", "nav", "header", "footer", "noscript", "iframe"]):
        tag.decompose()
    cilj = s.select_one(selektor) if selektor else None
    txt = (cilj or s).get_text("\n", strip=True)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt


def skini_nn(oznaka: str, opis: str) -> None:
    url = NN_FULL.format(oznaka=oznaka)
    txt = ocisti(get(url))
    ZAKONI_DIR.mkdir(parents=True, exist_ok=True)
    put = ZAKONI_DIR / f"NN_{oznaka}.md"
    put.write_text(f"# {opis}\n\n- **Izvor:** {url}\n- **NN oznaka:** {oznaka}\n\n---\n\n{txt}\n",
                   encoding="utf-8")
    log(f"  [OK] {put.name}  ({len(txt):,} znakova)")


def skini_zakon_hr(url: str, opis: str) -> None:
    txt = ocisti(get(url))
    ZAKONI_DIR.mkdir(parents=True, exist_ok=True)
    ime = re.sub(r"[^a-z0-9]+", "_", url.rsplit("/", 1)[-1]) or "zakon"
    put = ZAKONI_DIR / f"PROCISCENI_{ime}.md"
    put.write_text(f"# {opis}\n\n- **Izvor:** {url}\n\n---\n\n{txt}\n", encoding="utf-8")
    log(f"  [OK] {put.name}  ({len(txt):,} znakova)")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--popis", action="store_true")
    a = p.parse_args()

    if a.popis:
        for o, d in POPIS_NN:
            log(f"  NN  {o}  {d}")
        for u, d in POPIS_ZAKON_HR:
            log(f"  WEB {u}  {d}")
        return

    log(f"Spremam u: {ZAKONI_DIR}")
    for oznaka, opis in POPIS_NN:
        try:
            skini_nn(oznaka, opis)
        except Exception as e:  # noqa: BLE001
            log(f"  [!] {oznaka}: {e}")
    for url, opis in POPIS_ZAKON_HR:
        try:
            skini_zakon_hr(url, opis)
        except Exception as e:  # noqa: BLE001
            log(f"  [!] {url}: {e}")


if __name__ == "__main__":
    main()
