# -*- coding: utf-8 -*-
"""
Doktrina: klijent za HRCAK (hrcak.srce.hr) preko OAI-PMH.

ZASTO OAI, A NE STRUGANJE
-------------------------
Portal odluke.sudovi.hr ima robots.txt `Disallow: /` i zato se ne strugao.
HRCAK je suprotan slucaj: nudi OAI-PMH na https://hrcak.srce.hr/oai/, protokol
napravljen upravo za masovno preuzimanje metapodataka, a robots.txt zabranjuje
samo /pretraga*. Dohvat ide iskljucivo kroz /oai/ i kroz /file/ poveznice koje
sam OAI objavljuje.

DVA FORMATA, JER NIJEDAN SAM NIJE DOVOLJAN
------------------------------------------
Izmjereno na oai:hrcak.srce.hr:78896 (Policija i sigurnost):
  oai_dc       ima dc:rights s punim tekstom licence i dc:subject (kljucne
               rijeci), ali za vecinu zapisa NEMA poveznicu na PDF.
  oai_openaire ima <oaire:file objectType="fulltext"> s tocnim /file/ URL-om,
               ali od prava nosi samo COAR oznaku "open access", bez teksta
               licence.
Zato harvest hoda skupom DVA puta: prolaz 1 (oai_dc) upisuje metapodatke i
licencu, prolaz 2 (oai_openaire) dopunjava pdf_url. Oba prolaza idu po
stranicama od 100 zapisa, pa je trosak dvostrukog hoda oko 2 zahtjeva na 100
clanaka, a ne jedan zahtjev po clanku.

LICENCA JE NA RAZINI CASOPISA, NE CLANKA
----------------------------------------
Kljucni nalaz izvidnice: dc:rights je identican za sve zapise unutar jednog
seta. Zbornik PF Rijeka to i dokazuje - njegov tekst kaze da su radovi prije
vol. 44/2 bili CC BY-NC a sada su CC BY-NC-ND, ali taj kombinirani tekst nose
SVI zapisi, ukljucujuci one iz 2006. Iz OAI-ja se dakle licenca pojedinog
clanka NE MOZE pouzdano utvrditi. Modul to ne skriva:
  - stupac `licenca_razina` je uvijek 'casopis',
  - stupac `licenca_nejasno` = 1 kad tekst spominje vise razlicitih CC oznaka,
    i tada se uzima NAJSTROZA od njih,
  - puni tekst licence cuva se doslovno u `licenca_tekst`, pa je svaka
    klasifikacija provjerljiva unatrag.

STO SE SMIJE DOHVATITI
----------------------
Zadano se PDF dohvaca SAMO za zapise kojima klasifikator prizna izricito pravo
daljnjeg sirenja (CC licence i proza koja redistribuciju doslovno dopusta).
Za sve ostalo se sprema samo metapodatak i poveznica. Zastavica --osobno
prosiruje dohvat na clanke bez jasne otvorene licence, ali ih obiljezava
`samo_lokalno=1`: takvi zapisi su za osobno istrazivanje i NE izlaze iz ove
baze. `info:eu-repo/semantics/openAccess` znaci samo besplatan pristup, ne i
pravo daljnjeg sirenja, pa se sam za sebe vodi kao 'nepoznata'.

PDF SE NE POHRANJUJE
--------------------
PDF postoji samo kao `bytes` u memoriji, unutar io.BytesIO, dok pypdf iz njega
ne izvuce tekst. Nakon toga se odbacuje. Nema privremene datoteke, nema mape s
PDF-ovima, na disk ide samo izvuceni tekst (zlib-6) i metapodaci. Isto vrijedi
za svaki modul u ovom tijeku. Dohvat PDF-a NAMJERNO zaobilazi common.get, koji
kesira odgovor kao tekst i time bi binarni sadrzaj i pokvario i ostavio na disku.

NE VJERUJE SE SVEMU STO pypdf VRATI
-----------------------------------
Dio starijih PDF-ova ima ugradenu podskupinu fonta bez ToUnicode CMap-a, pa
pypdf umjesto znakova vraca imena glifova ("/g51/g53/g40..."). Takav izlaz ima
uvjerljivu duljinu, pa bi neprovjeren usao u korpus kao smece. Svaki izvuceni
tekst zato dobiva `tekst_status` (ok | sken | bez-unicode | prazno) i u bazu
ulazi samo 'ok'. Ostalo ostavlja trag u metapodacima, ali ne truje pretragu.
Izmjereno 2026-08-06: Policija i sigurnost godiste 2011 daje 8/8 'bez-unicode',
dok isti casopis od 2024. te HKJU, Zbornik PF Split i Zbornik PF Rijeka od
2022-23 daju uredan tekst s ocuvanim dijakriticima.

STO JE PROVJERENO (2026-08-06)
------------------------------
Sve brojke nize su izmjerene, ne procijenjene:
  - ListSets vraca 581 set, od cega 22 pravna i pravno-srodna casopisa;
  - `doktrina.py provjeri` prolazi 14/14 nad DOSLOVNIM dc:rights tekstovima;
  - harvest journal:399 (12 zapisa) -> 12/12 pdf poveznica, 12/12 'ok' teksta;
  - harvest journal:311 (8 zapisa)  -> 8/8 pdf poveznica, 8/8 'bez-unicode';
  - harvest journal:135 (5 zapisa)  -> licenca 'osobno', 0 dohvacenih PDF-ova;
  - u kesu nakon svega: 35 XML odgovora, 0 PDF-ova.
NIJE provjereno: ponasanje na punom setu od 9.360 clanaka, jer veliko
preuzimanje nije pokretano.

PRISTOJNOST
-----------
Rate limit 1,5 s po hostu nasljeduje se iz common.get. Za /file/ se dodaje jos
PDF_PAUZA_S jer je izmjereno da Hrcak na rafal zahtjeva vraca HTTP 418: tri
uzastopna dohvata istog PDF-a s razmakom 8 s vratila su 200, a isti ti dohvati
bez pauze 418. 418 se zato tretira kao "uspori", s backoffom, a ne kao greska.
Jedna dretva, resumption tokeni se postuju.

Pokretanje:
    python doktrina.py setovi [--pravni] [--osvjezi]
    python doktrina.py harvest --set journal:311 [--max N] [--od 2024-01-01]
                               [--tekst] [--osobno] [--puno] [--svjeze]
    python doktrina.py stat [--set journal:311]
    python doktrina.py trazi "stjecanje bez osnove" [--k 10]

Ovisnosti: requests, pypdf (oboje vec u requirements.txt).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import pathlib
import random
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import requests

import common
from common import DATA_DIR, log
from store import odzipaj, zipaj

OAI = "https://hrcak.srce.hr/oai/"
DB_PATH = DATA_DIR / "doktrina.sqlite"

# Dodatna pauza samo za /file/ dohvate, povrh 1,5 s iz common._throttle.
# Vidi docstring: Hrcak na rafal vraca 418.
PDF_PAUZA_S = 3.0
PDF_POKUSAJA = 5

# Ispod ovoliko znakova po stranici PDF nema tekstualni sloj (sken bez OCR-a).
# 80 je namjerno nisko: stranica s golim brojem stranice i zaglavljem ima
# 20-40 znakova, a najrjeda stvarna stranica teksta ima vise od 200.
PRAG_SKENA = 80

NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
    "oaire": "http://namespace.openaire.eu/schema/oaire",
    "datacite": "http://datacite.org/schema/kernel-4",
}


class OaiGreska(RuntimeError):
    """OAI je vratio <error code=...>. `kod` je strojno citljiv."""

    def __init__(self, kod: str, poruka: str):
        super().__init__(f"OAI error [{kod}]: {poruka}")
        self.kod = kod
        self.poruka = poruka


# ============================================================== LICENCE ======
#
# Klasifikator radi nad SPOJENIM tekstom svih dc:rights elemenata zapisa.
# Redoslijed provjera je bitan i nije proizvoljan:
#   1. "all rights reserved" pobjeduje sve ostalo (Pravnik nosi i openAccess
#      token i "All rights reserved" - token gubi).
#   2. CC oznaka je jedina koja daje pravo daljnjeg sirenja bez tumacenja.
#   3. Proza se tumaci restriktivno: ako igdje stoji "can not"/"may not", zapis
#      ide u 'proza-ogranicena' bez obzira na to sto jos pise.
#   4. Goli info:eu-repo/semantics/openAccess je 'nepoznata', NE otvorena.
#
# `redistribucija` je jedino polje koje odlucuje smije li se PDF dohvatiti.

# Kod -> (smije li se dalje siriti, ljudski opis)
LICENCE: Dict[str, Tuple[int, str]] = {
    "cc-by":        (1, "CC BY"),
    "cc-by-sa":     (1, "CC BY-SA"),
    "cc-by-nd":     (1, "CC BY-ND"),
    "cc-by-nc":     (1, "CC BY-NC"),
    "cc-by-nc-sa":  (1, "CC BY-NC-SA"),
    "cc-by-nc-nd":  (1, "CC BY-NC-ND"),
    "cc0":          (1, "CC0 / javna domena"),
    "proza-otvorena": (1, "proza koja izricito dopusta redistribuciju"),
    "proza-ogranicena": (0, "proza s izricitim zabranama, bez CC oznake"),
    "osobno":       (0, "samo osobna ili obrazovna uporaba"),
    "dozvola":      (0, "potrebna dozvola urednistva"),
    "sva-prava":    (0, "sva prava pridrzana"),
    "nepoznata":    (0, "nema licence, samo openAccess token ili nista"),
}

# Od najstroze prema najslobodnijoj. Kad tekst spominje vise CC oznaka
# (Zbornik PF Rijeka), uzima se PRVA nadena po ovom redu, dakle najstroza.
CC_PO_STROGOSTI = ("cc-by-nc-nd", "cc-by-nc-sa", "cc-by-nd", "cc-by-sa",
                   "cc-by-nc", "cc-by", "cc0")

_CC_URL = re.compile(r"creativecommons\.org/(?:licenses|publicdomain)/([a-z0-9\-]+)", re.I)

# Hvata i "CC BY-NC-ND" i "Creative Commons license BY-NC-ND" i "Creative
# Commons licencija BY". Umetnute rijeci (license/licence/licencij*/oznaka)
# moraju biti dopustene: Zbornik PF Split pise "Creative Commons license
# BY-NC-ND", sto je uzi oblik s literalnim "CC" propustao kao 'nepoznata'.
_CC_TXT = re.compile(
    r"(?:\bCC\b|creative\s+commons)"
    r"(?:[\s\-]*(?:licen[cs]\w*|oznak\w*|uvjet\w*|licencij\w*|attribution))*"
    # Razdjelnik mora dopustiti zagrade i navodnike: Kriminologija & socijalna
    # integracija pise 'Creative Commons license (BY-NC-ND)'.
    r"""[\s\-:,"'“”()\[\]]*"""
    r"\b(BY(?:[\s\-]?N[CD])*(?:[\s\-]?SA)?|ZERO|0)\b", re.I)

