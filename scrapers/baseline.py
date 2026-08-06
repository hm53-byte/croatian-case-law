# -*- coding: utf-8 -*-
"""
OSNOVICA za višeoznačnu klasifikaciju hrvatske sudske prakse po EuroVocu.

Zašto osnovica: bez nje se ne zna vrijedi li išta složenije. Model koji dobije
mikro F1 od 0,70 zvuči dobro dok se ne vidi da TF-IDF s linearnim klasifikatorom
daje 0,68 uz tisućinu troška. Ovaj modul postavlja tu referentnu točku.

Zadatak: iz teksta odluke predvidjeti EuroVoc područja (velikim slovima u
hijerarhiji, npr. PRAVO, KAZNENO PRAVO, ŠUMARSTVO I RIBARSTVO). Oznake dolaze
s portala, nisu ručno dodane.

Postupak:
  TF-IDF (riječi + znakovni n-grami)  ->  OneVsRest logistička regresija
  podjela na skup za učenje i provjeru, uz očuvanje rijetkih oznaka
  mjere: mikro i makro F1, po oznaci precision/recall/F1

Ovo se vrti na CPU-u u nekoliko minuta i ne treba GPU.

Pokretanje:
    python baseline.py                      # trening i izvjestaj
    python baseline.py --min-primjera 20    # ukljuci i rjede oznake
    python baseline.py --izvjestaj docs/baseline.md
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import re
import statistics

from common import log, PROJECT_DIR
import store

# EuroVoc podrucja su pisana VELIKIM slovima; uzi pojmovi malim.
RE_PODRUCJE = re.compile(r"[A-ZŠĐČĆŽ]{3,}(?:\s+[A-ZŠĐČĆŽ]{2,})*")

SJEME = 20260805


def oznake_iz(eurovoc: str) -> set[str]:
    out = set()
    for m in RE_PODRUCJE.finditer(eurovoc or ""):
        s = re.sub(r"\s+", " ", m.group(0)).strip()
        if 3 < len(s) < 40:
            out.add(s)
    return out


def ucitaj(min_primjera: int = 30) -> tuple[list[str], list[set[str]], list[str]]:
    con = store.veza()
    tekstovi, oznake = [], []
    for r in con.execute(
        "SELECT tekst, eurovoc FROM odluke "
        "WHERE eurovoc IS NOT NULL AND eurovoc <> '' AND tekst IS NOT NULL"):
        o = oznake_iz(r[1])
        if o and len(r[0] or "") > 500:
            tekstovi.append(r[0])
            oznake.append(o)

    brojac = collections.Counter(x for s in oznake for x in s)
    zadrzane = sorted(x for x, k in brojac.items() if k >= min_primjera)
    # izbaci dokumente koji nakon filtriranja ostanu bez ijedne oznake
    T, O = [], []
    for t, s in zip(tekstovi, oznake):
        s2 = s & set(zadrzane)
        if s2:
            T.append(t)
            O.append(s2)
    return T, O, zadrzane


def pokreni(min_primjera: int, izvjestaj: str | None) -> None:
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.multiclass import OneVsRestClassifier
    from sklearn.pipeline import FeatureUnion
    from sklearn.preprocessing import MultiLabelBinarizer
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report, f1_score

    T, O, oznake = ucitaj(min_primjera)
    log(f"dokumenata: {len(T)} | oznaka: {len(oznake)} | "
        f"prosjecno oznaka po dokumentu: {statistics.mean(len(s) for s in O):.1f}")
    if len(T) < 50 or len(oznake) < 2:
        log("[!] premalo podataka za osnovicu")
        return

    mlb = MultiLabelBinarizer(classes=oznake)
    Y = mlb.fit_transform(O)

    # Stratifikacija po najrjedoj oznaci dokumenta, da rijetke oznake ne nestanu
    # iz skupa za provjeru. Potpuna viseoznacna stratifikacija trazi vanjsku
    # biblioteku, a ovo je dovoljno dobro za osnovicu.
    ucest = collections.Counter(x for s in O for x in s)
    strat = [min(s, key=lambda x: ucest[x]) for s in O]
    # Skupine s jednim clanom se spajaju u "__ostalo__". Ako i ta skupina ostane
    # sama, stratifikacija nije moguca i pada se na obicnu podjelu.
    prerijetke = {k for k, v in collections.Counter(strat).items() if v < 2}
    strat = [("__ostalo__" if s in prerijetke else s) for s in strat]
    if min(collections.Counter(strat).values()) < 2:
        log("[i] stratifikacija nije moguca (preveliki broj rijetkih oznaka), "
            "koristi se obicna podjela")
        strat = None

    Xtr, Xte, Ytr, Yte = train_test_split(
        T, Y, test_size=0.25, random_state=SJEME, stratify=strat)
    log(f"ucenje: {len(Xtr)} | provjera: {len(Xte)}")

    # Rijeci hvataju pravni rjecnik, znakovni n-grami hvataju sklonidbu i
    # nedosljednu dijakritiku, sto je u hrvatskom bitno.
    vek = FeatureUnion([
        ("rijeci", TfidfVectorizer(lowercase=True, ngram_range=(1, 2),
                                   min_df=3, max_features=200_000,
                                   sublinear_tf=True, strip_accents="unicode")),
        ("znakovi", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                    min_df=3, max_features=200_000,
                                    sublinear_tf=True)),
    ])
    log("gradim znacajke...")
    Xtr_v = vek.fit_transform(Xtr)
    Xte_v = vek.transform(Xte)
    log(f"znacajki: {Xtr_v.shape[1]}")

    log("ucim OneVsRest logisticku regresiju...")
    clf = OneVsRestClassifier(
        LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced"),
        n_jobs=-1)
    clf.fit(Xtr_v, Ytr)

    Yp = clf.predict(Xte_v)
    mikro = f1_score(Yte, Yp, average="micro", zero_division=0)
    makro = f1_score(Yte, Yp, average="macro", zero_division=0)

    # Trivijalna osnovica: uvijek predvidi N najcescih oznaka.
    ucest_tr = Ytr.sum(axis=0)
    k = int(round(Ytr.sum(axis=1).mean()))
    top = np.argsort(-ucest_tr)[:k]
    Ytriv = np.zeros_like(Yte)
    Ytriv[:, top] = 1
    mikro_triv = f1_score(Yte, Ytriv, average="micro", zero_division=0)

    log("")
    log(f"  mikro F1:            {mikro:.3f}")
    log(f"  makro F1:            {makro:.3f}")
    log(f"  mikro F1 (trivijalno, {k} najcescih oznaka): {mikro_triv:.3f}")
    log("")
    izv = classification_report(Yte, Yp, target_names=oznake,
                                zero_division=0, digits=3)
    log(izv)

    if izvjestaj:
        p = pathlib.Path(izvjestaj)
        if not p.is_absolute():
            p = PROJECT_DIR / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "# Osnovica: klasifikacija po EuroVocu\n\n"
            "Referentna točka za svaki složeniji model. Oznake dolaze s portala\n"
            "(polje EuroVoc), nisu ručno dodane. Postupak i mjere opisani su u\n"
            "`scrapers/baseline.py`.\n\n"
            f"- Dokumenata: **{len(T)}**\n"
            f"- Oznaka (područja s najmanje {min_primjera} primjera): **{len(oznake)}**\n"
            f"- Prosječno oznaka po dokumentu: {statistics.mean(len(s) for s in O):.1f}\n"
            f"- Podjela: {len(Xtr)} za učenje, {len(Xte)} za provjeru\n"
            f"- Značajki nakon TF-IDF: {Xtr_v.shape[1]}\n\n"
            "## Rezultat\n\n"
            "| Mjera | Vrijednost |\n|---|---|\n"
            f"| Mikro F1 | **{mikro:.3f}** |\n"
            f"| Makro F1 | **{makro:.3f}** |\n"
            f"| Mikro F1, trivijalno ({k} najčešćih oznaka) | {mikro_triv:.3f} |\n\n"
            "Trivijalna osnovica pokazuje koliko se dobiva pukim pogađanjem\n"
            "najčešćih oznaka. Svaki model koji je ne nadmašuje uvjerljivo nije\n"
            "naučio ništa korisno.\n\n"
            "## Po oznaci\n\n```\n" + izv + "\n```\n\n"
            "## Ograničenja\n\n"
            "Korpus je prikupljen ciljano oko šumarske tematike, pa raspodjela\n"
            "oznaka ne odražava bazu od 1,17 milijuna odluka. Brojke su referentna\n"
            "točka za ovaj skup, ne procjena za cijelu praksu.\n",
            encoding="utf-8")
        log(f"[spremljeno] {p}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-primjera", type=int, default=30)
    ap.add_argument("--izvjestaj", default=None)
    a = ap.parse_args()
    pokreni(a.min_primjera, a.izvjestaj)


if __name__ == "__main__":
    main()
