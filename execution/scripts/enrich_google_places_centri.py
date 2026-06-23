"""
enrich_google_places_centri.py — Lead Centri Commerciali APS · Dream Team Clown

Arricchisce i centri commerciali del Google Sheet "Lead Centri Commerciali APS"
con dati Google Places API: indirizzo, telefono, sito_web, rating.

Gemello di enrich_google_places.py (hotel), adattato per:
- env CENTRI_APPS_SCRIPT_URL / CENTRI_APPS_SCRIPT_SECRET
- CSV centri (campo nome_centro)
- query "nome centro, città, centro commerciale Italia"
- nessun ordinamento per stelle (i centri non ne hanno) → alfabetico

Variabili d'ambiente (GitHub Secrets):
  GOOGLE_PLACES_API_KEY      — chiave API Google Cloud (condivisa con hotel)
  CENTRI_APPS_SCRIPT_URL     — URL /exec del Web App Centri
  CENTRI_APPS_SCRIPT_SECRET  — SHARED_SECRET di Code.gs centri
  CENTRI_CSV_URL             — URL CSV pubblicato tab Centri

Uso locale (dry-run):
  python enrich_google_places_centri.py --dry-run --max-calls 10
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Iterable

import urllib.request
import urllib.error
import urllib.parse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ============================================================
# CONFIG
# ============================================================

USER_AGENT = "LeadCentriAPS-DreamTeamClown-Enrichment/1.0 (teniamocipermanoonlus.net)"
HTTP_TIMEOUT_SEC = 30
APPS_SCRIPT_TIMEOUT_SEC = 180
SLEEP_BETWEEN_CALLS_SEC = 0.1
BATCH_SIZE_POST = 50
RETRY_POST_MAX = 3

PLACES_FIND_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# Default URL CSV pubblicato Centri (override via env CENTRI_CSV_URL)
DEFAULT_CENTRI_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTIurc1W0f_TJaOJsyyEogUEU9x9wiumg38MVHoFzmGMJQP6bOVjxbkQR3iL32xBjgC7ZJ0-1goGsYj/pub?gid=0&single=true&output=csv"


# ============================================================
# DATA
# ============================================================

@dataclass
class Candidate:
    osm_id: str
    nome_centro: str
    citta: str
    provincia: str
    indirizzo: str
    has_phone: bool
    has_website: bool
    has_address: bool


@dataclass
class EnrichmentResult:
    osm_id: str
    telefono: str = ""
    sito_web: str = ""
    indirizzo: str = ""
    rating: float | None = None


# ============================================================
# HELPERS
# ============================================================

def sanitize_phone(p: str) -> str:
    if not p:
        return ""
    p = p.strip()
    if not p:
        return ""
    if "@" in p:
        return ""
    n_digits = sum(1 for c in p if c.isdigit())
    if n_digits < 6:
        return ""
    if p[0] in ("+", "=", "-", "@"):
        if p.startswith("+"):
            p = "00" + p[1:]
        else:
            p = " " + p
    return p


def normalize_url(u: str) -> str:
    if not u:
        return ""
    u = u.strip()
    if u and not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


def http_get_json(url: str, params: dict, timeout: int = HTTP_TIMEOUT_SEC) -> dict:
    qs = urllib.parse.urlencode(params)
    full_url = url + "?" + qs
    req = urllib.request.Request(full_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ============================================================
# CARICAMENTO E FILTRO CANDIDATI
# ============================================================

def download_centri_csv(url: str) -> list[dict]:
    print(f"Scarico CSV Centri da {url[:60]}...", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        text = resp.read().decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    print(f"  → {len(rows)} righe nel CSV", flush=True)
    return rows


def filter_candidates(rows: list[dict]) -> list[Candidate]:
    """Centri OSM non ancora checkati, a cui manca almeno un campo (indirizzo/telefono/sito)."""
    candidates = []
    for r in rows:
        if (r.get("fonte") or "").strip().lower() != "osm":
            continue
        if (r.get("places_checked") or "").strip() == "1":
            continue
        has_phone = bool((r.get("telefono") or "").strip())
        has_website = bool((r.get("sito_web") or "").strip())
        has_address = bool((r.get("indirizzo") or "").strip())
        if has_phone and has_website and has_address:
            continue
        osm_id = (r.get("osm_id") or "").strip()
        if not osm_id:
            continue
        candidates.append(Candidate(
            osm_id=osm_id,
            nome_centro=(r.get("nome_centro") or "").strip(),
            citta=(r.get("citta") or "").strip(),
            provincia=(r.get("provincia") or "").strip(),
            indirizzo=(r.get("indirizzo") or "").strip(),
            has_phone=has_phone,
            has_website=has_website,
            has_address=has_address,
        ))
    candidates.sort(key=lambda c: c.nome_centro.lower())
    return candidates


# ============================================================
# GOOGLE PLACES API
# ============================================================

def places_find(api_key: str, query: str) -> str | None:
    params = {
        "key": api_key,
        "input": query,
        "inputtype": "textquery",
        "language": "it",
        "fields": "place_id,name,formatted_address",
    }
    try:
        data = http_get_json(PLACES_FIND_URL, params)
    except Exception as e:
        print(f"    ERR find: {e}", file=sys.stderr)
        return None
    status = data.get("status", "")
    if status == "ZERO_RESULTS":
        return None
    if status != "OK":
        print(f"    Find status {status}: {data.get('error_message','')}", file=sys.stderr)
        return None
    candidates = data.get("candidates", [])
    if not candidates:
        return None
    return candidates[0].get("place_id")


def places_details(api_key: str, place_id: str) -> dict | None:
    params = {
        "key": api_key,
        "place_id": place_id,
        "language": "it",
        "fields": "international_phone_number,formatted_phone_number,website,rating,formatted_address",
    }
    try:
        data = http_get_json(PLACES_DETAILS_URL, params)
    except Exception as e:
        print(f"    ERR details: {e}", file=sys.stderr)
        return None
    status = data.get("status", "")
    if status != "OK":
        print(f"    Details status {status}: {data.get('error_message','')}", file=sys.stderr)
        return None
    return data.get("result", {})


def enrich_candidate(api_key: str, c: Candidate) -> EnrichmentResult:
    # Hint "centro commerciale" aiuta Google a disambiguare
    query = f"{c.nome_centro}, {c.citta} {c.provincia}, centro commerciale Italia"
    place_id = places_find(api_key, query)
    if not place_id:
        return EnrichmentResult(osm_id=c.osm_id)
    time.sleep(SLEEP_BETWEEN_CALLS_SEC)
    details = places_details(api_key, place_id)
    if not details:
        return EnrichmentResult(osm_id=c.osm_id)
    phone_raw = details.get("international_phone_number") or details.get("formatted_phone_number") or ""
    website = normalize_url(details.get("website") or "")
    rating = details.get("rating")
    indirizzo = (details.get("formatted_address") or "").strip()
    return EnrichmentResult(
        osm_id=c.osm_id,
        telefono=sanitize_phone(phone_raw),
        sito_web=website,
        indirizzo=indirizzo,
        rating=rating,
    )


# ============================================================
# POST AD APPS SCRIPT
# ============================================================

def post_to_apps_script(url: str, secret: str, records: list[dict]) -> dict:
    payload = json.dumps({"secret": secret, "action": "update_enrichment", "records": records}).encode("utf-8")
    backoffs = [10, 30, 60]
    last_err = None
    for attempt in range(RETRY_POST_MAX + 1):
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
        try:
            with opener.open(req, timeout=APPS_SCRIPT_TIMEOUT_SEC) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_err = e
            if attempt < RETRY_POST_MAX:
                wait_s = backoffs[attempt]
                print(f"  POST timeout (tentativo {attempt+1}/{RETRY_POST_MAX+1}), retry in {wait_s}s...", file=sys.stderr)
                time.sleep(wait_s)
                continue
            raise
    raise last_err if last_err else RuntimeError("Unknown post error")


def batched(items: list, n: int) -> Iterable[list]:
    for i in range(0, len(items), n):
        yield items[i:i + n]


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Arricchisce centri commerciali OSM con dati Google Places")
    parser.add_argument("--dry-run", action="store_true", help="Stampa risultati ma non invia ad Apps Script")
    parser.add_argument("--max-calls", type=int, default=5000,
                        help="Max centri da arricchire in questo run (default 5000)")
    parser.add_argument("--city", help="Limita a una sola città (per test)")
    args = parser.parse_args()

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    apps_url = os.environ.get("CENTRI_APPS_SCRIPT_URL", "")
    apps_secret = os.environ.get("CENTRI_APPS_SCRIPT_SECRET", "")
    centri_csv_url = os.environ.get("CENTRI_CSV_URL", DEFAULT_CENTRI_CSV_URL)

    if not api_key:
        print("ERRORE: GOOGLE_PLACES_API_KEY non impostato", file=sys.stderr)
        sys.exit(2)
    if not args.dry_run and (not apps_url or not apps_secret):
        print("ERRORE: CENTRI_APPS_SCRIPT_URL / CENTRI_APPS_SCRIPT_SECRET non impostati", file=sys.stderr)
        sys.exit(2)

    rows = download_centri_csv(centri_csv_url)
    candidates = filter_candidates(rows)
    if args.city:
        candidates = [c for c in candidates if c.citta.lower() == args.city.lower()]
    print(f"Candidati per enrichment: {len(candidates)} (totale CSV: {len(rows)})", flush=True)

    if len(candidates) > args.max_calls:
        print(f"Limitato a primi {args.max_calls} per rispetto budget", flush=True)
        candidates = candidates[:args.max_calls]

    if not candidates:
        print("Niente da arricchire. Esco.", flush=True)
        return

    results = []
    success = 0
    for i, c in enumerate(candidates):
        print(f"[{i+1}/{len(candidates)}] {c.nome_centro} ({c.citta}) ...", flush=True)
        r = enrich_candidate(api_key, c)
        if r.telefono or r.sito_web or r.indirizzo or r.rating is not None:
            success += 1
            print(f"  ✓ ind={'sì' if r.indirizzo else 'no'}  tel={'sì' if r.telefono else 'no'}  web={'sì' if r.sito_web else 'no'}  rating={r.rating}", flush=True)
        else:
            print(f"  - nessun risultato", flush=True)
        results.append(r)
        time.sleep(SLEEP_BETWEEN_CALLS_SEC)

    print(f"\nRichiamato Places per {len(candidates)} centri. Successi: {success}", flush=True)

    if args.dry_run:
        print("--dry-run: non scrivo nel Sheet. Esempi:")
        for r in results[:5]:
            print(f"  {r.osm_id}: ind='{r.indirizzo}' tel='{r.telefono}' web='{r.sito_web}' rating={r.rating}")
        return

    records = []
    for r in results:
        rec = {"osm_id": r.osm_id}
        if r.telefono: rec["telefono"] = r.telefono
        if r.sito_web: rec["sito_web"] = r.sito_web
        if r.indirizzo: rec["indirizzo"] = r.indirizzo
        if r.rating is not None: rec["rating"] = r.rating
        records.append(rec)

    totals = {"updated": 0, "marked": 0, "skipped": 0, "not_found": 0}
    for batch in batched(records, BATCH_SIZE_POST):
        try:
            resp = post_to_apps_script(apps_url, apps_secret, batch)
            if not resp.get("ok"):
                print(f"  ERRORE Apps Script: {resp}", file=sys.stderr)
                continue
            for k in totals:
                totals[k] += resp.get(k, 0)
        except Exception as e:
            print(f"  ERRORE POST: {e}", file=sys.stderr)

    print("")
    print("=" * 60)
    print(f"COMPLETATO. Candidati processati: {len(candidates)}")
    print(f"  - Aggiornati (qualche campo nuovo): {totals['updated']}")
    print(f"  - Marcati come 'già checked' (no nuovi dati): {totals['marked']}")
    print(f"  - Skippati (es. fonte=manuale): {totals['skipped']}")
    print(f"  - Non trovati nel Sheet: {totals['not_found']}")


if __name__ == "__main__":
    main()