# Glagoli daljnjeg sirenja. NAMJERNO bez 'reproduce' i 'use': Pravni vjesnik
# kaze "may be used and reproduced for personal or educational purposes", sto
# nije pravo daljnjeg sirenja nego dopustenje osobne uporabe.
_SIRI = re.compile(r"\b(re-?distribut\w+|distribut\w+|share|shared|sharing|"
                   r"copy|copies|copied|umno[zž]\w+|dijelit\w*|raspa[cč]\w+)\b", re.I)
_DOPUSTA = re.compile(r"\b(allowed|permitted|free to|entitled|granted|may|can|"
                      r"dopu[sš]t\w*|smij\w*|slobodno)\b", re.I)
_NIJECE = re.compile(r"\b(not|n't|nor|nikad\w*|ne\s+smij\w*)\b", re.I)
_OSOBNO = re.compile(r"\b(personal|educational|osobn\w+|obrazovn\w+)\b"
                     r"[^.;]{0,60}?\b(purpose\w*|use|uporab\w+|svrh\w+|potreb\w+)\b", re.I)

# Puni engleski nazivi ("Attribution-NonCommercial-NoDerivatives 4.0").
_CC_IME = re.compile(
    r"\battribution(\s*[\-–]?\s*(?:non-?commercial))?"
    r"(\s*[\-–]?\s*(?:no-?deriv\w*))?"
    r"(\s*[\-–]?\s*(?:share-?alike))?", re.I)


