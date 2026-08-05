# -*- coding: utf-8 -*-
"""
NARODNE NOVINE - pretraga i dohvat PUNOG TEKSTA članaka.

Dva načina rada:
 1) search  - pretraga preko NN-ove vlastite tražilice (search.aspx).
    Ide OBIČNIM GET-om; POST i __VIEWSTATE nisu potrebni. Server na ispravan
    POST ionako odgovori preusmjerenjem na isti takav GET.
 2) fetch   - dohvat punog teksta kad imaš URL ili oznaku (godina_broj_članak).

OGRANIČENJA pretrage (provjereno uživo, kolovoz 2026.):
 - Obvezni su parametri qtype=3 (pretraga punog teksta službenog dijela) i
   pretraga=da. Bez pretraga=da stranica ostaje u načinu naslovnice i javi
   "Ukupno je pronađeno -1 dokumenata" (-1 je interna oznaka greške), a upit
   se uopće ne primjenjuje. qtype=1 je pregled po izdanju, ne pretraga.
 - rpp prima samo vrijednosti 10, 20, 50, 100 i 200; sve ostalo se ignorira.
   Modul zato zaokruži max_rez naviše na dopuštenu vrijednost, a za veće
   količine pagina preko parametra str (0-baziran indeks stranice).
 - Službeni NN API (/api/index, /api/editions, /api/acts, /api/act) i ELI
   sučelje (/eli/sluzbeni/{godina}/{broj}/{akt}[/json-ld|/rdf]) daju SAMO
   metapodatke po koordinatama dio/godina/broj/akt. Tekstualne pretrage ondje
   NEMA, pa search.aspx nema zamjene.
 - Ako NN promijeni sučelje pa pretraga presuši, zaobilazak je nn_fetch s
   poznatom oznakom NN-a ili gotov popis POPIS_NN u zakoni.py.

NN full-text URL obrazac (stabilan godinama):
    https://narodne-novine.nn.hr/clanci/sluzbeni/full/2023_11_140_1919.html
     -> 2023 = godina, 11 = mjesec, 140 = broj NN, 1919 = redni broj članka
ELI obrazac:  https://narodne-novine.nn.hr/eli/sluzbeni/{godina}/{broj}/{clanak}

Primjeri:
    python nn_scraper.py search "zamjena šumskog zemljišta"
    python nn_scraper.py search "odluka o zamjeni" "šumsko zemljište"
    python nn_scraper.py search --naslovi "zakon o šumama"
    python nn_scraper.py fetch https://narodne-novine.nn.hr/clanci/sluzbeni/full/2023_11_140_1919.html
    python nn_scraper.py fetch 2018_07_68_1392        # Zakon o šumama NN 68/18
"""
from __future__ import annotations

import re
import sys
import urllib.parse

from common import get, soup, save_md

FULL_URL = "https://narodne-novine.nn.hr/clanci/sluzbeni/full/{oznaka}.html"
SEARCH_URL = "https://narodne-novine.nn.hr/search.aspx"

# Tražilica prihvaća samo ove vrijednosti za "rezultata po stranici".
RPP_DOPUSTENI = (10, 20, 50, 100, 200)


def _rpp(trazeno: int) -> int:
    """Zaokruži željeni broj rezultata naviše na vrijednost koju NN prima."""
    for v in RPP_DOPUSTENI:
        if trazeno <= v:
            return v
    return RPP_DOPUSTENI[-1]


def _stavka(a, omotac=None) -> dict | None:
    """Iz <a> (i po mogućnosti iz div.searchListItem oko njega) složi rezultat."""
    href = urllib.parse.urljoin(SEARCH_URL, a.get("href", ""))
    # Unutar <a> stoji skriveni <span class="score"> s ocjenom relevantnosti;
    # bez uklanjanja bi se zalijepio u naslov ("Zakon o šumama 138,82986").
    for sc in a.select("span.score"):
        sc.decompose()
    naslov = a.get_text(" ", strip=True)
    if not naslov or "clanci/sluzbeni" not in href:
        return None
    oznaka = re.search(r"(\d{4}_\d{2}_\d+_\d+)", href)
    meta = omotac.select_one("div.official-number-and-date") if omotac else None
    isjecak = omotac.select_one("span.snippet") if omotac else None
    return {
        "naslov": naslov,
        "url": href,
        "oznaka": oznaka.group(1) if oznaka else "",
        "izvor": meta.get_text(" ", strip=True) if meta else "",
        "isjecak": isjecak.get_text(" ", strip=True) if isjecak else "",
    }


