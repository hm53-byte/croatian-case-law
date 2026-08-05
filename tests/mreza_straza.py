# -*- coding: utf-8 -*-
"""
Mrezna straza + postavljanje putanja za testove.

Svaki testni modul uvozi ovaj modul prvi. Time se postize dvoje:

1. mapa scrapers/ dolazi na sys.path, pa se moduli projekta mogu uvoziti
   (vektor, anon, store, analiza_cl55);
2. svaki pokusaj otvaranja TCP veze ili DNS upita rusi test umjesto da
   tiho ode na javni portal. Testovi zato ne opterecuju odluke.sudovi.hr
   niti ovise o dostupnosti mreze.

Straza se postavlja pri uvozu i idempotentna je.
"""
import os
import socket
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
KORIJEN = os.path.dirname(TESTS_DIR)
SCRAPERS_DIR = os.path.join(KORIJEN, "scrapers")
PODACI_DIR = os.path.join(TESTS_DIR, "podaci")

for _p in (SCRAPERS_DIR, TESTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class MreznaZabrana(AssertionError):
    """Test je pokusao otvoriti mreznu vezu. To nije dopusteno."""


def _zabrani(*args, **kwargs):
    raise MreznaZabrana(
        "Testovi ne smiju otvarati mrezne veze. "
        "Uzorke HTML-a stavi u tests/podaci/ i podmetni ih umjesto common.get."
    )


_zabrani.je_straza = True


def postavi():
    """Zamjenjuje mrezne ulaze socketa zabranom. Sigurno je zvati vise puta."""
    if getattr(socket.getaddrinfo, "je_straza", False):
        return
    # Stvaranje socket objekta ostaje dopusteno (neki moduli ga rade pri
    # uvozu), ali spajanje i razrjesavanje imena ne.
    socket.socket.connect = _zabrani
    socket.socket.connect_ex = _zabrani
    socket.create_connection = _zabrani
    socket.getaddrinfo = _zabrani


postavi()


def uzorak(ime):
    """Puna putanja do datoteke s uzorkom u tests/podaci/."""
    return os.path.join(PODACI_DIR, ime)
