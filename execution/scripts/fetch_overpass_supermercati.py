"""
fetch_overpass_supermercati.py — Lead Supermercati APS · Dream Team Clown

Estrae da OpenStreetMap (Overpass API) tutti i supermercati (shop=supermarket)
nelle 145 città target (50 principali + 93 comuni locali, stessa lista degli hotel)
e li carica nel Google Sheet "Lead Supermercati APS" via Apps Script Web App.

Gemello di fetch_overpass.py / fetch_overpass_centri.py.
Volume atteso: ~30.000-45.000 punti vendita → split in 2 dataset (main / extended)
per stare sotto il timeout di GitHub Actions.

Variabili d'ambiente (GitHub Secrets):
  SUPER_APPS_SCRIPT_URL    — URL /exec del Web App del Sheet Supermercati
  SUPER_APPS_SCRIPT_SECRET — SHARED_SECRET di Code.gs supermercati

Esecuzione locale (dry-run):
    python fetch_overpass_supermercati.py --dry-run --city Firenze
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
USER_AGENT = "LeadSupermercatiAPS-DreamTeamClown/1.0 (teniamocipermanoonlus.net)"
SLEEP_BETWEEN_QUERIES_SEC = 5.0
RETRY_BACKOFF_SEC = [5, 15, 45]
HTTP_TIMEOUT_SEC = 90
BATCH_SIZE_POST = 100

# Tag OSM: shop=supermarket copre supermercati e ipermercati.
SHOP_FILTER = "supermarket"

# ============================================================
# CITIES — stessa lista degli hotel (50 main + 93 extended)
# ============================================================

CITIES_MAIN = [
    ("Roma","RM"),("Milano","MI"),("Napoli","NA"),("Torino","TO"),("Palermo","PA"),
    ("Genova","GE"),("Bologna","BO"),("Firenze","FI"),("Bari","BA"),("Catania","CT"),
    ("Venezia","VE"),("Verona","VR"),("Messina","ME"),("Padova","PD"),("Trieste","TS"),
    ("Taranto","TA"),("Brescia","BS"),("Parma","PR"),("Prato","PO"),("Modena","MO"),
    ("Reggio Calabria","RC"),("Reggio Emilia","RE"),("Perugia","PG"),("Ravenna","RA"),
    ("Livorno","LI"),("Cagliari","CA"),("Foggia","FG"),("Rimini","RN"),("Salerno","SA"),
    ("Ferrara","FE"),("Sassari","SS"),("Latina","LT"),("Caserta","CE"),("Monza","MB"),
    ("Siracusa","SR"),("Pescara","PE"),("Bergamo","BG"),("Forlì","FC"),("Trento","TN"),
    ("Vicenza","VI"),("Terni","TR"),("Bolzano","BZ"),("Novara","NO"),("Piacenza","PC"),
    ("Ancona","AN"),("Andria","BT"),("Arezzo","AR"),("Udine","UD"),("Cesena","FC"),
    ("Lecce","LE"),
]

CITIES_EXTENDED = [
    # Campania
    ("Giugliano in Campania","NA"),("Lacco Ameno","NA"),("Nola","NA"),("Sorrento","NA"),
    ("Vico Equense","NA"),("Pozzuoli","NA"),("San Giorgio a Cremano","NA"),("Afragola","NA"),
    ("Caivano","NA"),("Castel Volturno","CE"),("Torre del Greco","NA"),("Cicciano","NA"),
    ("Pompei","NA"),("Pomigliano d'Arco","NA"),("Scisciano","NA"),("Avellino","AV"),
    ("Nocera Inferiore","SA"),("Scafati","SA"),("Angri","SA"),("Cava de' Tirreni","SA"),
    ("Maddaloni","CE"),("San Clemente","CE"),("Casapulla","CE"),("Aversa","CE"),
    ("Marcianise","CE"),("Sessa Aurunca","CE"),("Mondragone","CE"),
    # Lazio
    ("Frosinone","FR"),("Alatri","FR"),("Sora","FR"),("Isola del Liri","FR"),
    ("San Giorgio a Liri","FR"),("Ceccano","FR"),("Veroli","FR"),("Ceprano","FR"),
    ("Fiuggi","FR"),("Colleferro","RM"),("Velletri","RM"),("Albano Laziale","RM"),
    ("Lanuvio","RM"),("Cisterna di Latina","LT"),("Minturno","LT"),("Castelforte","LT"),
    ("Santi Cosma e Damiano","LT"),("Formia","LT"),
    # Lombardia
    ("Melzo","MI"),("Cene","BG"),("Appiano Gentile","CO"),("Cantù","CO"),
    # Piemonte
    ("Settimo Torinese","TO"),
    # Veneto
    ("Monteforte d'Alpone","VR"),("Sommacampagna","VR"),("Mestre","VE"),("Zelarino","VE"),
    ("Mogliano Veneto","TV"),("Scorzè","VE"),("Chirignago","VE"),("Cazzago di Pianiga","VE"),
    ("Trebaseleghe","PD"),
    # Puglia
    ("Monopoli","BA"),("Fasano","BR"),("San Giovanni Rotondo","FG"),("Manfredonia","FG"),
    ("Monte Sant'Angelo","FG"),("Torremaggiore","FG"),
    # Emilia-Romagna
    ("Carpi","MO"),
    # Sicilia
    ("Taormina","ME"),("Milazzo","ME"),("Sant'Agata di Militello","ME"),("Capo d'Orlando","ME"),
    ("Nizza di Sicilia","ME"),("Furci Siculo","ME"),("Santa Marina Salina","ME"),
    ("Ragusa","RG"),("Vittoria","RG"),("Comiso","RG"),("Pozzallo","RG"),
    ("Augusta","SR"),("Lentini","SR"),("Termini Imerese","PA"),("Bagheria","PA"),
    ("Gravina di Catania","CT"),("Caltagirone","CT"),("Acireale","CT"),
    ("Trapani","TP"),("Valderice","TP"),("Xitta","TP"),("Enna","EN"),("Troina","EN"),
    # Sardegna
    ("Sestu","CA"),("Capoterra","CA"),("Quartu Sant'Elena","CA"),("Pula","CA"),
    ("Ussana","CA"),("Selargius","CA"),
    # Toscana
    ("Settignano","FI"),
]

CITIES_ALL = CITIES_MAIN + CITIES_EXTENDED


# ============================================================
# DATA
# ============================================================

@dataclass
class SupermercatoRecord:
    osm_id: str
    citta: str
    provincia: str
    nome_super: str
    insegna: str          # brand OSM (Coop, Conad, Lidl...) — utile per raggruppare
    indirizzo: str
    telefono: str
    email: str
    sito_web: str

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# OVERPASS
# ============================================================

def build_overpass_query(city_name: str) -> str:
    return f"""
