# -*- coding: utf-8 -*-
"""
Testovi za PRESUDE: iskljucivo offline, bez ijednog mreznog zahtjeva.

Pokretanje:
    cd /Users/hrvojematej/Desktop/PRESUDE
    scrapers/venv/bin/python -m unittest discover -s tests -v

Sadrzaj:
    mreza_straza.py            putanje + zabrana mreznih poziva
    podaci/                    spremljeni uzorci HTML-a
    test_vektor_cankiraj.py    lomljenje presude na cankove (granica 1600)
    test_anon_datum.py         normalizacija hrvatskih datuma u ISO
    test_anon_search.py        parsiranje rezultata pretrage iz uzorka
    test_analiza_cl55.py       cl. 55. Zakona o sumama vs Zakona o naknadi
    test_store.py             SQLite korpus, inkrementalno spremanje
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mreza_straza  # noqa: E402,F401

MreznaZabrana = mreza_straza.MreznaZabrana
