#!/usr/bin/env python3
"""
Verifica QUALITA' del Sheet Supermercati — non solo il conteggio.

Nasce dal problema del 2026-07-20: il fetch girava verde, il conteggio saliva a
4690 record, ma il 39.7% delle righe aveva SOLO il nome e l'arricchimento Google
Places non era mai partito (places_checked=1 su 20 righe su 4690).
Contare i record non dice nulla sulla loro utilita' operativa.

Esegue i 5 controlli:
  1. numero record per citta' + citta' attese ma assenti
  2. completezza dei campi principali
  3. coerenza citta' <-> provincia
  4. liste anomale (citta' quasi vuote, record non arricchibili)
  5. duplicati e record privi di informazioni utili

Uso:
    python execution/scripts/verifica_qualita_supermercati.py
    python execution/scripts/verifica_qualita_supermercati.py --citta Napoli
    python execution/scripts/verifica_qualita_supermercati.py --strict   # exit 1 sotto soglia

Exit code 1 con --strict se la qualita' e' sotto le soglie minime accettabili.
"""

import argparse
import collections
import csv
import io
import re
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vTOMKjQcXX5My9om7PYl02Q7"
    "leyOG-5gseeLSuzHaw0oA-rrjM3Ge6JGiTErGnc1MuvMdVyz0O4LpNO/pub"
    "?gid=0&single=true&output=csv"
)

# Soglie minime perche' il database sia considerato "operativamente utilizzabile".
# email esclusa di proposito: Google Places non la restituisce mai, il tetto
# realistico resta ~2-5% e non ha senso far fallire il check su un limite noto.
SOGLIE = {
    "contattabili": 60.0,   # % record con almeno telefono OR sito OR email
    "indirizzo": 70.0,
    "telefono": 60.0,
    "coordinate": 95.0,     # senza coordinate il record non e' arricchibile
    "citta_coperte": 90.0,  # % delle citta' attese presenti nel Sheet
}


def pieno(rec: dict, campo: str) -> bool:
    return (rec.get(campo) or "").strip() not in ("", "-", "—")


def contattabile(rec: dict) -> bool:
    return pieno(rec, "telefono") or pieno(rec, "email") or pieno(rec, "sito_web")


def citta_attese() -> dict[str, str]:
    """Legge le liste dal fetch script: unica fonte di verita', niente copie a mano."""
    script = Path(__file__).with_name("fetch_overpass_supermercati.py")
    if not script.exists():
        return {}
    testo = script.read_text(encoding="utf-8")
    attese: dict[str, str] = {}
    for nome in ("CITIES_MAIN", "CITIES_EXTENDED", "CITIES_LOCALI"):
        m = re.search(nome + r"\s*=\s*\[(.*?)\n\]", testo, re.S)
        if m:
            for citta, prov in re.findall(r'\("([^"]+)","([^"]+)"\)', m.group(1)):
                attese[citta] = prov
    return attese


