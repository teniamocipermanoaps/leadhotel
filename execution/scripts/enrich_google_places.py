"""
enrich_google_places.py — Lead Hotel APS · Dream Team Clown

Arricchisce gli hotel del Google Sheet con dati Google Places API:
- telefono (se mancante in OSM)
- sito_web (se mancante in OSM)
- rating Google (informativo)

Filosofia "budget-safe":
- Scarica il CSV pubblicato della tab Hotel (gratis, no API key)
- Filtra candidati: fonte=osm AND (telefono="" OR sito_web="") AND places_checked != "1"
- Ordina per stelle DESC (priorità ai top hotel)
- Limita a --max-calls (default 5000 → ~$185 = sotto free tier $200/mese)
- Per ogni candidato:
  - Find Place From Text (query: "nome_hotel città Italia") — $0.017
  - Se match con confidence sufficiente, Place Details (telefono, sito, rating) — $0.020
- POST batch ad Apps Script Web App con action="update_enrichment"
- Apps Script:
  - Aggiorna SOLO campi vuoti (mai sovrascrive dati manuali)
  - Marca places_checked=1 anche se nessun risultato (non ri-prova)

Variabili d'ambiente attese (in GitHub Secrets):
  GOOGLE_PLACES_API_KEY — chiave API Google Cloud
  APPS_SCRIPT_URL       — URL /exec del Web App
  APPS_SCRIPT_SECRET    — SHARED_SECRET di Code.gs
  HOTEL_CSV_URL         — URL CSV pubblicato tab Hotel

Uso locale (dry-run):
  python enrich_google_places.py --dry-run --max-calls 10
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

# Forza UTF-8 stdout su Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ============================================================
# CONFIG
# ============================================================

USER_AGENT = "LeadHotelAPS-DreamTeamClown-Enrichment/1.0 (teniamocipermanoonlus.net)"
HTTP_TIMEOUT_SEC = 30
APPS_SCRIPT_TIMEOUT_SEC = 180  # Apps Script può richiedere fino a 3 min per batch grandi (bulk write)
SLEEP_BETWEEN_CALLS_SEC = 0.1  # Google Places limit: 10 QPS — siamo sotto
BATCH_SIZE_POST = 50           # ridotto da 100 → 50 per stare ben sotto al timeout Apps Script
RETRY_POST_MAX = 3             # 3 tentativi per POST in caso di timeout

# Endpoints Google Places (API classica)
PLACES_FIND_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# Default URL CSV pubblicato Hotel (override possibile via env HOTEL_CSV_URL)
DEFAULT_HOTEL_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTkQPCqdtbNREEYL5PnMR4H7RZOd1lFxhxjcLhBMMuu7LBcm4GqwG3TvI5LvMyxDgK_vzeQSb8_l8H6/pub?gid=0&single=true&output=csv"


# ============================================================
# DATA
# ============================================================

@dataclass
class Candidate:
    osm_id: str
    nome_hotel: str
    citta: str
    provincia: str
    indirizzo: str
    stelle: int
    has_phone: bool
    has_website: bool


@dataclass
class EnrichmentResult:
    osm_id: str
    telefono: str = ""
    sito_web: str = ""
    rating: float | None = None


# ============================================================
# HELPERS
# ============================================================

def sanitize_phone(p: str) -> str:
    """Stessa logica di fetch_overpass.py per consistenza."""
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

def download_hotel_csv(url: str) -> list[dict]:
    """Scarica il CSV pubblicato della tab Hotel e ritorna lista di dict."""
    print(f"Scarico CSV Hotel da {url[:60]}...", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        text = resp.read().decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    print(f"  → {len(rows)} righe nel CSV", flush=True)
    return rows


def filter_candidates(rows: list[dict], min_stars: int = 0) -> list[Candidate]:
    """Filtra le righe e crea Candidate ordinati per priorità.

    Criteri:
    - fonte == "osm" (non tocchiamo righe manuali)
    - places_checked != "1" (non ri-controlliamo)
    - telefono vuoto OR sito_web vuoto
    - stelle >= min_stars

    Ordinamento: stelle DESC (5 stelle prima), poi nome alfabetico.
    """
    candidates = []
    for r in rows:
        # Solo righe OSM
        if (r.get("fonte") or "").strip().lower() != "osm":
            continue
        # Skip se già checked
        if (r.get("places_checked") or "").strip() == "1":
            continue
        # Skip se ha già sia telefono che sito (niente da arricchire)
        has_phone = bool((r.get("telefono") or "").strip())
        has_website = bool((r.get("sito_web") or "").strip())
        if has_phone and has_website:
            continue
        # Skip senza osm_id (anomalia)
        osm_id = (r.get("osm_id") or "").strip()
        if not osm_id:
            continue
        # Parse stelle
        try:
            stelle = int(r.get("stelle") or 0)
        except ValueError:
            stelle = 0
        if stelle < min_stars:
            continue
        candidates.append(Candidate(
            osm_id=osm_id,
            nome_hotel=(r.get("nome_hotel") or "").strip(),
            citta=(r.get("citta") or "").strip(),
            provincia=(r.get("provincia") or "").strip(),
            indirizzo=(r.get("indirizzo") or "").strip(),
            stelle=stelle,
            has_phone=has_phone,
            has_website=has_website,
        ))
    # Ordina per stelle DESC, poi nome
    candidates.sort(key=lambda c: (-c.stelle, c.nome_hotel.lower()))
    return candidates


# ============================================================
# GOOGLE PLACES API
# ============================================================

def places_find(api_key: str, query: str) -> str | None:
    """Find Place From Text → ritorna place_id o None."""
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
    """Place Details → ritorna {phone, website, rating} o None."""
    params = {
        "key": api_key,
        "place_id": place_id,
        "language": "it",
        "fields": "international_phone_number,formatted_phone_number,website,rating",
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
    """Lancia find + details per un singolo hotel. Sempre ritorna result (può essere vuoto)."""
    # Query ottimizzata: nome hotel + città + Italia (aiuta Google a disambiguare)
    query = f"{c.nome_hotel}, {c.citta} {c.provincia}, Italia"
    place_id = places_find(api_key, query)
    if not place_id:
        return EnrichmentResult(osm_id=c.osm_id)  # marked but empty → places_checked=1
    time.sleep(SLEEP_BETWEEN_CALLS_SEC)
    details = places_details(api_key, place_id)
    if not details:
        return EnrichmentResult(osm_id=c.osm_id)
    phone_raw = details.get("international_phone_number") or details.get("formatted_phone_number") or ""
    website = normalize_url(details.get("website") or "")
    rating = details.get("rating")
    return EnrichmentResult(
        osm_id=c.osm_id,
        telefono=sanitize_phone(phone_raw),
        sito_web=website,
        rating=rating,
    )


# ============================================================
# POST AD APPS SCRIPT
# ============================================================

def post_to_apps_script(url: str, secret: str, records: list[dict]) -> dict:
    """POST con retry su timeout (Apps Script può rallentare con Sheet grandi).
    Backoff: 10s, 30s, 60s.
    """
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
    parser = argparse.ArgumentParser(description="Arricchisce hotel OSM con dati Google Places")
    parser.add_argument("--dry-run", action="store_true", help="Stampa risultati ma non invia ad Apps Script")
    parser.add_argument("--max-calls", type=int, default=5000,
                        help="Max hotel da arricchire in questo run (default 5000 = ~$185 in free tier)")
    parser.add_argument("--min-stars", type=int, default=0,
                        help="Solo hotel con almeno N stelle (default: 0 = tutti)")
    parser.add_argument("--city", help="Limita a una sola città (per test)")
    args = parser.parse_args()

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    apps_url = os.environ.get("APPS_SCRIPT_URL", "")
    apps_secret = os.environ.get("APPS_SCRIPT_SECRET", "")
    hotel_csv_url = os.environ.get("HOTEL_CSV_URL", DEFAULT_HOTEL_CSV_URL)

    if not api_key:
        print("ERRORE: GOOGLE_PLACES_API_KEY non impostato", file=sys.stderr)
        sys.exit(2)
    if not args.dry_run and (not apps_url or not apps_secret):
        print("ERRORE: APPS_SCRIPT_URL / APPS_SCRIPT_SECRET non impostati", file=sys.stderr)
        sys.exit(2)

    # 1) Scarica e filtra
    rows = download_hotel_csv(hotel_csv_url)
    candidates = filter_candidates(rows, min_stars=args.min_stars)
    if args.city:
        candidates = [c for c in candidates if c.citta.lower() == args.city.lower()]
    print(f"Candidati per enrichment: {len(candidates)} (totale CSV: {len(rows)})", flush=True)

    # 2) Limita
    if len(candidates) > args.max_calls:
        print(f"Limitato a primi {args.max_calls} per rispetto budget", flush=True)
        candidates = candidates[:args.max_calls]

    if not candidates:
        print("Niente da arricchire. Esco.", flush=True)
        return

    # 3) Chiamate Google Places + collect results
    results = []
    success = 0
    for i, c in enumerate(candidates):
        print(f"[{i+1}/{len(candidates)}] ⭐{c.stelle} {c.nome_hotel} ({c.citta}) ...", flush=True)
        r = enrich_candidate(api_key, c)
        # Conta come successo se ha trovato almeno un campo
        if r.telefono or r.sito_web or r.rating is not None:
            success += 1
            print(f"  ✓ tel={'sì' if r.telefono else 'no'}  web={'sì' if r.sito_web else 'no'}  rating={r.rating}", flush=True)
        else:
            print(f"  - nessun risultato", flush=True)
        results.append(r)
        time.sleep(SLEEP_BETWEEN_CALLS_SEC)

    print(f"\nRichiamato Places per {len(candidates)} hotel. Successi: {success}", flush=True)

    if args.dry_run:
        print("--dry-run: non scrivo nel Sheet. Esempi:")
        for r in results[:5]:
            print(f"  {r.osm_id}: tel='{r.telefono}' web='{r.sito_web}' rating={r.rating}")
        return

    # 4) POST batch ad Apps Script
    records = []
    for r in results:
        rec = {"osm_id": r.osm_id}
        if r.telefono: rec["telefono"] = r.telefono
        if r.sito_web: rec["sito_web"] = r.sito_web
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
