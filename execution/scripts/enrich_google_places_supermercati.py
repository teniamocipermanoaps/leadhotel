"""
enrich_google_places_supermercati.py — Lead Supermercati APS · Dream Team Clown

Arricchisce i supermercati del Google Sheet "Lead Supermercati APS" con dati
Google Places API: indirizzo, telefono, sito_web, rating.

Gemello di enrich_google_places_centri.py, adattato per:
- env SUPER_APPS_SCRIPT_URL / SUPER_APPS_SCRIPT_SECRET
- CSV supermercati (campo nome_super + insegna)
- query "nome supermercato, insegna, città, supermercato Italia"
- priorità: prima i punti vendita con insegna nota (catene → più probabile match Google)

Variabili d'ambiente (GitHub Secrets):
  GOOGLE_PLACES_API_KEY      — chiave API Google Cloud (condivisa)
  SUPER_APPS_SCRIPT_URL      — URL /exec del Web App Supermercati
  SUPER_APPS_SCRIPT_SECRET   — SHARED_SECRET di Code.gs supermercati
  SUPER_CSV_URL              — URL CSV pubblicato tab Supermercati

Uso locale (dry-run):
  python enrich_google_places_supermercati.py --dry-run --max-calls 10
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

USER_AGENT = "LeadSupermercatiAPS-DreamTeamClown-Enrichment/1.0 (teniamocipermanoonlus.net)"
HTTP_TIMEOUT_SEC = 30
APPS_SCRIPT_TIMEOUT_SEC = 180
SLEEP_BETWEEN_CALLS_SEC = 0.1
BATCH_SIZE_POST = 50
RETRY_POST_MAX = 3

PLACES_FIND_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

DEFAULT_SUPER_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTOMKjQcXX5My9om7PYl02Q7leyOG-5gseeLSuzHaw0oA-rrjM3Ge6JGiTErGnc1MuvMdVyz0O4LpNO/pub?gid=0&single=true&output=csv"


# ============================================================
# DATA
# ============================================================

@dataclass
class Candidate:
    osm_id: str
    nome_super: str
    insegna: str
    citta: str
    provincia: str
    indirizzo: str
    lat: str = ""
    lon: str = ""


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
    if not p or "@" in p:
        return ""
    if sum(1 for c in p if c.isdigit()) < 6:
        return ""
    if p[0] in ("+", "=", "-", "@"):
        p = "00" + p[1:] if p.startswith("+") else " " + p
    return p


def normalize_url(u: str) -> str:
    if not u:
        return ""
    u = u.strip()
    if u and not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


def http_get_json(url: str, params: dict, timeout: int = HTTP_TIMEOUT_SEC) -> dict:
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ============================================================
# CARICAMENTO E FILTRO
# ============================================================

def download_super_csv(url: str) -> list[dict]:
    print(f"Scarico CSV Supermercati da {url[:60]}...", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        text = resp.read().decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    print(f"  → {len(rows)} righe nel CSV", flush=True)
    return rows


def filter_candidates(rows: list[dict]) -> list[Candidate]:
    """Supermercati OSM non ancora checkati, a cui manca almeno un campo.
    Ordine di priorità: prima quelli CON insegna nota (match Google più affidabile),
    poi per nome alfabetico.
    """
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
        lat = (r.get("lat") or "").strip()
        lon = (r.get("lon") or "").strip()
        # ⚠️ SENZA COORDINATE non arricchiamo: Google restituirebbe sempre lo stesso
        # negozio per tutti gli omonimi di catena (bug dati errati del 2026-07-19).
        if not lat or not lon:
            continue
        candidates.append(Candidate(
            osm_id=osm_id,
            nome_super=(r.get("nome_super") or "").strip(),
            insegna=(r.get("insegna") or "").strip(),
            citta=(r.get("citta") or "").strip(),
            provincia=(r.get("provincia") or "").strip(),
            indirizzo=(r.get("indirizzo") or "").strip(),
            lat=lat,
            lon=lon,
        ))
    # Priorità: con insegna prima (0), senza insegna dopo (1); poi nome
    candidates.sort(key=lambda c: (0 if c.insegna else 1, c.nome_super.lower()))
    return candidates


# ============================================================
# GOOGLE PLACES
# ============================================================

def places_find(api_key: str, query: str, lat: str = "", lon: str = "") -> tuple[str, dict] | tuple[None, None]:
    """Find Place con locationbias sulle coordinate OSM.

    CRITICO per le catene: senza locationbias, cercare "Conad Roma" restituisce
    sempre lo STESSO negozio per tutti i 100+ Conad di Roma. Con il bias sul punto
    GPS, Google restituisce il punto vendita effettivamente in quella posizione.

    Ritorna (place_id, geometry) per permettere la verifica di distanza.
    """
    params = {
        "key": api_key,
        "input": query,
        "inputtype": "textquery",
        "language": "it",
        "fields": "place_id,name,formatted_address,geometry",
    }
    if lat and lon:
        # circle:raggio_metri@lat,lng — 400 m attorno al punto OSM
        params["locationbias"] = f"circle:400@{lat},{lon}"
    try:
        data = http_get_json(PLACES_FIND_URL, params)
    except Exception as e:
        print(f"    ERR find: {e}", file=sys.stderr)
        return None, None
    status = data.get("status", "")
    if status == "ZERO_RESULTS":
        return None, None
    if status != "OK":
        print(f"    Find status {status}: {data.get('error_message','')}", file=sys.stderr)
        return None, None
    cands = data.get("candidates", [])
    if not cands:
        return None, None
    return cands[0].get("place_id"), (cands[0].get("geometry") or {})


def distanza_metri(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza approssimata in metri (formula equirettangolare, ok per brevi distanze)."""
    import math
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    x = dlon * math.cos((p1 + p2) / 2)
    return math.sqrt(x * x + dlat * dlat) * R


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
    if data.get("status") != "OK":
        print(f"    Details status {data.get('status')}: {data.get('error_message','')}", file=sys.stderr)
        return None
    return data.get("result", {})


