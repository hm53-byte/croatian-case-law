# -*- coding: utf-8 -*-
"""
Analiza korpusa: zamjena šuma i šumskih zemljišta po čl. 55. Zakona o šumama.

Problem koji ovaj modul rješava: puko traženje "članak 55" daje mnoštvo lažnih
pogodaka jer čl. 55. postoji i u Zakonu o naknadi (denacionalizacija), Zakonu o
vlasništvu i drugdje. Klasifikator zato traži čl. 55. SAMO u dosluhu sa Zakonom
o šumama (prozor od ±400 znakova) te odvojeno boduje materijalne signale
zamjene (okrupnjivanje, gospodarska jedinica, ugovor o zamjeni, srazmjerna
vrijednost).

Pokretanje:
    python analiza_cl55.py                 # rangirana lista kandidata
    python analiza_cl55.py --izvezi        # + fulltext u PRESUDE/SUME55/odluke/
"""
from __future__ import annotations

import argparse
import re

from common import PROJECT_DIR, log
import store

SUME55_DIR = PROJECT_DIR / "SUME55"

# --- prepoznavanje propisa ------------------------------------------------
RE_ZOS = re.compile(r"zakon[a-z]*\s+o\s+šumama|\bZŠ\b|Zakona\s+o\s+šumama", re.I)
RE_55 = re.compile(r"čl(?:anak|anka|ankom|anku|\.)\s*55|\b55\.\s*(?:st|Zakona)", re.I)
RE_NAKNADA = re.compile(r"zakon[a-z]*\s+o\s+naknadi", re.I)

# --- materijalni signali zamjene po čl. 55. -------------------------------
SIGNALI = {
    "okrupnjivanje šuma": (re.compile(r"okrupnjivanj[a-z]*\s+(?:šum|drž)", re.I), 4),
    "gospodarska jedinica": (re.compile(r"(?:iste|susjedn[a-z]*)\s+gospodarsk[a-z]*\s+jedinic", re.I), 4),
    "ugovor o zamjeni nekretnina": (re.compile(r"ugovor[a-z]*\s+o\s+zamjeni\s+nekretnin", re.I), 3),
    "odluka o zamjeni šuma": (re.compile(r"odluk[a-z]*\s+o\s+zamjeni\s+šum", re.I), 5),
    "srazmjerna vrijednost / 5 %": (re.compile(r"srazmjern[a-z]*\s+vrijednost|odstupanj[a-z]*\s+od\s*5\s*%", re.I), 3),
    "zamjena + šumsko zemljište": (re.compile(r"zamjen[a-z]*[^.]{0,120}šumsk[a-z]*\s+zemljišt", re.I), 2),
    "Hrvatske šume / javni šumoposjednik": (re.compile(r"Hrvatske\s+šume|javn[a-z]*\s+šumoposjednik", re.I), 1),
    "ministar sklapa ugovor": (re.compile(r"ministar[a-z]*\s+sklapa\s+ugovor", re.I), 3),
}

# --- ishod postupka --------------------------------------------------------
RE_USVOJEN = re.compile(r"(usvaja\s+se\s+tužben|poništava\s+se\s+rješenj|"
                        r"nalaže\s+se[^.]{0,80}sklopi|utvrđuje\s+se\s+da\s+je[^.]{0,80}zamjen)", re.I)
RE_ODBIJEN = re.compile(r"(odbija\s+se\s+tužben[a-z]*\s+zahtjev|odbija\s+se\s+tužba|"
                        r"odbija\s+se\s+žalba)", re.I)


def blizina(tekst: str, a: re.Pattern, b: re.Pattern, prozor: int = 400) -> list[str]:
    """Vraća isječke gdje se uzorci a i b pojavljuju unutar `prozor` znakova."""
    poz_b = [m.start() for m in b.finditer(tekst)]
    if not poz_b:
        return []
    out = []
    for m in a.finditer(tekst):
        for pb in poz_b:
            if abs(m.start() - pb) <= prozor:
                i = min(m.start(), pb)
                out.append(re.sub(r"\s+", " ", tekst[max(0, i - 200): i + 500]))
                break
    return out


def ocijeni(rec) -> dict:
    t = rec["tekst"] or ""
    signali, bodovi = [], 0

    # čl. 55. mora biti u dosluhu sa Zakonom o šumama
    konteksti = blizina(t, RE_55, RE_ZOS)
    if konteksti:
        bodovi += 6
        signali.append("čl.55 + Zakon o šumama (blizina)")

    for ime, (rx, w) in SIGNALI.items():
        if rx.search(t):
            bodovi += w
            signali.append(ime)

    # kazna za očiti drugi propis
    if RE_NAKNADA.search(t) and not RE_ZOS.search(t):
        bodovi -= 6
        signali.append("(!) čl.55 Zakona o naknadi — drugi propis")

    ishod = ""
    if RE_USVOJEN.search(t):
        ishod = "zahtjev USVOJEN (barem djelomično)"
    elif RE_ODBIJEN.search(t):
        ishod = "zahtjev ODBIJEN"

    return {"bodovi": bodovi, "signali": signali, "ishod": ishod,
            "konteksti": konteksti[:3]}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--prag", type=int, default=6)
    p.add_argument("--izvezi", action="store_true",
                   help="spremi fulltext kandidata u SUME55/odluke/")
    a = p.parse_args()

    con = store.veza()
    redovi = con.execute("SELECT * FROM odluke").fetchall()
    log(f"Korpus: {len(redovi)} odluka\n")

    kand = []
    for r in redovi:
        o = ocijeni(r)
        if o["bodovi"] >= a.prag:
            kand.append((o, r))
    kand.sort(key=lambda x: -x[0]["bodovi"])

    log(f"Kandidata iznad praga {a.prag}: {len(kand)}\n" + "=" * 90)
    for o, r in kand:
        log(f"\n[{o['bodovi']:2d}] {r['sud']} — {r['broj']} ({r['datum']})")
        log(f"     {r['pravomocnost']}  {('| ' + o['ishod']) if o['ishod'] else ''}")
        log(f"     signali: {', '.join(o['signali'])}")
        log(f"     {r['url']}")
        for k in o["konteksti"][:1]:
            log(f"     »{k[:400]}«")

    if a.izvezi and kand:
        d = SUME55_DIR / "odluke"
        d.mkdir(parents=True, exist_ok=True)
        for o, r in kand:
            from common import slugify
            ime = slugify(f"{o['bodovi']:02d}_{r['sud']}_{r['broj']}")
            zaglavlje = [
                f"# {r['sud']} — {r['broj']}", "",
                f"- **Datum odluke:** {r['datum']}",
                f"- **Vrsta:** {r['vrsta']}",
                f"- **Pravomoćnost:** {r['pravomocnost']}",
                f"- **ECLI:** {r['ecli']}",
                f"- **Stvarno kazalo:** {r['kazalo']}",
                f"- **Izvor:** {r['url']}",
                f"- **Relevantnost (bodovi):** {o['bodovi']}",
                f"- **Signali:** {', '.join(o['signali'])}",
                f"- **Ishod:** {o['ishod'] or 'nije automatski razlučen'}",
                "", "---", "", r["tekst"] or "", "",
            ]
            (d / f"{ime}.md").write_text("\n".join(zaglavlje), encoding="utf-8")
        log(f"\n[izvezeno] {len(kand)} odluka u fulltextu -> {d}")


if __name__ == "__main__":
    main()
