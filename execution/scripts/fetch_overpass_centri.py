"""
fetch_overpass_centri.py — Lead Centri Commerciali APS · Dream Team Clown

Estrae da OpenStreetMap (Overpass API) tutti i centri commerciali (shop=mall)
nei 107 capoluoghi di provincia italiani + 4 grandi città (Monza, Andria, Forlì,
Cesena), e li carica nel Google Sheet "Lead Centri Commerciali APS" via Apps
Script Web App.

Architettura speculare a fetch_overpass.py per gli hotel:
- Stessa logica di retry + backoff + multi-mirror Overpass.
- Stesso pattern POST → Apps Script.
- Sanitize telefoni come gli hotel.

Variabili d'ambiente (GitHub Secrets):
  CENTRI_APPS_SCRIPT_URL    — URL /exec del Web App del nuovo Sheet Centri
  CENTRI_APPS_SCRIPT_SECRET — SHARED_SECRET del nuovo Apps Script Centri

Esecuzione locale (dry-run):
    python fetch_overpass_centri.py --dry-run --city Roma
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
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

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]
USER_AGENT = "LeadCentriAPS-DreamTeamClown/1.0 (teniamocipermanoonlus.net)"
SLEEP_BETWEEN_QUERIES_SEC = 5.0
RETRY_BACKOFF_SEC = [5, 15, 45]
HTTP_TIMEOUT_SEC = 90
BATCH_SIZE_POST = 100

# Tag OSM per centri commerciali. Solo shop=mall (no department_store, no outlet)
# come da scelta utente.
MALL_FILTER = "mall"

# ============================================================
# CITIES — 107 capoluoghi di provincia italiani + 4 grandi città
# ============================================================
# Lista completa di tutti i comuni capoluogo di provincia in Italia
# ordinati per regione (per leggibilità nel codice). La query Overpass
# usa il nome del comune, non quello della provincia.

CITIES = [
    # PIEMONTE (8)
    ("Torino","TO"),("Asti","AT"),("Alessandria","AL"),("Biella","BI"),
    ("Cuneo","CN"),("Novara","NO"),("Vercelli","VC"),("Verbania","VB"),
    # VALLE D'AOSTA (1)
    ("Aosta","AO"),
    # LIGURIA (4)
    ("Genova","GE"),("Imperia","IM"),("La Spezia","SP"),("Savona","SV"),
    # LOMBARDIA (12)
    ("Milano","MI"),("Bergamo","BG"),("Brescia","BS"),("Como","CO"),
    ("Cremona","CR"),("Lecco","LC"),("Lodi","LO"),("Mantova","MN"),
    ("Monza","MB"),("Pavia","PV"),("Sondrio","SO"),("Varese","VA"),
    # TRENTINO-ALTO ADIGE (2)
    ("Trento","TN"),("Bolzano","BZ"),
    # VENETO (7)
    ("Venezia","VE"),("Belluno","BL"),("Padova","PD"),("Rovigo","RO"),
    ("Treviso","TV"),("Verona","VR"),("Vicenza","VI"),
    # FRIULI-VENEZIA GIULIA (4)
    ("Trieste","TS"),("Gorizia","GO"),("Pordenone","PN"),("Udine","UD"),
    # EMILIA-ROMAGNA (9)
    ("Bologna","BO"),("Ferrara","FE"),("Forlì","FC"),("Cesena","FC"),
    ("Modena","MO"),("Parma","PR"),("Piacenza","PC"),("Ravenna","RA"),
    ("Reggio Emilia","RE"),("Rimini","RN"),
    # TOSCANA (10)
    ("Firenze","FI"),("Arezzo","AR"),("Grosseto","GR"),("Livorno","LI"),
    ("Lucca","LU"),("Massa","MS"),("Pisa","PI"),("Pistoia","PT"),
    ("Prato","PO"),("Siena","SI"),
    # UMBRIA (2)
    ("Perugia","PG"),("Terni","TR"),
    # MARCHE (5)
    ("Ancona","AN"),("Ascoli Piceno","AP"),("Fermo","FM"),
    ("Macerata","MC"),("Pesaro","PU"),
    # LAZIO (5)
    ("Roma","RM"),("Frosinone","FR"),("Latina","LT"),("Rieti","RI"),("Viterbo","VT"),
    # ABRUZZO (4)
    ("L'Aquila","AQ"),("Chieti","CH"),("Pescara","PE"),("Teramo","TE"),
    # MOLISE (2)
    ("Campobasso","CB"),("Isernia","IS"),
    # CAMPANIA (5)
    ("Napoli","NA"),("Avellino","AV"),("Benevento","BN"),
    ("Caserta","CE"),("Salerno","SA"),
    # PUGLIA (6+1)
    ("Bari","BA"),("Andria","BT"),("Brindisi","BR"),
    ("Foggia","FG"),("Lecce","LE"),("Taranto","TA"),
    # BASILICATA (2)
    ("Potenza","PZ"),("Matera","MT"),
    # CALABRIA (5)
    ("Catanzaro","CZ"),("Cosenza","CS"),("Crotone","KR"),
    ("Reggio Calabria","RC"),("Vibo Valentia","VV"),
    # SICILIA (9)
    ("Palermo","PA"),("Agrigento","AG"),("Caltanissetta","CL"),
    ("Catania","CT"),("Enna","EN"),("Messina","ME"),("Ragusa","RG"),
    ("Siracusa","SR"),("Trapani","TP"),
    # SARDEGNA (5)
    ("Cagliari","CA"),("Nuoro","NU"),("Oristano","OR"),("Sassari","SS"),
    ("Carbonia","SU"),
]


# ============================================================
# DATA
# ============================================================

@dataclass
class CentroRecord:
    osm_id: str
    citta: str
    provincia: str
    nome_centro: str
    indirizzo: str
    telefono: str
    email: str
    sito_web: str

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# OVERPASS QUERY
# ============================================================

def build_overpass_query(city_name: str) -> str:
    """Centri commerciali (shop=mall) dentro l'area amministrativa del comune."""
    return f"""
[out:json][timeout:50];
area["name"="{city_name}"]["boundary"="administrative"]["admin_level"~"^(8|9|10)$"]->.searchArea;
(
  node["shop"="{MALL_FILTER}"](area.searchArea);
  way["shop"="{MALL_FILTER}"](area.searchArea);
  relation["shop"="{MALL_FILTER}"](area.searchArea);
);
out tags center;
"""