def _normkod(s: str) -> str:
    """'BY - NC-ND' -> 'cc-by-nc-nd'; 'zero'/'0' -> 'cc0'."""
    s = re.sub(r"[\s_]+", "-", s.strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    if s in ("0", "zero"):
        return "cc0"
    if s.startswith("publicdomain") or s.startswith("zero"):
        return "cc0"
    return "cc-" + s if not s.startswith("cc") else s


def _dopusta_sirenje(tekst: str, prozor: int = 70) -> bool:
    """
    True ako tekst igdje dopusta daljnje sirenje.

    Za svaki glagol sirenja gleda `prozor` znakova ispred njega: mora sadrzavati
    rijec dopustenja i ne smije sadrzavati nijecnicu. Time se "can be downloaded
    and redistributed" prizna, a "cannot be redistributed" ne.
    """
    for m in _SIRI.finditer(tekst):
        ispred = tekst[max(0, m.start() - prozor):m.start()]
        # nijecnica se broji samo ako je iza nje jos i rijec dopustenja, tj.
        # ako pripada ovom glagolu; zato se gleda dio od zadnjeg dopustenja
        d = None
        for x in _DOPUSTA.finditer(ispred):
            d = x
        if d is None:
            continue
        if _NIJECE.search(ispred[d.start():]):
            continue
        # "cannot"/"can not" se ne razlaze u _DOPUSTA/_NIJECE par, pa zasebno
        if re.search(r"\b(can\s?not|cannot|may not|must not)\b",
                     ispred[max(0, d.start() - 4):], re.I):
            continue
        return True
    return False


def klasificiraj_licencu(rights: Sequence[str]) -> Tuple[str, int, int]:
    """
    dc:rights -> (kod, redistribucija, nejasno).

    `nejasno` = 1 kad tekst navodi vise razlicitih CC oznaka, pa se licenca
    pojedinog clanka iz OAI-ja ne moze utvrditi. Tada je vracen kod NAJSTROZE
    nadene oznake, sto je jedini siguran izbor.
    """
    tekst = " ".join(x for x in rights if x)
    if not tekst.strip():
        return "nepoznata", 0, 0
    t = tekst.lower()

    # 1. izricito zadrzana prava nadglasavaju openAccess token
    if "all rights reserved" in t or "sva prava pridr" in t:
        return "sva-prava", 0, 0

    # 2. CC oznake: iz URL-a (pouzdanije) i iz proze
    nadeni = set()
    for m in _CC_URL.finditer(tekst):
        nadeni.add(_normkod(m.group(1)))
    for m in _CC_TXT.finditer(tekst):
        nadeni.add(_normkod(m.group(1)))
    if not nadeni and re.search(r"creative\s+commons", t):
        # Puni naziv bez kratice, npr. "Creative Commons
        # Attribution-NonCommercial-NoDerivatives 4.0 International".
        m = _CC_IME.search(tekst)
        if m:
            dijelovi = ["by"]
            if m.group(1):
                dijelovi.append("nc")
            if m.group(2):
                dijelovi.append("nd")
            elif m.group(3):
                dijelovi.append("sa")
            nadeni.add("cc-" + "-".join(dijelovi))
    nadeni = {k for k in nadeni if k in LICENCE}
    if nadeni:
        for kod in CC_PO_STROGOSTI:
            if kod in nadeni:
                return kod, LICENCE[kod][0], int(len(nadeni) > 1)

    # 3. dozvola urednistva (InterEULawEast)
    if re.search(r"permission of the (editor|publisher)|dozvol\w+ ured", t):
        return "dozvola", 0, 0

    # 4. samo osobna / obrazovna uporaba. MORA prethoditi provjeri sirenja:
    #    Pravni vjesnik kaze "may be used and reproduced for personal or
    #    educational purposes", sto bi inace proslo kao dopustenje sirenja.
    if _OSOBNO.search(tekst):
        return "osobno", 0, 0

    # 5. izricito dopustenje daljnjeg sirenja.
    #
    #    Provjera je BLIZINSKA, a ne recenicna, jer Poredbeno pomorsko pravo
    #    dopustenje i zabranu stavlja u istu recenicu: "can be downloaded and
    #    redistributed ... but they cannot be modified". Nijecnica se odnosi na
    #    'modified', ne na 'redistributed'. Zato se gleda samo prozor ISPRED
    #    glagola sirenja: u njemu mora biti rijec dopustenja i ne smije biti
    #    nijecnice. Zbornik PFZ tako ostaje ogranicen, jer uz svoje zabrane
    #    nema nijedan glagol sirenja.
    if _dopusta_sirenje(tekst):
        return "proza-otvorena", 1, 0

    # 6. proza s izricitom zabranom, bez ijednog dopustenja sirenja
    if re.search(r"\b(can\s?not|cannot|may not|must not|nije dopu[sš]|ne smij)\b", t):
        return "proza-ogranicena", 0, 0

    # 7. goli openAccess token ne daje pravo sirenja
    return "nepoznata", 0, 0


def opis_licence(kod: Optional[str]) -> str:
    return LICENCE.get(kod or "nepoznata", (0, kod or "?"))[1]


# Straza klasifikatora. Svi tekstovi su DOSLOVNI dc:rights dohvaceni s Hrcka
# 2026-08-06, ne izmisljeni primjeri. Ocekivane vrijednosti su procitane iz
# samog teksta licence. `doktrina.py provjeri` mora proci 14/14; ako promjena
# regexa nesto obori, vidi se odmah i nad stvarnim, a ne sintetickim ulazom.
PROVJERA: Tuple[Tuple[str, str, int, int, str], ...] = (
    ("journal:18 Zbornik PF Rijeka", "cc-by-nc-nd", 1, 1,
     "info:eu-repo/semantics/openAccess|Collected Papers of the Law Faculty of the "
     "University of Rijeka is an Open Access journal. Papers published before vol. 44/2 "
     "are licensed under CC BY-NC. Papers published from vol. 44/2 onwards are licensed "
     "under CC BY-NC-ND."),
    ("journal:26 Financijska teorija", "nepoznata", 0, 0,
     "info:eu-repo/semantics/openAccess"),
    ("journal:101 Zbornik PFZ", "proza-ogranicena", 0, 0,
     "info:eu-repo/semantics/openAccess|Zbornik Pravnog fakulteta u Zagrebu is an Open "
     "Access journal. All content is made freely available. Users can not use the "
     "materials for commercial purposes. Users can not alter, transform, or build upon "
     "the material."),
    ("journal:127 Pravnik", "sva-prava", 0, 0,
     "info:eu-repo/semantics/openAccess|All rights reserved.  copyright- Law Student "
     "Association \"Pravnik\""),
    ("journal:132 Poredbeno pomorsko", "proza-otvorena", 1, 0,
     "info:eu-repo/semantics/openAccess|The full text materials can be downloaded and "
     "redistributed, paying due regard to attribution by giving appropriate credit to "
     "the authors and the publisher and by providing reference according to the "
     "customary rules of citation, but they cannot be modified, transformed or build upon."),
    ("journal:135 Pravni vjesnik", "osobno", 0, 0,
     "info:eu-repo/semantics/openAccess|Rights and Permissions: full texts may be used "
     "and reproduced for personal or educational purposes respecting all copyrights"),
    ("journal:139 CYELP", "osobno", 0, 0,
     "info:eu-repo/semantics/openAccess|Full text of this journal can be used for "
     "personal or educational purposes."),
    ("journal:197 Zbornik PF Split", "cc-by-nc-nd", 1, 0,
     "info:eu-repo/semantics/openAccess|Papers published in the journal are licensed "
     "under the Creative Commons license BY-NC-ND, which means that their content can be "
     "distributed with attribution for non-commercial purposes without modification."),
    ("journal:211 Kriminologija", "cc-by-nc-nd", 1, 0,
     "info:eu-repo/semantics/openAccess|The author(s) agree that their paper may be used "
     "under a Creative Commons license (BY-NC-ND), so that re-users are allowed to copy "
     "and distribute the material in any medium or format in un-adapted form and for "
     "non-commercial purposes only, as long as credit is given to the author."),
    ("journal:311 Policija i sigurnost", "cc-by", 1, 0,
     "info:eu-repo/semantics/openAccess|Users are allowed to read, download, copy, "
     "redistribute, print, search and link to material, and alter, transform, or build "
     "upon the material, or use them for any other lawful purpose as long as they "
     "attribute the source in an appropriate manner according to the CC BY licence."),
    ("journal:386 InterEULawEast", "dozvola", 0, 0,
     "info:eu-repo/semantics/openAccess|The paper accepted for publication or already "
     "published in INTEREULAWEAST Journal may be published by the author in other "
     "publications only with the permission of the Editorial Board. The full text of "
     "articles published in this journal can be used free of charge for personal and "
     "educational purposes."),
    ("journal:401 Kriminalisticka", "osobno", 0, 0,
     "info:eu-repo/semantics/openAccess|The full-text articles of this Journal may be "
     "used only for personal and educational purposes with respect to copyrights."),
    ("journal:528 Zbornik PF Mostar", "cc-by-nc", 1, 0,
     "info:eu-repo/semantics/openAccess|The Collected Papers of the Faculty of Law, "
     "University of Mostar is an open access journal and is licensed under the Creative "
     "Commons Attributtion – NonCommercial 4.0. license "
     "(https://creativecommons.org/licenses/by-nc/4.0/)"),
    ("journal:605 DOOR", "proza-otvorena", 1, 0,
     "info:eu-repo/semantics/openAccess|DOOR is an open access journal which means that "
     "all content is freely available without charge to the user or his/her institution. "
     "Users are allowed to read, download, copy, distribute, print, search, or link to "
     "the full texts of the articles."),
)


# ================================================================= OAI =======

def _korijen(xml: str) -> ET.Element:
    # encode: ET odbija str s deklaracijom kodiranja u nekim gradnjama
    return ET.fromstring(xml.encode("utf-8"))


def oai(*, svjeze: bool = False, **params) -> ET.Element:
    """Jedan OAI zahtjev. Rate limit, kes i retry dolaze iz common.get."""
    xml = common.get(OAI, params=params, cache=not svjeze, timeout=90)
    korijen = _korijen(xml)
    greska = korijen.find("oai:error", NS)
    if greska is not None:
        raise OaiGreska(greska.get("code") or "?", (greska.text or "").strip())
    return korijen


def stranice(verb: str, *, svjeze: bool = False, **params
             ) -> Iterator[Tuple[ET.Element, Optional[int], int]]:
    """
    Hoda po resumptionToken-ima i daje (korijen, completeListSize, kursor).

    Zahtjev s resumptionTokenom NE smije nositi metadataPrefix ni set - to je
    tvrdo pravilo OAI-PMH 2.0 i Hrcak ga provodi (badArgument).
    """
    p = {"verb": verb}
    p.update({k: v for k, v in params.items() if v})
    ukupno: Optional[int] = None
    kursor = 0
    while True:
        korijen = oai(svjeze=svjeze, **p)

        # Token se cita PRIJE yielda: completeListSize stoji na tokenu tekuce
        # stranice, a pozivatelj cesto prekine hod nakon prve (--max), pa bi
        # citanje nakon yielda ukupan broj ostavilo None.
        tok = korijen.find("oai:%s/oai:resumptionToken" % verb, NS)
        if tok is not None:
            if tok.get("completeListSize"):
                try:
                    ukupno = int(tok.get("completeListSize"))
                except ValueError:
                    pass
            try:
                kursor = int(tok.get("cursor") or kursor)
            except ValueError:
                pass

        yield korijen, ukupno, kursor

        if tok is None or not (tok.text or "").strip():
            return
        p = {"verb": verb, "resumptionToken": tok.text.strip()}


def _tekstovi(el: ET.Element, put: str) -> List[str]:
    return [(x.text or "").strip() for x in el.findall(put, NS) if (x.text or "").strip()]


def _po_jeziku(el: ET.Element, put: str, jezik: str = "hrv") -> Tuple[str, str]:
    """
    Vraca (glavni, sporedni) za visejezicne elemente (dc:title, dc:description).
    Glavni je hrvatski ako postoji, inace prvi.
    """
    parovi = []
    for x in el.findall(put, NS):
        t = (x.text or "").strip()
        if not t:
            continue
        lang = (x.get("{http://www.w3.org/XML/1998/namespace}lang") or "").lower()
        parovi.append((lang, t))
    if not parovi:
        return "", ""
    glavni = next((t for lang, t in parovi if lang.startswith(jezik)), parovi[0][1])
    sporedni = next((t for lang, t in parovi if t != glavni), "")
    return glavni, sporedni


_HRCAK_ID = re.compile(r"hrcak\.srce\.hr/(?:file/)?(\d+)")
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]+)")