MAX_DISTANZA_MATCH_M = 500.0  # oltre questa distanza il match è considerato sbagliato


def enrich_candidate(api_key: str, c: Candidate) -> tuple[EnrichmentResult, str]:
    """Ritorna (risultato, motivo). motivo = 'ok' | 'no_match' | 'troppo_lontano'."""
    nome_query = c.nome_super
    if c.insegna and c.insegna.lower() not in c.nome_super.lower():
        nome_query = f"{c.insegna} {c.nome_super}"
    query = f"{nome_query}, {c.citta}"

    place_id, geometry = places_find(api_key, query, c.lat, c.lon)
    if not place_id:
        return EnrichmentResult(osm_id=c.osm_id), "no_match"

    # === VERIFICA DISTANZA ===
    # Se Google ha restituito un negozio lontano dal punto OSM, è l'omonimo
    # sbagliato → scartiamo (meglio nessun dato che un telefono errato).
    try:
        loc = (geometry or {}).get("location") or {}
        g_lat, g_lon = float(loc.get("lat")), float(loc.get("lng"))
        d = distanza_metri(float(c.lat), float(c.lon), g_lat, g_lon)
        if d > MAX_DISTANZA_MATCH_M:
            return EnrichmentResult(osm_id=c.osm_id), f"troppo_lontano ({int(d)}m)"
    except (TypeError, ValueError):
        # Geometry mancante/illeggibile → non possiamo verificare: scartiamo per prudenza
        return EnrichmentResult(osm_id=c.osm_id), "no_geometry"

    time.sleep(SLEEP_BETWEEN_CALLS_SEC)
    details = places_details(api_key, place_id)
    if not details:
        return EnrichmentResult(osm_id=c.osm_id), "no_details"
    phone_raw = details.get("international_phone_number") or details.get("formatted_phone_number") or ""
    return EnrichmentResult(
        osm_id=c.osm_id,
        telefono=sanitize_phone(phone_raw),
        sito_web=normalize_url(details.get("website") or ""),
        indirizzo=(details.get("formatted_address") or "").strip(),
        rating=details.get("rating"),
    ), "ok"


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
                print(f"  POST timeout (tentativo {attempt+1}), retry in {wait_s}s...", file=sys.stderr)
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
    parser = argparse.ArgumentParser(description="Arricchisce supermercati OSM con Google Places")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-calls", type=int, default=5000,
                        help="Max supermercati da arricchire in questo run (default 5000)")
    parser.add_argument("--city", help="Limita a una sola città (test)")
    parser.add_argument("--insegna", help="Limita a una sola insegna (es: Conad)")
    args = parser.parse_args()

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    apps_url = os.environ.get("SUPER_APPS_SCRIPT_URL", "")
    apps_secret = os.environ.get("SUPER_APPS_SCRIPT_SECRET", "")
    csv_url = os.environ.get("SUPER_CSV_URL", DEFAULT_SUPER_CSV_URL)

    if not api_key:
        print("ERRORE: GOOGLE_PLACES_API_KEY non impostato", file=sys.stderr)
        sys.exit(2)
    if not args.dry_run and (not apps_url or not apps_secret):
        print("ERRORE: SUPER_APPS_SCRIPT_URL / SUPER_APPS_SCRIPT_SECRET non impostati", file=sys.stderr)
        sys.exit(2)

    rows = download_super_csv(csv_url)
    candidates = filter_candidates(rows)
    if args.city:
        candidates = [c for c in candidates if c.citta.lower() == args.city.lower()]
    if args.insegna:
        candidates = [c for c in candidates if args.insegna.lower() in c.insegna.lower()]
    print(f"Candidati per enrichment: {len(candidates)} (totale CSV: {len(rows)})", flush=True)

    if len(candidates) > args.max_calls:
        print(f"Limitato a primi {args.max_calls} per rispetto budget", flush=True)
        candidates = candidates[:args.max_calls]

    if not candidates:
        print("Niente da arricchire. Esco.", flush=True)
        return

    results = []
    success = 0
    scartati = {"no_match": 0, "troppo_lontano": 0, "no_geometry": 0, "no_details": 0}
    for i, c in enumerate(candidates):
        etichetta = f"{c.insegna} · {c.nome_super}" if c.insegna else c.nome_super
        print(f"[{i+1}/{len(candidates)}] {etichetta} ({c.citta}) ...", flush=True)
        r, motivo = enrich_candidate(api_key, c)
        if motivo == "ok" and (r.telefono or r.sito_web or r.indirizzo or r.rating is not None):
            success += 1
            print(f"  ✓ ind={'sì' if r.indirizzo else 'no'}  tel={'sì' if r.telefono else 'no'}  web={'sì' if r.sito_web else 'no'}  rating={r.rating}", flush=True)
        else:
            key = motivo.split(" ")[0]
            scartati[key] = scartati.get(key, 0) + 1
            print(f"  - scartato: {motivo}", flush=True)
        results.append(r)
        time.sleep(SLEEP_BETWEEN_CALLS_SEC)

    print(f"\nRichiamato Places per {len(candidates)} supermercati.")
    print(f"  Match validi: {success}")
    print(f"  Scartati: no_match={scartati.get('no_match',0)} · troppo_lontano={scartati.get('troppo_lontano',0)} · no_geometry={scartati.get('no_geometry',0)} · no_details={scartati.get('no_details',0)}", flush=True)

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
    write_errors = 0
    for batch in batched(records, BATCH_SIZE_POST):
        try:
            resp = post_to_apps_script(apps_url, apps_secret, batch)
            if not resp.get("ok"):
                print(f"  ERRORE Apps Script: {resp}", file=sys.stderr)
                write_errors += 1
                continue
            for k in totals:
                totals[k] += resp.get(k, 0)
        except Exception as e:
            print(f"  ERRORE POST: {e}", file=sys.stderr)
            write_errors += 1

    print("")
    print("=" * 60)
    print(f"COMPLETATO. Candidati processati: {len(candidates)}")
    print(f"  - Aggiornati (nuovi dati): {totals['updated']}")
    print(f"  - Marcati (nessun dato nuovo): {totals['marked']}")
    print(f"  - Skippati: {totals['skipped']}")
    print(f"  - Non trovati nel Sheet: {totals['not_found']}")

    if write_errors > 0:
        print(f"  ❌ {write_errors} batch NON scritti nel Sheet — verifica SUPER_APPS_SCRIPT_URL/SECRET.")
        sys.exit(1)


if __name__ == "__main__":
    main()