def scarica(url: str) -> list[dict]:
    print(f"Scarico il Sheet pubblicato...", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "TPM-QualityCheck/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        testo = resp.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(testo)))


def main() -> int:
    ap = argparse.ArgumentParser(description="Verifica qualita' Sheet Supermercati")
    ap.add_argument("--url", default=CSV_URL)
    ap.add_argument("--citta", help="Report dettagliato su una sola citta'")
    ap.add_argument("--strict", action="store_true",
                    help="Exit 1 se la qualita' e' sotto le soglie minime")
    args = ap.parse_args()

    righe = scarica(args.url)
    if not righe:
        print("ERRORE: Sheet vuoto o non raggiungibile")
        return 1

    tot = len(righe)
    attese = citta_attese()
    per_citta: dict[str, list[dict]] = collections.defaultdict(list)
    for r in righe:
        per_citta[(r.get("citta") or "").strip()].append(r)

    print(f"\n{'=' * 62}\nRECORD TOTALI: {tot}   CITTA' NEL SHEET: {len(per_citta)}"
          f"   ATTESE: {len(attese) or 'n/d'}\n{'=' * 62}")

    # --- 2. completezza campi -------------------------------------------------
    print("\n[2] COMPLETEZZA CAMPI PRINCIPALI")
    pct: dict[str, float] = {}
    for campo in ("nome_super", "insegna", "indirizzo", "telefono",
                  "email", "sito_web", "lat"):
        n = sum(1 for r in righe if pieno(r, campo))
        pct[campo] = 100 * n / tot
        etichetta = "coordinate" if campo == "lat" else campo
        print(f"    {etichetta:<12}{n:>6}/{tot}  {pct[campo]:>5.1f}%")
    pct["coordinate"] = pct.pop("lat")

    n_cont = sum(1 for r in righe if contattabile(r))
    pct["contattabili"] = 100 * n_cont / tot
    n_vuoti = sum(1 for r in righe if not contattabile(r) and not pieno(r, "indirizzo"))
    print(f"\n    CONTATTABILI (tel/email/sito): {n_cont}/{tot}  {pct['contattabili']:.1f}%")
    print(f"    SOLO NOME (nessun contatto, nessun indirizzo): {n_vuoti}  {100*n_vuoti/tot:.1f}%")

    arricchiti = sum(1 for r in righe if (r.get("places_checked") or "").strip() == "1")
    print(f"    ARRICCHITI da Google Places: {arricchiti}/{tot}  {100*arricchiti/tot:.1f}%")
    if arricchiti < tot * 0.5:
        print("    >> L'arricchimento non e' stato completato: lancia "
              "enrich-supermercati-google-places.yml")

    # --- 1. copertura citta' --------------------------------------------------
    print("\n[1] COPERTURA CITTA'")
    if attese:
        mancanti = [c for c in attese if c not in per_citta]
        pct["citta_coperte"] = 100 * (len(attese) - len(mancanti)) / len(attese)
        print(f"    presenti {len(attese) - len(mancanti)}/{len(attese)}  "
              f"({pct['citta_coperte']:.1f}%)")
        if mancanti:
            print(f"    MANCANTI ({len(mancanti)}): {', '.join(sorted(mancanti))}")
            print("    >> lancia i workflow fetch-supermercati (main/extended/locali)")
    else:
        pct["citta_coperte"] = 100.0
        print("    fetch_overpass_supermercati.py non trovato: confronto saltato")

    # --- 3. coerenza citta'/provincia ----------------------------------------
    print("\n[3] COERENZA CITTA' <-> PROVINCIA")
    incoerenti = collections.Counter()
    for r in righe:
        c, p = (r.get("citta") or "").strip(), (r.get("provincia") or "").strip()
        if c in attese and p != attese[c]:
            incoerenti[(c, p, attese[c])] += 1
    senza_prov = sum(1 for r in righe if not pieno(r, "provincia"))
    if incoerenti:
        for (c, p, exp), n in incoerenti.most_common(20):
            print(f"    {c}: provincia '{p}' ma attesa '{exp}'  ({n} record)")
    else:
        print("    nessuna incoerenza")
    print(f"    record senza provincia: {senza_prov}")

    # --- 4. liste anomale -----------------------------------------------------
    print("\n[4] LISTE ANOMALE — peggiori 20 citta' per contattabilita' (min 10 record)")
    print(f"    {'citta':<26}{'tot':>5}{'contatt':>9}{'%':>7}{'indir':>7}{'geo':>6}")
    classifica = []
    for c, rs in per_citta.items():
        if len(rs) < 10:
            continue
        ct = sum(1 for r in rs if contattabile(r))
        classifica.append((c, len(rs), ct,
                           sum(1 for r in rs if pieno(r, "indirizzo")),
                           sum(1 for r in rs if pieno(r, "lat"))))
    for c, n, ct, ind, geo in sorted(classifica, key=lambda x: x[2] / x[1])[:20]:
        print(f"    {c:<26}{n:>5}{ct:>9}{100*ct/n:>6.0f}%{ind:>7}{geo:>6}")

    senza_geo = sum(1 for r in righe if not pieno(r, "lat"))
    if senza_geo:
        print(f"\n    NON ARRICCHIBILI (senza coordinate): {senza_geo}  "
              f"{100*senza_geo/tot:.1f}%")
        peggiori = collections.Counter(
            (r.get("citta") or "").strip() for r in righe if not pieno(r, "lat"))
        print("    piu' colpite:", ", ".join(f"{c} ({n})" for c, n in peggiori.most_common(8)))
        print("    >> rilancia i fetch: la versione nuova dello script salva lat/lon")

    piccole = sorted(((c, len(rs)) for c, rs in per_citta.items() if len(rs) < 8),
                     key=lambda x: x[1])
    if piccole:
        print(f"\n    Citta' con <8 record ({len(piccole)}): "
              + ", ".join(f"{c}({n})" for c, n in piccole[:25])
              + (" ..." if len(piccole) > 25 else ""))

    # --- 5. duplicati e record inutili ---------------------------------------
    print("\n[5] DUPLICATI E RECORD SENZA VALORE")
    osm = collections.Counter((r.get("osm_id") or "").strip()
                              for r in righe if (r.get("osm_id") or "").strip())
    dup_osm = {k: v for k, v in osm.items() if v > 1}
    print(f"    osm_id duplicati: {len(dup_osm)}"
          f" (record: {sum(dup_osm.values())})"
          + ("  << upsert rotto, va indagato" if dup_osm else "  OK"))

    chiave = collections.Counter(
        ((r.get("nome_super") or "").strip().lower(),
         (r.get("citta") or "").strip().lower(),
         (r.get("indirizzo") or "").strip().lower())
        for r in righe if (r.get("nome_super") or "").strip())
    ambigui = {k: v for k, v in chiave.items() if v > 1 and not k[2]}
    if ambigui:
        print(f"    stesso nome+citta' SENZA indirizzo: {len(ambigui)} gruppi "
              f"({sum(ambigui.values())} record)")
        print("    (non sono duplicati: osm_id distinti. L'arricchimento li separa "
              "dando a ciascuno il suo indirizzo)")

    generici = sum(1 for r in righe
                   if (r.get("nome_super") or "").strip().lower()
                   in ("", "supermercato", "supermarket", "market",
                       "alimentari", "minimarket", "discount"))
    print(f"    nome generico o vuoto: {generici}")

    # --- insegne: la vista che serve davvero ---------------------------------
    insegne = collections.Counter((r.get("insegna") or "").strip()
                                  for r in righe if (r.get("insegna") or "").strip())
    if insegne:
        top = insegne.most_common(15)
        coperti = sum(v for _, v in top)
        print(f"\n[+] CATENE: {len(insegne)} insegne distinte. Le prime 15 coprono "
              f"{coperti} record ({100*coperti/tot:.1f}%)")
        print("    " + ", ".join(f"{k} ({v})" for k, v in top[:10]))
        print("    >> per una sponsorizzazione nazionale l'interlocutore e' la "
              "catena, non il singolo punto vendita")

    # --- focus citta' ---------------------------------------------------------
    if args.citta:
        rs = per_citta.get(args.citta, [])
        print(f"\n[FOCUS] {args.citta}: {len(rs)} record")
        for campo in ("insegna", "indirizzo", "telefono", "email", "sito_web", "lat"):
            n = sum(1 for r in rs if pieno(r, campo))
            print(f"    {campo:<12}{n:>5}  {100*n/max(1,len(rs)):>5.1f}%")

    # --- verdetto -------------------------------------------------------------
    print(f"\n{'=' * 62}\nVERDETTO (soglie di utilizzabilita' operativa)")
    sotto = []
    for chiave_s, minimo in SOGLIE.items():
        val = pct.get(chiave_s, 0.0)
        ok = val >= minimo
        print(f"    {chiave_s:<16}{val:>6.1f}%  (min {minimo:.0f}%)  "
              f"{'OK' if ok else 'SOTTO SOGLIA'}")
        if not ok:
            sotto.append(chiave_s)
    print(f"    {'email':<16}{pct.get('email', 0):>6.1f}%  "
          "(nessuna soglia: Google Places non restituisce mai l'email)")

    if sotto:
        print(f"\n  DATABASE NON ANCORA UTILIZZABILE — sotto soglia: {', '.join(sotto)}")
        print("  Ordine di intervento: 1) i 3 fetch  2) enrichment a blocchi da 2000")
    else:
        print("\n  DATABASE UTILIZZABILE")
    print("=" * 62)

    return 1 if (args.strict and sotto) else 0


if __name__ == "__main__":
    sys.exit(main())