def raspakiraj_dc(rec: ET.Element) -> Optional[dict]:
    """Jedan <record> u oai_dc formatu -> rjecnik spreman za upis."""
    hdr = rec.find("oai:header", NS)
    if hdr is None:
        return None
    oai_id = (hdr.findtext("oai:identifier", "", NS) or "").strip()
    if not oai_id or (hdr.get("status") or "").lower() == "deleted":
        return None

    dc = rec.find("oai:metadata/oai_dc:dc", NS)
    if dc is None:
        return None

    naslov, naslov_alt = _po_jeziku(dc, "dc:title")
    sazetak, sazetak_alt = _po_jeziku(dc, "dc:description")
    autori = _tekstovi(dc, "dc:creator")

    # kljucne rijeci: hrvatske prve, pa ostale; bez duplikata
    kljucne, vidjene = [], set()
    for prolaz in ("hrv", ""):
        for x in dc.findall("dc:subject", NS):
            t = (x.text or "").strip()
            lang = (x.get("{http://www.w3.org/XML/1998/namespace}lang") or "").lower()
            if not t or t.lower() in vidjene:
                continue
            if prolaz and not lang.startswith(prolaz):
                continue
            vidjene.add(t.lower())
            kljucne.append(t)

    identifikatori = _tekstovi(dc, "dc:identifier")
    izvori = _tekstovi(dc, "dc:source")
    tipovi = _tekstovi(dc, "dc:type")
    prava = _tekstovi(dc, "dc:rights")

    url = next((i for i in identifikatori if i.startswith("http")), "")
    doi = ""
    for i in identifikatori + _tekstovi(dc, "dc:relation"):
        m = _DOI.search(i)
        if m:
            doi = m.group(1).rstrip(".")
            break

    hrcak_id = None
    m = _HRCAK_ID.search(url or oai_id) or re.search(r":(\d+)$", oai_id)
    if m:
        hrcak_id = int(m.group(1))

    # dc:source nosi i naziv casopisa i ISSN i svezak, sve u istom elementu
    casopis = next((s for s in izvori if not re.match(r"^(ISSN|CODEN|Volume|Issue)", s, re.I)), "")
    volumen = next((re.sub(r"^Volume\s*", "", s, flags=re.I) for s in izvori
                    if re.match(r"^Volume\b", s, re.I)), "")
    svezak = next((re.sub(r"^Issue\s*", "", s, flags=re.I) for s in izvori
                   if re.match(r"^Issue\b", s, re.I)), "")
    issn = "; ".join(s for s in izvori if re.match(r"^ISSN", s, re.I))

    datum = (dc.findtext("dc:date", "", NS) or "").strip()
    m = re.search(r"(1[89]\d{2}|20\d{2})", datum)
    godina = int(m.group(1)) if m else None

    vrsta = next((t.rsplit("/", 1)[-1] for t in tipovi
                  if t.startswith("info:eu-repo/semantics/")
                  and "Version" not in t), "")

    kod, redistr, nejasno = klasificiraj_licencu(prava)

    return {
        "oai_id": oai_id,
        "hrcak_id": hrcak_id,
        "datestamp": (hdr.findtext("oai:datestamp", "", NS) or "").strip(),
        "naslov": naslov,
        "naslov_alt": naslov_alt,
        "autori": json.dumps(autori, ensure_ascii=False),
        "sazetak": sazetak,
        "sazetak_alt": sazetak_alt,
        "kljucne_rijeci": "; ".join(kljucne),
        "casopis": casopis,
        "issn": issn,
        "volumen": volumen,
        "svezak": svezak,
        "jezik": "; ".join(_tekstovi(dc, "dc:language")),
        "vrsta_rada": vrsta,
        "izdavac": dc.findtext("dc:publisher", "", NS) or "",
        "datum": datum,
        "godina": godina,
        "doi": doi,
        "url": url,
        "licenca_kod": kod,
        "licenca_tekst": "\n".join(prava),
        "redistribucija": redistr,
        "licenca_nejasno": nejasno,
    }


def raspakiraj_openaire(rec: ET.Element) -> Tuple[str, str, str]:
    """<record> u oai_openaire -> (oai_id, pdf_url, vrsta_rada). Prazno ako nema."""
    hdr = rec.find("oai:header", NS)
    if hdr is None:
        return "", "", ""
    oai_id = (hdr.findtext("oai:identifier", "", NS) or "").strip()
    res = rec.find("oai:metadata/oaire:resource", NS)
    if res is None:
        return oai_id, "", ""
    pdf = ""
    for f in res.findall("oaire:file", NS):
        if (f.get("objectType") or "").lower() == "fulltext" and (f.text or "").strip():
            pdf = f.text.strip()
            break
    vrsta = (res.findtext("oaire:resourceType", "", NS) or "").strip()
    return oai_id, pdf, vrsta


# ================================================================= PDF =======

def dohvati_pdf(url: str) -> bytes:
    """
    Bajtovi PDF-a, s backoffom. NIKAD ne dodiruje disk i ne ide kroz common.get
    (koji kesira kao tekst i time bi pokvario binarni sadrzaj).

    418 je Hrcakov nacin da kaze "usporio si premalo" i tretira se kao 429.
    """
    zadnja = None
    for pokusaj in range(1, PDF_POKUSAJA + 1):
        try:
            common._throttle(url)
            time.sleep(PDF_PAUZA_S)
            r = common.session.get(url, timeout=120, headers={
                "Accept": "application/pdf,*/*;q=0.8",
                "Referer": "https://hrcak.srce.hr/",
            })
            if r.status_code in (418, 429, 500, 502, 503, 504):
                raise requests.HTTPError("HTTP %d" % r.status_code)
            r.raise_for_status()
            tip = (r.headers.get("Content-Type") or "").lower()
            if "pdf" not in tip and not r.content[:5].startswith(b"%PDF"):
                raise RuntimeError("odgovor nije PDF (Content-Type: %s)" % tip)
            return r.content
        except Exception as e:  # noqa: BLE001
            zadnja = e
            if pokusaj < PDF_POKUSAJA:
                pauza = (2 ** pokusaj) + random.uniform(0, 1.5)
                log("      [pdf retry %d/%d] %s - cekam %.1fs"
                    % (pokusaj, PDF_POKUSAJA - 1, e, pauza))
                time.sleep(pauza)
    raise RuntimeError("PDF nije dohvacen: %s - %s" % (url, zadnja))


# Neki stariji Hrcakovi PDF-ovi imaju ugradenu podskupinu fonta BEZ ToUnicode
# CMap-a, pa pypdf umjesto znakova vraca imena glifova: "/g51/g53/g40/g42..."
# Izmjereno 2026-08-06 na Policiji i sigurnosti (godiste 2011): 6 od 6 PDF-ova
# tako izlazi, oko 124 % duljine teksta otpada na /gNN tokene, a udio slova je
# 26 % umjesto uobicajenih 75-79 %. Isti casopis od 2024. i Zbornici PF Split,
# Rijeka te HKJU od 2022-23 izlaze ispravno, s ocuvanim dijakriticima.
#
# Takav se tekst NE SPREMA i NE POKUSAVA rekonstruirati. Preslikavanje glifa u
# znak jest izvedivo za ASCII (izmjereno: kod = indeks + 29), ali za hrvatske
# dijakritike glifovi su izvan tog raspona i specificni za podskupinu fonta;
# pogodeno preslikavanje dalo bi "sluzbenike" kao "slulbenike", dakle tiho
# pokvaren korpus. Bolje je zapis posteno oznaciti i prepustiti ga OCR-u.
_GLIF = re.compile(r"/g\d+")

STATUS_OK = "ok"
STATUS_SKEN = "sken"            # PDF bez tekstualnog sloja, treba OCR
STATUS_BEZ_UNICODE = "bez-unicode"   # font bez ToUnicode, izlaze /gNN
STATUS_PRAZNO = "prazno"        # pypdf nije vratio nista upotrebljivo


def ocijeni_tekst(tekst: str, n_str: int) -> str:
    """Strojno citljiva ocjena izvucenog teksta. Vidi komentar iznad."""
    if n_str <= 0 or not tekst.strip():
        return STATUS_PRAZNO
    if len(_GLIF.findall(tekst)) * 4 > len(tekst) * 0.30:
        return STATUS_BEZ_UNICODE
    if len(tekst) / n_str < PRAG_SKENA:
        return STATUS_SKEN
    return STATUS_OK


def izvuci_tekst(bajtovi: bytes) -> Tuple[str, int, str]:
    """
    PDF bajtovi -> (tekst, broj_stranica, status).

    `status` je jedan od STATUS_*. Tekst se vraca i kad status nije 'ok', da ga
    pozivatelj moze pregledati, ali `spremi_tekst` sprema samo 'ok'.

    Bajtovi zive samo u BytesIO i oslobadaju se prije povratka. Na disk ne idu.
    """
    from pypdf import PdfReader

    spremnik = io.BytesIO(bajtovi)
    try:
        citac = PdfReader(spremnik)
        if getattr(citac, "is_encrypted", False):
            try:
                citac.decrypt("")
            except Exception:  # noqa: BLE001
                return "", 0, STATUS_PRAZNO
        dijelovi = []
        for stranica in citac.pages:
            try:
                dijelovi.append(stranica.extract_text() or "")
            except Exception:  # noqa: BLE001
                dijelovi.append("")
        n_str = len(citac.pages)
    finally:
        spremnik.close()

    tekst = re.sub(r"[ \t]+", " ", "\n".join(dijelovi))
    tekst = re.sub(r"\n{3,}", "\n\n", tekst).strip()
    return tekst, n_str, ocijeni_tekst(tekst, n_str)


# =============================================================== POHRANA =====