def fetch_overpass(query: str) -> dict:
    data = ("data=" + urllib.parse.quote(query)).encode("utf-8")
    last_err = None
    for attempt in range(len(RETRY_BACKOFF_SEC) + 1):
        endpoint = OVERPASS_ENDPOINTS[attempt % len(OVERPASS_ENDPOINTS)]
        req = urllib.request.Request(
            endpoint,
            data=data,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < len(RETRY_BACKOFF_SEC):
                wait_s = RETRY_BACKOFF_SEC[attempt]
                print(f"    Overpass HTTP {e.code}, retry {attempt+1}/{len(RETRY_BACKOFF_SEC)+1} su altro mirror in {wait_s}s...", file=sys.stderr)
                time.sleep(wait_s)
                last_err = e
                continue
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            raise RuntimeError(f"Overpass HTTP {e.code}: {body[:200]}") from e
        except urllib.error.URLError as e:
            if attempt < len(RETRY_BACKOFF_SEC):
                wait_s = RETRY_BACKOFF_SEC[attempt]
                print(f"    Overpass URL error, retry {attempt+1}/{len(RETRY_BACKOFF_SEC)+1} su altro mirror in {wait_s}s...", file=sys.stderr)
                time.sleep(wait_s)
                last_err = e
                continue
            raise RuntimeError(f"Overpass URL error: {e}") from e
    raise last_err if last_err else RuntimeError("Overpass failed all retries")


# ============================================================
# PARSING / SANITIZE
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


def build_address(tags: dict) -> str:
    parts = []
    street = tags.get("addr:street", "").strip()
    house = tags.get("addr:housenumber", "").strip()
    if street:
        parts.append(f"{street}{(' ' + house) if house else ''}")
    postcode = tags.get("addr:postcode", "").strip()
    city = tags.get("addr:city", "").strip()
    if postcode and city:
        parts.append(f"{postcode} {city}")
    elif postcode:
        parts.append(postcode)
    elif city:
        parts.append(city)
    return ", ".join(parts)


def normalize_url(u: str) -> str:
    if not u:
        return ""
    u = u.strip()
    if u and not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


def osm_element_to_record(el: dict, city_name: str, provincia: str) -> CentroRecord | None:
    tags = el.get("tags", {}) or {}
    name = (tags.get("name") or "").strip()
    if not name:
        return None
    osm_type = el.get("type", "?")[0]
    osm_id = f"{osm_type}{el.get('id')}"
    return CentroRecord(
        osm_id=osm_id,
        citta=city_name,
        provincia=provincia,
        nome_centro=name,
        indirizzo=build_address(tags),
        telefono=sanitize_phone(tags.get("phone") or tags.get("contact:phone") or ""),
        email=(tags.get("email") or tags.get("contact:email") or "").strip(),
        sito_web=normalize_url(tags.get("website") or tags.get("contact:website") or ""),
    )


def fetch_city(city_name: str, provincia: str) -> list[CentroRecord]:
    query = build_overpass_query(city_name)
    raw = fetch_overpass(query)
    elements = raw.get("elements", [])
    records: list[CentroRecord] = []
    seen_ids: set[str] = set()
    for el in elements:
        rec = osm_element_to_record(el, city_name, provincia)
        if rec and rec.osm_id not in seen_ids:
            records.append(rec)
            seen_ids.add(rec.osm_id)
    return records


# ============================================================
# POST AD APPS SCRIPT
# ============================================================

def post_to_apps_script(url: str, secret: str, centri: list[dict]) -> dict:
    payload = json.dumps({"secret": secret, "action": "upsert_centri", "centri": centri}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
    with opener.open(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def batched(items: list, n: int) -> Iterable[list]:
    for i in range(0, len(items), n):
        yield items[i:i + n]


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Fetch centri commerciali da Overpass → Google Sheet")
    parser.add_argument("--dry-run", action="store_true", help="Non inviare ad Apps Script; stampa JSON a stdout")
    parser.add_argument("--city", help="Limita a una sola città (per test). Es: --city Roma")
    args = parser.parse_args()

    cities = CITIES
    if args.city:
        cities = [c for c in CITIES if c[0].lower() == args.city.lower()]
        if not cities:
            print(f"Città '{args.city}' non in lista", file=sys.stderr)
            sys.exit(2)

    apps_url = os.environ.get("CENTRI_APPS_SCRIPT_URL", "")
    apps_secret = os.environ.get("CENTRI_APPS_SCRIPT_SECRET", "")
    if not args.dry_run and (not apps_url or not apps_secret):
        print("ERRORE: CENTRI_APPS_SCRIPT_URL / CENTRI_APPS_SCRIPT_SECRET non impostati", file=sys.stderr)
        sys.exit(2)

    total_records = 0
    grand_totals = {"inserted": 0, "updated": 0, "skipped": 0}
    failed_cities: list[str] = []        # errori Overpass (tollerabili)
    write_failed_cities: list[str] = []  # errori scrittura Apps Script (gravi)

    for idx, (city, prov) in enumerate(cities):
        print(f"[{idx+1}/{len(cities)}] {city} ({prov}) ...", flush=True)
        try:
            records = fetch_city(city, prov)
        except Exception as e:
            print(f"  ERRORE Overpass: {e}", file=sys.stderr)
            failed_cities.append(city)
            time.sleep(SLEEP_BETWEEN_QUERIES_SEC)
            continue

        total_records += len(records)
        print(f"  → {len(records)} centri trovati")

        if args.dry_run:
            for r in records[:3]:
                print("    " + json.dumps(r.to_dict(), ensure_ascii=False))
        else:
            for batch in batched([r.to_dict() for r in records], BATCH_SIZE_POST):
                try:
                    resp = post_to_apps_script(apps_url, apps_secret, batch)
                    if not resp.get("ok"):
                        print(f"  ERRORE Apps Script (risposta): {resp}", file=sys.stderr)
                        write_failed_cities.append(city)
                        break
                    grand_totals["inserted"] += resp.get("inserted", 0)
                    grand_totals["updated"]  += resp.get("updated", 0)
                    grand_totals["skipped"]  += resp.get("skipped", 0)
                except Exception as e:
                    print(f"  ERRORE POST Apps Script (rete): {e}", file=sys.stderr)
                    write_failed_cities.append(city)
                    break

        time.sleep(SLEEP_BETWEEN_QUERIES_SEC)

    print("")
    print("=" * 60)
    print(f"COMPLETATO. Centri trovati totali: {total_records}")
    if not args.dry_run:
        print(f"  - Inseriti: {grand_totals['inserted']}")
        print(f"  - Aggiornati: {grand_totals['updated']}")
        print(f"  - Skipped: {grand_totals['skipped']}")
    if failed_cities:
        print(f"  Città con errori Overpass (timeout/rate-limit): {', '.join(failed_cities)}")

    # === ESITO ===
    if write_failed_cities:
        print(f"  ❌ ERRORE SCRITTURA sul Sheet per: {', '.join(write_failed_cities)}")
        print("     Verifica CENTRI_APPS_SCRIPT_URL / CENTRI_APPS_SCRIPT_SECRET e il deployment Apps Script.")
        sys.exit(1)

    if not args.dry_run and total_records > 0 and (grand_totals["inserted"] + grand_totals["updated"] + grand_totals["skipped"]) == 0:
        print("  ❌ Trovati record ma nessuno scritto nel Sheet.")
        sys.exit(1)

    if failed_cities and total_records == 0:
        print("  ❌ Nessun dato recuperato: fallimento totale Overpass.")
        sys.exit(1)

    if failed_cities:
        print(f"  ✅ OK parziale: {total_records} record processati nonostante {len(failed_cities)} città in errore Overpass.")


if __name__ == "__main__":
    main()