[out:json][timeout:60];
area["name"="{city_name}"]["boundary"="administrative"]["admin_level"~"^(8|9|10)$"]->.searchArea;
(
  node["shop"="{SHOP_FILTER}"](area.searchArea);
  way["shop"="{SHOP_FILTER}"](area.searchArea);
  relation["shop"="{SHOP_FILTER}"](area.searchArea);
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
                print(f"    Overpass HTTP {e.code}, retry {attempt+1} su altro mirror in {wait_s}s...", file=sys.stderr)
                time.sleep(wait_s)
                last_err = e
                continue
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            raise RuntimeError(f"Overpass HTTP {e.code}: {body[:200]}") from e
        except urllib.error.URLError as e:
            if attempt < len(RETRY_BACKOFF_SEC):
                wait_s = RETRY_BACKOFF_SEC[attempt]
                print(f"    Overpass URL error, retry {attempt+1} in {wait_s}s...", file=sys.stderr)
                time.sleep(wait_s)
                last_err = e
                continue
            raise RuntimeError(f"Overpass URL error: {e}") from e
    raise last_err if last_err else RuntimeError("Overpass failed all retries")


# ============================================================
# PARSING
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


def osm_element_to_record(el: dict, city_name: str, provincia: str) -> SupermercatoRecord | None:
    tags = el.get("tags", {}) or {}
    name = (tags.get("name") or "").strip()
    brand = (tags.get("brand") or tags.get("operator") or "").strip()
    # Se manca il nome ma c'è il brand, usa il brand come nome
    if not name:
        name = brand
    if not name:
        return None
    osm_type = el.get("type", "?")[0]
    osm_id = f"{osm_type}{el.get('id')}"
    return SupermercatoRecord(
        osm_id=osm_id,
        citta=city_name,
        provincia=provincia,
        nome_super=name,
        insegna=brand,
        indirizzo=build_address(tags),
        telefono=sanitize_phone(tags.get("phone") or tags.get("contact:phone") or ""),
        email=(tags.get("email") or tags.get("contact:email") or "").strip(),
        sito_web=normalize_url(tags.get("website") or tags.get("contact:website") or ""),
    )


def fetch_city(city_name: str, provincia: str) -> list[SupermercatoRecord]:
    raw = fetch_overpass(build_overpass_query(city_name))
    records: list[SupermercatoRecord] = []
    seen: set[str] = set()
    for el in raw.get("elements", []):
        rec = osm_element_to_record(el, city_name, provincia)
        if rec and rec.osm_id not in seen:
            records.append(rec)
            seen.add(rec.osm_id)
    return records


# ============================================================
# POST AD APPS SCRIPT
# ============================================================

def post_to_apps_script(url: str, secret: str, supermercati: list[dict]) -> dict:
    payload = json.dumps({"secret": secret, "action": "upsert_supermercati", "supermercati": supermercati}).encode("utf-8")
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
    parser = argparse.ArgumentParser(description="Fetch supermercati da Overpass → Google Sheet")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--city", help="Limita a una sola città (test)")
    parser.add_argument("--dataset", choices=["main","extended","all"], default="main",
                        help="main (50 città), extended (93 comuni), all")
    args = parser.parse_args()

    if args.dataset == "extended":
        source_cities = CITIES_EXTENDED
    elif args.dataset == "all":
        source_cities = CITIES_ALL
    else:
        source_cities = CITIES_MAIN

    cities = source_cities
    if args.city:
        cities = [c for c in source_cities if c[0].lower() == args.city.lower()]
        if not cities:
            print(f"Città '{args.city}' non nel dataset '{args.dataset}'", file=sys.stderr)
            sys.exit(2)

    apps_url = os.environ.get("SUPER_APPS_SCRIPT_URL", "")
    apps_secret = os.environ.get("SUPER_APPS_SCRIPT_SECRET", "")
    if not args.dry_run and (not apps_url or not apps_secret):
        print("ERRORE: SUPER_APPS_SCRIPT_URL / SUPER_APPS_SCRIPT_SECRET non impostati", file=sys.stderr)
        sys.exit(2)

    total_records = 0
    grand = {"inserted": 0, "updated": 0, "skipped": 0}
    failed_cities: list[str] = []

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
        print(f"  → {len(records)} supermercati trovati")

        if args.dry_run:
            for r in records[:3]:
                print("    " + json.dumps(r.to_dict(), ensure_ascii=False))
            if len(records) > 3:
                print(f"    ... e altri {len(records)-3}")
        else:
            for batch in batched([r.to_dict() for r in records], BATCH_SIZE_POST):
                try:
                    resp = post_to_apps_script(apps_url, apps_secret, batch)
                    if not resp.get("ok"):
                        print(f"  ERRORE Apps Script: {resp}", file=sys.stderr)
                        failed_cities.append(city)
                        break
                    grand["inserted"] += resp.get("inserted", 0)
                    grand["updated"]  += resp.get("updated", 0)
                    grand["skipped"]  += resp.get("skipped", 0)
                except Exception as e:
                    print(f"  ERRORE POST Apps Script: {e}", file=sys.stderr)
                    failed_cities.append(city)
                    break

        time.sleep(SLEEP_BETWEEN_QUERIES_SEC)

    print("")
    print("=" * 60)
    print(f"COMPLETATO. Supermercati trovati totali: {total_records}")
    if not args.dry_run:
        print(f"  - Inseriti: {grand['inserted']}")
        print(f"  - Aggiornati: {grand['updated']}")
        print(f"  - Skipped: {grand['skipped']}")
    if failed_cities:
        print(f"  Città con errori (timeout/rate-limit Overpass): {', '.join(failed_cities)}")
        # Successo parziale → exit 0. Exit 1 solo se nessun dato.
        if total_records == 0:
            print("  Nessun dato scritto: fallimento totale.")
            sys.exit(1)
        print(f"  OK parziale: {total_records} record nonostante {len(failed_cities)} città in errore.")


if __name__ == "__main__":
    main()