SHEMA = """
CREATE TABLE IF NOT EXISTS casopisi (
    set_spec        TEXT PRIMARY KEY,
    naziv           TEXT,
    opis            TEXT,
    ukupno          INTEGER,       -- completeListSize iz resumptionTokena
    licenca_kod     TEXT,
    licenca_tekst   TEXT,
    redistribucija  INTEGER DEFAULT 0,
    licenca_nejasno INTEGER DEFAULT 0,
    osvjezeno       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS clanci (
    rid             INTEGER PRIMARY KEY,
    oai_id          TEXT NOT NULL UNIQUE,
    hrcak_id        INTEGER,
    set_spec        TEXT,
    casopis         TEXT,
    issn            TEXT,
    izdavac         TEXT,
    naslov          TEXT,
    naslov_alt      TEXT,          -- prijevod naslova
    autori          TEXT,          -- JSON lista "Prezime, Ime"
    sazetak         TEXT,
    sazetak_alt     TEXT,
    kljucne_rijeci  TEXT,          -- '; ' spojeno, hrvatske prve
    jezik           TEXT,
    vrsta_rada      TEXT,
    godina          INTEGER,
    datum           TEXT,
    volumen         TEXT,
    svezak          TEXT,
    doi             TEXT,
    url             TEXT,          -- landing stranica na Hrcku
    pdf_url         TEXT,          -- iz oai_openaire; PDF se NE pohranjuje
    licenca_kod     TEXT,
    licenca_tekst   TEXT,
    licenca_razina  TEXT DEFAULT 'casopis',  -- vidi docstring modula
    licenca_nejasno INTEGER DEFAULT 0,
    redistribucija  INTEGER DEFAULT 0,
    samo_lokalno    INTEGER DEFAULT 0,       -- dohvaceno pod --osobno
    ima_tekst       INTEGER DEFAULT 0,       -- 1 samo ako je tekst upotrebljiv
    tekst_status    TEXT,                    -- ok | sken | bez-unicode | prazno
    sken            INTEGER DEFAULT 0,       -- 1 kad je tekst_status='sken'
    n_stranica      INTEGER,
    n_znakova       INTEGER,
    sha256          BLOB,
    datestamp       TEXT,
    dohvaceno       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tekstovi (
    rid     INTEGER PRIMARY KEY REFERENCES clanci(rid) ON DELETE CASCADE,
    komp    INTEGER NOT NULL DEFAULT 6,
    n_bajt  INTEGER,
    tijelo  BLOB NOT NULL
);

-- Stanje inkrementalnog dohvata po setu i formatu. `zadnji_datestamp` je
-- najveci vidjeni OAI datestamp; sljedeci harvest krece od njega.
CREATE TABLE IF NOT EXISTS harvest (
    set_spec         TEXT,
    format           TEXT,
    zadnji_datestamp TEXT,
    zapisa           INTEGER DEFAULT 0,
    zadnji_run       TEXT,
    PRIMARY KEY (set_spec, format)
);

CREATE INDEX IF NOT EXISTS ix_clanci_set     ON clanci(set_spec, godina);
CREATE INDEX IF NOT EXISTS ix_clanci_godina  ON clanci(godina);
CREATE INDEX IF NOT EXISTS ix_clanci_lic     ON clanci(licenca_kod, redistribucija);
CREATE INDEX IF NOT EXISTS ix_clanci_tekst   ON clanci(ima_tekst, sken);
CREATE INDEX IF NOT EXISTS ix_clanci_ds      ON clanci(datestamp);
"""

# Isti obrazac kao u store.py: pogled sa SKALARNIM podupitom, ne JOIN-om,
# da ga SQLite moze spljostiti umjesto materijalizirati.
POGLED = """
CREATE VIEW v_clanci AS
SELECT c.rid AS rid,
       COALESCE(c.naslov, '') || ' ' || COALESCE(c.naslov_alt, '') AS naslov,
       COALESCE(c.autori, '') AS autori,
       COALESCE(c.kljucne_rijeci, '') AS kljucne,
       COALESCE(c.sazetak, '') || ' ' || COALESCE(c.sazetak_alt, '') AS sazetak,
       COALESCE((SELECT CASE WHEN t.komp = 0 THEN CAST(t.tijelo AS TEXT)
                             ELSE odzipaj(t.tijelo) END
                   FROM tekstovi t WHERE t.rid = c.rid), '') AS tekst
FROM clanci c
"""

FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS clanci_fts USING fts5(
    naslov, autori, kljucne, sazetak, tekst,
    content='v_clanci', content_rowid='rid',
    tokenize='unicode61 remove_diacritics 2'
);
"""

FTS_STUPCI = ("naslov", "autori", "kljucne", "sazetak", "tekst")


def veza(path=None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or DB_PATH))
    con.row_factory = sqlite3.Row
    con.create_function("odzipaj", 1, odzipaj, deterministic=True)
    for pragma, v in (("journal_mode", "WAL"), ("synchronous", "NORMAL"),
                      ("temp_store", "MEMORY"), ("foreign_keys", "ON")):
        con.execute("PRAGMA %s=%s" % (pragma, v))
    con.executescript(SHEMA)

    # Blaga migracija: CREATE TABLE IF NOT EXISTS ne dodaje stupce u postojecu
    # tablicu, pa se novi stupci dodaju rucno. Bez ovoga bi baza napravljena
    # ranijom inacicom pucala na tekst_status.
    postojeci = {r[1] for r in con.execute("PRAGMA table_info(clanci)")}
    for stupac, tip in (("tekst_status", "TEXT"),):
        if stupac not in postojeci:
            con.execute("ALTER TABLE clanci ADD COLUMN %s %s" % (stupac, tip))

    ima = con.execute("SELECT sql FROM sqlite_master WHERE name='v_clanci'").fetchone()
    if ima is None or (ima[0] or "").strip() != POGLED.strip():
        con.execute("DROP VIEW IF EXISTS v_clanci")
        con.execute(POGLED)
    con.executescript(FTS)
    con.commit()
    return con


def _fts_makni(con: sqlite3.Connection, rid: int) -> None:
    """FTS s vanjskim sadrzajem pri brisanju trazi STARE vrijednosti."""
    r = con.execute("SELECT %s FROM v_clanci WHERE rid=?" % ", ".join(FTS_STUPCI),
                    (rid,)).fetchone()
    if r is None:
        return
    con.execute("INSERT INTO clanci_fts (clanci_fts, rowid, %s) VALUES ('delete',?,?,?,?,?,?)"
                % ", ".join(FTS_STUPCI), (rid,) + tuple(r))


def _fts_dodaj(con: sqlite3.Connection, rid: int) -> None:
    r = con.execute("SELECT %s FROM v_clanci WHERE rid=?" % ", ".join(FTS_STUPCI),
                    (rid,)).fetchone()
    if r is not None:
        con.execute("INSERT INTO clanci_fts (rowid, %s) VALUES (?,?,?,?,?,?)"
                    % ", ".join(FTS_STUPCI), (rid,) + tuple(r))


META_STUPCI = ("hrcak_id", "set_spec", "casopis", "issn", "izdavac", "naslov",
               "naslov_alt", "autori", "sazetak", "sazetak_alt", "kljucne_rijeci",
               "jezik", "vrsta_rada", "godina", "datum", "volumen", "svezak",
               "doi", "url", "licenca_kod", "licenca_tekst", "licenca_nejasno",
               "redistribucija", "datestamp")


def spremi(con: sqlite3.Connection, rec: dict, *, set_spec: str) -> bool:
    """Upsert metapodataka clanka. Vraca True ako je zapis nov. Tekst ne dira."""
    rec = dict(rec)
    rec["set_spec"] = set_spec
    stari = con.execute("SELECT rid FROM clanci WHERE oai_id=?", (rec["oai_id"],)).fetchone()
    vrijednosti = [rec.get(k) for k in META_STUPCI]

    if stari is None:
        cur = con.execute(
            "INSERT INTO clanci (oai_id, %s) VALUES (%s)"
            % (", ".join(META_STUPCI), ",".join("?" * (len(META_STUPCI) + 1))),
            [rec["oai_id"]] + vrijednosti)
        _fts_dodaj(con, cur.lastrowid)
        return True

    rid = stari["rid"]
    _fts_makni(con, rid)
    con.execute("UPDATE clanci SET %s, dohvaceno=datetime('now') WHERE rid=?"
                % ", ".join("%s=?" % k for k in META_STUPCI), vrijednosti + [rid])
    _fts_dodaj(con, rid)
    return False


def spremi_tekst(con: sqlite3.Connection, rid: int, tekst: str,
                 *, n_stranica: int, status: str) -> None:
    """
    Upisuje izvuceni tekst (zlib-6). PDF u ovom trenutku vise ne postoji.

    U `tekstovi` ide SAMO tekst sa statusom 'ok'. Neupotrebljiv izlaz (sken bez
    OCR-a, font bez ToUnicode) ostavlja trag u metapodacima - broj stranica i
    status - ali ne ulazi ni u bazu ni u FTS, da ne truje pretragu.
    """
    _fts_makni(con, rid)
    upotrebljiv = status == STATUS_OK
    if upotrebljiv:
        komp, n_bajt, blob = zipaj(tekst)
        con.execute("INSERT INTO tekstovi (rid, komp, n_bajt, tijelo) VALUES (?,?,?,?) "
                    "ON CONFLICT(rid) DO UPDATE SET komp=excluded.komp, "
                    "n_bajt=excluded.n_bajt, tijelo=excluded.tijelo",
                    (rid, komp, n_bajt, blob))
    else:
        con.execute("DELETE FROM tekstovi WHERE rid=?", (rid,))
    con.execute("UPDATE clanci SET ima_tekst=?, tekst_status=?, sken=?, n_stranica=?, "
                "n_znakova=?, sha256=? WHERE rid=?",
                (int(upotrebljiv), status, int(status == STATUS_SKEN), n_stranica,
                 len(tekst) if upotrebljiv else 0,
                 hashlib.sha256(tekst.encode("utf-8")).digest() if upotrebljiv else None,
                 rid))
    _fts_dodaj(con, rid)


# =============================================================== SETOVI ======

PRAVNI_UZORAK = re.compile(
    r"pravn|pravo|kriminol|kriminal|javna uprava|odvjetni|bilje[zž]nik|"
    r"kazneno|kaznen[ei]|ljetopis za kazn|law|legal|jurisprud|policij|"
    r"financije i pravo|zagreba[cč]ka pravna", re.I)


def ucitaj_setove(con: sqlite3.Connection, *, svjeze: bool = False) -> int:
    """ListSets -> tablica casopisi. Vraca broj setova."""
    n = 0
    for korijen, _, _ in stranice("ListSets", svjeze=svjeze):
        for s in korijen.findall("oai:ListSets/oai:set", NS):
            spec = (s.findtext("oai:setSpec", "", NS) or "").strip()
            naziv = (s.findtext("oai:setName", "", NS) or "").strip()
            opis = " ".join(_tekstovi(s, "oai:setDescription/oai_dc:dc/dc:description"))
            if not spec:
                continue
            con.execute(
                "INSERT INTO casopisi (set_spec, naziv, opis) VALUES (?,?,?) "
                "ON CONFLICT(set_spec) DO UPDATE SET naziv=excluded.naziv, "
                "opis=excluded.opis, osvjezeno=datetime('now')",
                (spec, naziv, opis))
            n += 1
    con.commit()
    return n


# ============================================================== HARVEST ======

def _od_kada(con: sqlite3.Connection, set_spec: str, fmt: str,
             od: Optional[str], puno: bool) -> Optional[str]:
    """Odreduje `from=`: izricit argument > zapamceni datestamp > nista."""
    if puno:
        return None
    if od:
        return od
    r = con.execute("SELECT zadnji_datestamp FROM harvest WHERE set_spec=? AND format=?",
                    (set_spec, fmt)).fetchone()
    return r["zadnji_datestamp"] if r and r["zadnji_datestamp"] else None


def _zapamti(con: sqlite3.Connection, set_spec: str, fmt: str,
             najveci: Optional[str], n: int) -> None:
    con.execute(
        "INSERT INTO harvest (set_spec, format, zadnji_datestamp, zapisa, zadnji_run) "
        "VALUES (?,?,?,?,datetime('now')) "
        "ON CONFLICT(set_spec, format) DO UPDATE SET "
        "zadnji_datestamp=MAX(COALESCE(harvest.zadnji_datestamp,''), COALESCE(excluded.zadnji_datestamp,'')), "
        "zapisa=harvest.zapisa+excluded.zapisa, zadnji_run=excluded.zadnji_run",
        (set_spec, fmt, najveci, n))


def harvest(con: sqlite3.Connection, set_spec: str, *, najvise: Optional[int] = None,
            od: Optional[str] = None, puno: bool = False, svjeze: bool = False,
            tekst: bool = False, osobno: bool = False, ponovi: bool = False) -> dict:
    """
    Dohvat jednog seta. Vraca statistiku prolaza.

    Prolaz 1: oai_dc  -> metapodaci + licenca
    Prolaz 2: oai_openaire -> pdf_url za zapise iz prolaza 1
    Prolaz 3 (--tekst): PDF -> tekst, samo gdje licenca to dopusta
    """
    st = {"set": set_spec, "novih": 0, "azuriranih": 0, "ukupno_u_setu": None,
          "s_pdf_linkom": 0, "tekstova": 0, "neupotrebljivih": 0,
          "preskoceno_licenca": 0, "neuspjelih_pdf": 0}

    # ---------------------------------------------------------- prolaz 1 ---
    poc = _od_kada(con, set_spec, "oai_dc", od, puno)
    log("[1/3] oai_dc  set=%s%s" % (set_spec, ("  from=%s" % poc) if poc else ""))
    vidjeni: List[Tuple[int, dict]] = []
    najveci_ds = ""
    n = 0
    try:
        for korijen, ukupno, _ in stranice("ListRecords", svjeze=svjeze,
                                           metadataPrefix="oai_dc",
                                           set=set_spec, **{"from": poc}):
            if ukupno is not None:
                st["ukupno_u_setu"] = ukupno
            for r in korijen.findall("oai:ListRecords/oai:record", NS):
                rec = raspakiraj_dc(r)
                if rec is None:
                    continue
                nov = spremi(con, rec, set_spec=set_spec)
                st["novih" if nov else "azuriranih"] += 1
                najveci_ds = max(najveci_ds, rec.get("datestamp") or "")
                rid = con.execute("SELECT rid FROM clanci WHERE oai_id=?",
                                  (rec["oai_id"],)).fetchone()["rid"]
                vidjeni.append((rid, rec))
                n += 1
                if najvise and n >= najvise:
                    break
            con.commit()
            common.progress(n, ukupno or n, "zapisa ")
            if najvise and n >= najvise:
                break
    except OaiGreska as e:
        if e.kod != "noRecordsMatch":
            raise
        log("  nema novih zapisa (noRecordsMatch)")
    _zapamti(con, set_spec, "oai_dc", najveci_ds or None, n)
    if st["ukupno_u_setu"]:
        con.execute("UPDATE casopisi SET ukupno=? WHERE set_spec=?",
                    (st["ukupno_u_setu"], set_spec))
    if vidjeni:
        prvi = vidjeni[0][1]
        con.execute("UPDATE casopisi SET licenca_kod=?, licenca_tekst=?, "
                    "redistribucija=?, licenca_nejasno=? WHERE set_spec=?",
                    (prvi["licenca_kod"], prvi["licenca_tekst"], prvi["redistribucija"],
                     prvi["licenca_nejasno"], set_spec))
    con.commit()

    # ---------------------------------------------------------- prolaz 2 ---
    # Trazimo pdf_url samo za zapise koje smo upravo vidjeli. Hod prestaje cim
    # su svi razrijeseni, pa --max ne povlaci hodanje cijelim setom.
    if vidjeni:
        trazeni = {rec["oai_id"] for _, rec in vidjeni}
        log("\n[2/3] oai_openaire  (pdf poveznice za %d zapisa)" % len(trazeni))
        try:
            for korijen, _, _ in stranice("ListRecords", svjeze=svjeze,
                                          metadataPrefix="oai_openaire",
                                          set=set_spec, **{"from": poc}):
                for r in korijen.findall("oai:ListRecords/oai:record", NS):
                    oid, pdf, vrsta = raspakiraj_openaire(r)
                    if oid not in trazeni:
                        continue
                    trazeni.discard(oid)
                    if pdf:
                        con.execute("UPDATE clanci SET pdf_url=? WHERE oai_id=?", (pdf, oid))
                        st["s_pdf_linkom"] += 1
                    if vrsta:
                        con.execute("UPDATE clanci SET vrsta_rada="
                                    "COALESCE(NULLIF(?,''), vrsta_rada) WHERE oai_id=?",
                                    (vrsta, oid))
                con.commit()
                if not trazeni:
                    break
        except OaiGreska as e:
            if e.kod != "noRecordsMatch":
                raise
        log("  pdf poveznica: %d/%d" % (st["s_pdf_linkom"], len(vidjeni)))

    # ---------------------------------------------------------- prolaz 3 ---
    # NAMJERNO gleda cijeli set, a ne samo zapise iz ovog prolaza: inkrementalni
    # harvest drugi put ne vraca nista (from= je pomaknut), pa bi vezanje uz
    # `vidjeni` znacilo da se `--tekst` nakon golog harvesta nikad ne izvrsi.
    # Ovako je dohvat teksta nastavljiv: uzima zaostatak, komad po komad.
    if not tekst:
        return st

    # `tekst_status IS NULL` znaci "jos nije pokusano". Zapis koji je zavrsio
    # kao 'sken' ili 'bez-unicode' se NE ponavlja u nedogled - ponovni pokusaj
    # trazi --ponovi, jer ishod ovisi o PDF-u, ne o mrezi.
    uvjet_status = "tekst_status IS NULL" if not ponovi else "ima_tekst=0"
    redci = con.execute(
        "SELECT rid, oai_id, pdf_url, licenca_kod, redistribucija FROM clanci "
        "WHERE set_spec=? AND pdf_url IS NOT NULL AND pdf_url<>'' AND " + uvjet_status +
        "  AND (? OR redistribucija=1) "
        "ORDER BY godina DESC, rid LIMIT ?",
        (set_spec, 1 if osobno else 0, najvise or -1)).fetchall()
    st["preskoceno_licenca"] = 0 if osobno else con.execute(
        "SELECT COUNT(*) FROM clanci WHERE set_spec=? AND pdf_url IS NOT NULL "
        "AND pdf_url<>'' AND " + uvjet_status + " AND redistribucija=0",
        (set_spec,)).fetchone()[0]
    log("\n[3/3] puni tekst  (%d kandidata, %d preskoceno zbog licence)"
        % (len(redci), st["preskoceno_licenca"]))

    for i, r in enumerate(redci, 1):
        try:
            bajtovi = dohvati_pdf(r["pdf_url"])
        except Exception as e:  # noqa: BLE001
            st["neuspjelih_pdf"] += 1
            log("  [%d/%d] PDF neuspjeh %s: %s" % (i, len(redci), r["oai_id"], e))
            continue
        try:
            t, n_str, status = izvuci_tekst(bajtovi)
        except Exception as e:  # noqa: BLE001
            st["neuspjelih_pdf"] += 1
            log("  [%d/%d] pypdf neuspjeh %s: %s" % (i, len(redci), r["oai_id"], e))
            continue
        finally:
            # PDF prestaje postojati ovdje. Na disk nije ni dosao.
            del bajtovi

        spremi_tekst(con, r["rid"], t, n_stranica=n_str, status=status)
        if not r["redistribucija"]:
            con.execute("UPDATE clanci SET samo_lokalno=1 WHERE rid=?", (r["rid"],))
        con.commit()
        st.setdefault("status_" + status, 0)
        st["status_" + status] += 1
        if status == STATUS_OK:
            st["tekstova"] += 1
        else:
            st["neupotrebljivih"] += 1
        log("  [%d/%d] %s  %d str, %d znak  [%s]"
            % (i, len(redci), r["oai_id"], n_str, len(t), status))
    return st


# =================================================================== CLI =====

def cmd_setovi(a) -> int:
    con = veza(a.baza)
    if a.osvjezi or con.execute("SELECT COUNT(*) FROM casopisi").fetchone()[0] == 0:
        log("ListSets ...")
        log("ucitano setova: %d" % ucitaj_setove(con, svjeze=a.osvjezi))
    upit = "SELECT set_spec, naziv, ukupno, licenca_kod, redistribucija FROM casopisi"
    redci = con.execute(upit + " ORDER BY CAST(SUBSTR(set_spec,9) AS INTEGER)").fetchall()
    if a.pravni:
        redci = [r for r in redci if PRAVNI_UZORAK.search(r["naziv"] or "")]
    for r in redci:
        lic = r["licenca_kod"] or "-"
        znak = {1: "R", 0: "L"}.get(r["redistribucija"], "?") if r["licenca_kod"] else " "
        print("%-14s %s %-16s %6s  %s" % (
            r["set_spec"], znak, lic, r["ukupno"] if r["ukupno"] else "", r["naziv"]))
    print("\nukupno setova: %d%s" % (len(redci), "  (filtar: pravni)" if a.pravni else ""))
    print("R = licenca dopusta redistribuciju, L = samo lokalno, prazno = jos nedohvaceno")
    return 0


def cmd_harvest(a) -> int:
    con = veza(a.baza)
    if con.execute("SELECT COUNT(*) FROM casopisi").fetchone()[0] == 0:
        ucitaj_setove(con)
    st = harvest(con, a.set, najvise=a.max, od=a.od, puno=a.puno, svjeze=a.svjeze,
                 tekst=a.tekst, osobno=a.osobno, ponovi=a.ponovi)
    print("\n--- %s ---" % st["set"])
    for k in ("ukupno_u_setu", "novih", "azuriranih", "s_pdf_linkom", "tekstova",
              "neupotrebljivih", "preskoceno_licenca", "neuspjelih_pdf"):
        print("  %-20s %s" % (k, st[k]))
    for k in sorted(x for x in st if x.startswith("status_")):
        print("    %-18s %s" % (k[7:], st[k]))
    r = con.execute("SELECT licenca_kod, licenca_nejasno, redistribucija FROM casopisi "
                    "WHERE set_spec=?", (a.set,)).fetchone()
    if r and r["licenca_kod"]:
        print("  licenca (razina casopisa): %s - %s%s"
              % (r["licenca_kod"], opis_licence(r["licenca_kod"]),
                 ", VISE CC OZNAKA U TEKSTU, uzeta najstroza" if r["licenca_nejasno"] else ""))
        if not r["redistribucija"] and not a.osobno:
            print("  puni tekst nije dohvacan: licenca ne dopusta redistribuciju")
    return 0


def cmd_stat(a) -> int:
    con = veza(a.baza)
    uvjet, arg = ("WHERE set_spec=?", (a.set,)) if a.set else ("", ())
    r = con.execute("""
        SELECT COUNT(*) n,
               SUM(ima_tekst) s_tekstom,
               SUM(sken) skenova,
               SUM(pdf_url IS NOT NULL AND pdf_url<>'') s_pdf,
               SUM(samo_lokalno) lokalnih,
               SUM(sazetak IS NOT NULL AND sazetak<>'') sa_sazetkom,
               SUM(kljucne_rijeci IS NOT NULL AND kljucne_rijeci<>'') s_kljucnima,
               SUM(doi IS NOT NULL AND doi<>'') s_doi,
               MIN(godina) od_g, MAX(godina) do_g,
               COUNT(DISTINCT set_spec) setova
        FROM clanci """ + uvjet, arg).fetchone()
    n = r["n"] or 0
    print("baza: %s" % (a.baza or DB_PATH))
    if n == 0:
        print("clanaka: 0 (jos nije bilo harvesta)")
        return 0
    # Velicina se mora filtrirati istim uvjetom kao i broj clanaka, inace bi
    # `stat --set X` prijavio MB cijele baze uz broj clanaka jednog seta.
    b = con.execute("SELECT SUM(t.n_bajt) FROM tekstovi t JOIN clanci c ON c.rid=t.rid "
                    + uvjet.replace("WHERE set_spec", "WHERE c.set_spec"), arg).fetchone()[0] or 0

    def pct(x):
        return "%5d (%4.1f%%)" % (x or 0, 100.0 * (x or 0) / n)

    print("clanaka:            %d  u %d %s, godine %s-%s"
          % (n, r["setova"], "setova" if r["setova"] != 1 else "set", r["od_g"], r["do_g"]))
    print("  sa sazetkom:      %s" % pct(r["sa_sazetkom"]))
    print("  s kljucnima:      %s" % pct(r["s_kljucnima"]))
    print("  s DOI:            %s" % pct(r["s_doi"]))
    print("  s PDF poveznicom: %s" % pct(r["s_pdf"]))
    print("  s punim tekstom:  %s" % pct(r["s_tekstom"]))
    print("  samo lokalno:     %s" % pct(r["lokalnih"]))
    print("  teksta na disku:  %.1f MB nekomprimirano" % (b / 1048576.0))

    print("\nishod izvlacenja iz PDF-a:")
    for x in con.execute("SELECT COALESCE(tekst_status,'(nije pokusano)') s, COUNT(*) n "
                         "FROM clanci " + uvjet + " GROUP BY s ORDER BY n DESC", arg):
        opis = {STATUS_OK: "upotrebljiv tekst",
                STATUS_SKEN: "sken bez OCR-a, tekstualni sloj ne postoji",
                STATUS_BEZ_UNICODE: "font bez ToUnicode, pypdf vraca /gNN glifove",
                STATUS_PRAZNO: "pypdf nije vratio nista"}.get(x["s"], "")
        print("  %-16s %6d  %s" % (x["s"], x["n"], opis))

    print("\nlicence (razina casopisa, ne clanka):")
    for x in con.execute("SELECT licenca_kod k, redistribucija r, "
                         "MAX(licenca_nejasno) nj, COUNT(*) n FROM clanci " + uvjet +
                         " GROUP BY k, r ORDER BY n DESC", arg):
        print("  %-18s %6d  %s%s" % (x["k"] or "?", x["n"],
                                     "redistribucija DOPUSTENA" if x["r"] else "samo lokalno",
                                     "  (nejasno)" if x["nj"] else ""))
    print("\nnajveci setovi:")
    for x in con.execute("SELECT set_spec s, casopis c, COUNT(*) n, SUM(ima_tekst) t "
                         "FROM clanci " + uvjet +
                         " GROUP BY s ORDER BY n DESC LIMIT 15", arg):
        print("  %-14s %5d clanaka, %4d s tekstom  %s"
              % (x["s"], x["n"], x["t"] or 0, (x["c"] or "")[:45]))
    return 0


def cmd_trazi(a) -> int:
    con = veza(a.baza)
    redci = con.execute(
        "SELECT c.oai_id, c.naslov, c.casopis, c.godina, c.url, c.licenca_kod, "
        "       c.ima_tekst, bm25(clanci_fts) b "
        "FROM clanci_fts JOIN clanci c ON c.rid = clanci_fts.rowid "
        "WHERE clanci_fts MATCH ? ORDER BY b LIMIT ?", (a.upit, a.k)).fetchall()
    if not redci:
        print("nema pogodaka za: %s" % a.upit)
        return 1
    for i, r in enumerate(redci, 1):
        print("%2d. %s (%s, %s)" % (i, r["naslov"], r["casopis"] or "?", r["godina"] or "?"))
        print("    %s  licenca=%s  tekst=%s"
              % (r["url"] or r["oai_id"], r["licenca_kod"], "da" if r["ima_tekst"] else "ne"))
    return 0


# ============================================== PRELIJEVANJE U KORPUS ======
#
# Do ovdje doktrina zivi u vlastitoj bazi, jer harvest ima svoj ritam i svoje
# stanje (resumption tokeni, datestampovi po setu). Pretraga ih mora vidjeti
# zajedno, pa se gotovi clanci prelijevaju u glavni korpus kao gradivo
# 'doktrina'. Shema 3 u store.py za to vec ima stupce; ovdje je samo preslik.
#
# U korpus ide SAMO clanak s upotrebljivim tekstom (ima_tekst=1). Zapis bez
# teksta ostaje u doktrina.sqlite kao bibliografski trag; u korpusu bi bio
# prazna ljuska koja kvari statistiku i ne moze se cankirati.

def _citaj_tekst(con: sqlite3.Connection, rid: int) -> str:
    """Tekst clanka iz lokalne baze. `odzipaj` podnosi i zipan i sirov zapis."""
    r = con.execute("SELECT tijelo FROM tekstovi WHERE rid=?", (rid,)).fetchone()
    return (odzipaj(r["tijelo"]) or "") if r else ""


def u_korpus(con: sqlite3.Connection, korpus, *, samo_slobodne: bool = False,
             najvise: Optional[int] = None) -> dict:
    """
    Prelijeva clanke s tekstom iz doktrina.sqlite u glavni korpus.

    `samo_slobodne` propusta samo ono sto se smije redistribuirati. Zadano je
    False jer je korpus lokalan, a store.py uz svaki zapis pamti licencu i
    izvedenu ocjenu redistribucije, pa se ogranicenje vidi na zapisu.
    """
    import store

    st = {"preneseno": 0, "novih": 0, "preskoceno_bez_teksta": 0,
          "preskoceno_licenca": 0, "bez_licence": 0}
    sql = ("SELECT * FROM clanci WHERE ima_tekst = 1 "
           "ORDER BY casopis, godina, rid")
    redci = con.execute(sql).fetchall()

    for r in redci:
        if najvise and st["preneseno"] >= najvise:
            break
        tekst = _citaj_tekst(con, r["rid"])
        if not tekst.strip():
            st["preskoceno_bez_teksta"] += 1
            continue

        licenca = (r["licenca_tekst"] or "").strip() or (r["licenca_kod"] or "").strip()
        if not licenca:
            # store.spremi bi ovdje dignuo ValueError, i s pravom
            st["bez_licence"] += 1
            continue
        red = store.procijeni_redistribuciju(licenca)
        if samo_slobodne and red != "slobodna":
            st["preskoceno_licenca"] += 1
            continue

        try:
            autori = "; ".join(json.loads(r["autori"] or "[]"))
        except (ValueError, TypeError):
            autori = r["autori"] or ""

        def _bez_tocke(v) -> str:
            return str(v).strip().rstrip(".").strip()

        citat = ", ".join(x for x in (
            ("Vol. %s" % _bez_tocke(r["volumen"])) if r["volumen"] else "",
            ("br. %s" % _bez_tocke(r["svezak"])) if r["svezak"] else "",
            str(r["godina"]) if r["godina"] else "") if x)

        rec = {
            "id": "hrcak:%s" % (r["hrcak_id"] or r["oai_id"]),
            "izvor": "hrcak",
            "gradivo": "doktrina",
            "url": r["url"] or r["oai_id"],
            "naslov": r["naslov"],
            "autori": autori,
            "casopis": r["casopis"],
            "citat": citat or None,
            "doi": r["doi"],
            "licenca": licenca,
            # licenca_url ostaje prazan kad ga izvor ne daje. Hrcak u dc:rights
            # salje prozu, ne poveznicu, pa bi upisivanje kratkog koda
            # ("cc-by-nc-nd") u polje koje se zove URL bilo krivo predstavljanje;
            # kod ionako stoji u meta.licenca_kod.
            "licenca_url": None,
            "redistribucija": red,
            "vrsta": r["vrsta_rada"],
            "kazalo": r["kljucne_rijeci"],
            "datum": r["datum"],
            "godina": r["godina"],
            "sazetak": r["sazetak"] or "",
            "tekst": tekst,
            "meta": {
                "oai_id": r["oai_id"], "set_spec": r["set_spec"],
                "issn": r["issn"], "izdavac": r["izdavac"], "jezik": r["jezik"],
                "volumen": r["volumen"], "svezak": r["svezak"],
                "pdf_url": r["pdf_url"], "n_stranica": r["n_stranica"],
                "licenca_kod": r["licenca_kod"],
                "licenca_razina": r["licenca_razina"],
                "licenca_nejasno": r["licenca_nejasno"],
                "samo_lokalno": r["samo_lokalno"],
                "naslov_alt": r["naslov_alt"],
            },
        }
        nov = store.spremi(korpus, rec, commit=False)
        st["preneseno"] += 1
        st["novih"] += int(nov)
        if st["preneseno"] % 50 == 0:
            korpus.commit()
    korpus.commit()
    return st


def cmd_ulij(a) -> int:
    import store

    con = veza(a.baza)
    korpus = store.veza(a.korpus)
    st = u_korpus(con, korpus, samo_slobodne=a.samo_slobodne, najvise=a.max)
    print("\n--- prelijevanje u korpus ---")
    for k, v in st.items():
        print("  %-24s %s" % (k, v))
    n = korpus.execute(
        "SELECT COUNT(*) FROM odluke_meta WHERE gradivo='doktrina'").fetchone()[0]
    print("  %-24s %s" % ("doktrine u korpusu", n))
    return 0


def cmd_provjeri(a) -> int:
    """Straza klasifikatora licenci nad doslovnim dc:rights tekstovima."""
    lose = 0
    for ime, ok_kod, ok_r, ok_nj, txt in PROVJERA:
        kod, r, nj = klasificiraj_licencu(txt.split("|"))
        dobro = (kod, r, nj) == (ok_kod, ok_r, ok_nj)
        lose += int(not dobro)
        print("%-5s %-32s %-17s red=%d nej=%d%s"
              % ("OK" if dobro else "LOSE", ime, kod, r, nj,
                 "" if dobro else "   ocekivano: %s red=%d nej=%d" % (ok_kod, ok_r, ok_nj)))
    print("\nneuspjelih: %d/%d" % (lose, len(PROVJERA)))
    return 1 if lose else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="doktrina.py", description="HRCAK preko OAI-PMH: metapodaci, licence, puni tekst.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baza", default=None, help="putanja do doktrina.sqlite")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("setovi", help="popis casopisa (ListSets)")
    ps.add_argument("--pravni", action="store_true", help="samo pravni i pravno-srodni")
    ps.add_argument("--osvjezi", action="store_true", help="ponovno dohvati s posluzitelja")
    ps.set_defaults(f=cmd_setovi)

    ph = sub.add_parser("harvest", help="dohvat jednog seta")
    ph.add_argument("--set", required=True, help="npr. journal:311")
    ph.add_argument("--max", type=int, default=None, help="stani nakon N zapisa")
    ph.add_argument("--od", default=None, help="OAI from=, YYYY-MM-DD")
    ph.add_argument("--puno", action="store_true",
                    help="zanemari zapamceni datestamp i dohvati set od pocetka")
    ph.add_argument("--svjeze", action="store_true", help="zaobidi kes odgovora")
    ph.add_argument("--tekst", action="store_true", help="dohvati i puni tekst PDF-a")
    ph.add_argument("--osobno", action="store_true",
                    help="dohvati tekst i bez otvorene licence; zapisi se oznace "
                         "samo_lokalno=1 i NE smiju se redistribuirati")
    ph.add_argument("--ponovi", action="store_true",
                    help="ponovi i PDF-ove koji su vec zavrsili kao sken/bez-unicode")
    ph.set_defaults(f=cmd_harvest)

    pt = sub.add_parser("stat", help="stanje korpusa")
    pt.add_argument("--set", default=None)
    pt.set_defaults(f=cmd_stat)

    pu = sub.add_parser("ulij", help="prelij clanke s tekstom u glavni korpus")
    pu.add_argument("--korpus", default=None, help="putanja do corpus.sqlite")
    pu.add_argument("--max", type=int, default=None, help="stani nakon N clanaka")
    pu.add_argument("--samo-slobodne", action="store_true", dest="samo_slobodne",
                    help="propusti samo licence koje dopustaju redistribuciju")
    pu.set_defaults(f=cmd_ulij)

    pp = sub.add_parser("provjeri", help="straza klasifikatora licenci (bez mreze)")
    pp.set_defaults(f=cmd_provjeri)

    pn = sub.add_parser("trazi", help="FTS5 pretraga po korpusu")
    pn.add_argument("upit")
    pn.add_argument("--k", type=int, default=10)
    pn.set_defaults(f=cmd_trazi)

    a = ap.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