def _parsiraj(html: str) -> tuple[list[dict], int]:
    """Vrati (rezultati stranice, prijavljeni ukupan broj dokumenata ili -1)."""
    s = soup(html)
    ukupno = -1
    m = re.search(r"pronađen\w*\s+(-?[\d.\s]+?)\s*dokumen", s.get_text(" ", strip=True))
    if m:
        try:
            ukupno = int(re.sub(r"[.\s]", "", m.group(1)))
        except ValueError:
            ukupno = -1

    stavke = s.select("div.searchListItem")
    rez = []
    for omotac in stavke:
        a = omotac.select_one("a[href*='clanci/sluzbeni']")
        if a is None:
            continue
        r = _stavka(a, omotac)
        if r:
            rez.append(r)
    if not stavke:
        # Rezervni put ako NN preimenuje razred omotača: sirovi linkovi.
        for a in s.select("a[href*='clanci/sluzbeni']"):
            r = _stavka(a)
            if r:
                rez.append(r)
    return rez, ukupno


def nn_search(upit: str, max_rez: int = 30, *, samo_naslovi: bool = False,
              sortiraj: str = "0") -> list[dict]:
    """
    Pretraga NN-ove službene tražilice. Radni oblik upita (obični GET):

        /search.aspx?upit={pojam}&sortiraj=0&kategorija=1
                    &rpp={10|20|50|100|200}&qtype=3&pretraga=da
                    [&naslovi=da][&str={0-baziran indeks stranice}]

    qtype=3      pretraga punog teksta službenog dijela (qtype=1 je pregled izdanja)
    pretraga=da  bez toga se upit ne primjenjuje i vraća se "-1 dokumenata"
    sortiraj     0 = po relevantnosti (za pretragu po pojmu jedino smisleno),
                 4 = kronološki
    naslovi=da   traži samo po naslovu propisa; uže i preciznije

    Argumenti:
        max_rez       koliko rezultata najviše vratiti; preko 200 se pagina
        samo_naslovi  proslijedi naslovi=da
        sortiraj      "0" relevantnost, "4" kronološki

    Vraća listu rječnika s ključevima: naslov, url, oznaka, izvor, isjecak.

    Ako NN promijeni parametre: otvori https://narodne-novine.nn.hr, napravi
    pretragu ručno i prekopiraj query-string iz adresne trake u params dolje.
    Zaobilazni put bez tražilice: nn_fetch("2018_07_68_1392") ili zakoni.py.
    """
    rpp = _rpp(max_rez)
    max_stranica = max(1, -(-max_rez // rpp))
    rez: list[dict] = []
    vidjeni: set[str] = set()

    for stranica in range(max_stranica):
        params = {"upit": upit, "sortiraj": sortiraj, "kategorija": "1",
                  "rpp": str(rpp), "qtype": "3", "pretraga": "da"}
        if samo_naslovi:
            params["naslovi"] = "da"
        if stranica:
            params["str"] = str(stranica)

        nova, ukupno = _parsiraj(get(SEARCH_URL, params=params))
        if ukupno == -1 and stranica == 0:
            print("  (!) NN je vratio '-1 dokumenata': tražilica nije izvela "
                  "pretragu; provjeri parametre qtype=3 i pretraga=da")
        prije = len(rez)
        for r in nova:
            if r["url"] not in vidjeni:
                vidjeni.add(r["url"])
                rez.append(r)
        if len(rez) == prije or len(rez) >= max_rez:
            break   # nema više novih stavki ili je kvota popunjena

    if not rez:
        print("  (0 rezultata; ako pojam sigurno postoji, vidi ograničenja u "
              "docstringu modula ili koristi nn_fetch s poznatom oznakom)")
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
        samo_naslovi = "--naslovi" in args      # traži samo po naslovu propisa
        args = [a for a in args if a != "--naslovi"]
        for upit in args:
            print(f"== NN pretraga: {upit!r}{' (samo naslovi)' if samo_naslovi else ''}")
            for r in nn_search(upit, samo_naslovi=samo_naslovi):
                print(f"  {r['naslov']}")
                if r["izvor"]:
                    print(f"    {r['izvor']}")
                print(f"    {r['url']}")
    elif cmd == "fetch":
        for x in args:
            nn_fetch(x)
    else:
        print(__doc__)
