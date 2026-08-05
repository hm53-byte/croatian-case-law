# -*- coding: utf-8 -*-
"""
Pretvorba izvezenih presuda (.md) u PDF.

Koristi Chrome u headless načinu (već instaliran) — nema vanjskih ovisnosti,
a tipografija i hrvatski znakovi izlaze uredno. Pandoc/LaTeX nisu potrebni.

Pokretanje:
    python u_pdf.py <mapa-s-md> [--izlaz <mapa>] [--zbirno]

Primjer:
    python u_pdf.py ../SUME55/odluke/zamjena_nekretnina_sume/1_JAKE_zamjena_sume --zbirno
"""
from __future__ import annotations

import argparse
import html
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
* { box-sizing: border-box; }
body {
  font-family: "Charter","Palatino",Georgia,"Times New Roman",serif;
  font-size: 10.5pt; line-height: 1.5; color: #16181d; margin: 0;
  -webkit-font-smoothing: antialiased;
}
h1 { font-size: 15pt; line-height: 1.25; margin: 0 0 10px; color: #0f1115;
     border-bottom: 2px solid #2c3e50; padding-bottom: 7px; }
h2 { font-size: 12pt; margin: 22px 0 8px; page-break-after: avoid; }
.meta { background: #f4f6f8; border-left: 3px solid #5a7184;
        padding: 9px 12px; margin: 0 0 16px; font-size: 9pt;
        line-height: 1.55; page-break-inside: avoid; }
.meta div { margin: 1.5px 0; }
.meta b { color: #33475b; font-weight: 600; }
p { margin: 0 0 7px; text-align: justify; hyphens: auto; orphans: 2; widows: 2; }
.izreka { font-weight: 600; }
hr { border: 0; border-top: 1px solid #d4dae0; margin: 14px 0; }
.footer { margin-top: 20px; padding-top: 7px; border-top: 1px solid #d4dae0;
          font-size: 7.5pt; color: #7a848e; }
.doc + .doc { page-break-before: always; }
a { color: #2b5b8c; text-decoration: none; word-break: break-all; }
"""


def md_u_html(tekst: str) -> str:
    """Minimalni pretvarač — datoteke imaju poznatu, jednostavnu strukturu."""
    redci = tekst.split("\n")
    naslov, meta, tijelo, faza = "", [], [], "zaglavlje"

    for r in redci:
        s = r.rstrip()
        if faza == "zaglavlje":
            if s.startswith("# "):
                naslov = s[2:].strip()
                continue
            if s.startswith("- **"):
                m = re.match(r"-\s+\*\*(.+?):\*\*\s*(.*)", s)
                if m:
                    meta.append((m.group(1), m.group(2)))
                continue
            if s.strip() == "---":
                faza = "tijelo"
                continue
            if not s.strip():
                continue
            faza = "tijelo"
        if faza == "tijelo":
            tijelo.append(s)

    def esc(x: str) -> str:
        x = html.escape(x)
        return re.sub(r"(https?://\S+)", r'<a href="\1">\1</a>', x)

    d = [f"<h1>{esc(naslov)}</h1>"]
    if meta:
        d.append('<div class="meta">')
        for k, v in meta:
            d.append(f"<div><b>{esc(k)}:</b> {esc(v)}</div>")
        d.append("</div>")

    # izreka presude (velika razmaknuta slova) neka bude podebljana
    for red in tijelo:
        if not red.strip():
            continue
        klasa = ""
        zbito = re.sub(r"\s+", "", red)
        if len(zbito) < 60 and re.match(r"^[A-ZŠĐČĆŽ\s]{6,}$", red.strip()):
            klasa = ' class="izreka"'
        elif re.match(r"^\s*(p r e s u d i o|r i j e š i o|presudio je|riješio je)", red, re.I):
            klasa = ' class="izreka"'
        d.append(f"<p{klasa}>{esc(red.strip())}</p>")
    return "\n".join(d)


def u_pdf(html_tekst: str, cilj: pathlib.Path, naslov: str) -> bool:
    doc = (f"<!doctype html><html lang='hr'><head><meta charset='utf-8'>"
           f"<title>{html.escape(naslov)}</title><style>{CSS}</style></head>"
           f"<body>{html_tekst}</body></html>")
    with tempfile.TemporaryDirectory() as td:
        h = pathlib.Path(td) / "d.html"
        h.write_text(doc, encoding="utf-8")
        profil = pathlib.Path(td) / "prof"
        # Bez ovih zastavica se Chrome vješa: pokreće tijek prvog pokretanja i
        # čeka pozadinsku mrežu, pa --print-to-pdf nikad ne dovrši.
        osnovne = [
            "--disable-gpu", "--no-sandbox", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions",
            "--disable-background-networking", "--disable-sync",
            "--disable-default-apps", "--no-pdf-header-footer",
        ]
        for zastavice in (["--headless=new"], ["--headless"]):
            try:
                subprocess.run(
                    [CHROME, *zastavice, *osnovne, f"--user-data-dir={profil}",
                     f"--print-to-pdf={cilj}", h.as_uri()],
                    capture_output=True, timeout=90)
            except subprocess.TimeoutExpired:
                pass
            if cilj.exists() and cilj.stat().st_size > 1000:
                return True
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mapa")
    ap.add_argument("--izlaz", default=None)
    ap.add_argument("--zbirno", action="store_true",
                    help="uz pojedinačne, izradi i jedan objedinjeni PDF")
    a = ap.parse_args()

    if not pathlib.Path(CHROME).exists():
        print("Chrome nije nađen — pretvorba nije moguća."); sys.exit(1)

    izvor = pathlib.Path(a.mapa).resolve()
    cilj = pathlib.Path(a.izlaz).resolve() if a.izlaz else izvor / "PDF"
    cilj.mkdir(parents=True, exist_ok=True)

    datoteke = sorted(izvor.glob("*.md"))
    if not datoteke:
        print(f"Nema .md datoteka u {izvor}"); sys.exit(1)
    print(f"Pretvaram {len(datoteke)} datoteka -> {cilj}\n")

    svi, uspjeh = [], 0
    for i, f in enumerate(datoteke, 1):
        h = md_u_html(f.read_text(encoding="utf-8", errors="replace"))
        svi.append(f'<div class="doc">{h}</div>')
        out = cilj / (f.stem + ".pdf")
        if u_pdf(h, out, f.stem):
            uspjeh += 1
            print(f"  [{i}/{len(datoteke)}] {out.name}  ({out.stat().st_size/1024:.0f} KB)")
        else:
            print(f"  [{i}/{len(datoteke)}] NEUSPJEH: {f.name}")

    print(f"\nPojedinačnih PDF-ova: {uspjeh}/{len(datoteke)}")

    if a.zbirno and svi:
        zb = cilj / "_ZBIRNO_sve_odluke.pdf"
        if u_pdf("\n".join(svi), zb, "Zbirka odluka"):
            print(f"Objedinjeni PDF: {zb.name} ({zb.stat().st_size/1024/1024:.1f} MB)")


if __name__ == "__main__":
    main()
