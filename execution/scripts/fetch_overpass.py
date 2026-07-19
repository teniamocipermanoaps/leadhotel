"""
fetch_overpass.py — Lead Hotel APS · Dream Team Clown

Estrae da OpenStreetMap (Overpass API) tutti gli hotel (tourism=hotel|guest_house|hostel|motel)
nelle 50 città target italiane, filtra per stelle >= 2 dove l'attributo è disponibile,
e invia il batch all'Apps Script Web App del Google Sheet "Lead Hotel APS" per upsert.

Esecuzione locale (dry-run):
    python fetch_overpass.py --dry-run --city Firenze

Esecuzione in GitHub Actions (vedi .github/workflows/fetch-hotels.yml):
    python fetch_overpass.py
    Variabili d'ambiente attese:
      APPS_SCRIPT_URL    — URL /exec del Web App
      APPS_SCRIPT_SECRET — stesso valore di SHARED_SECRET in Code.gs

Limiti accettati:
- Overpass rate-limit: 1 query/città con sleep 2s tra una città e l'altra.
- Email: OSM le ha raramente → la maggioranza arriverà senza email (campo vuoto).
- Stelle: OSM ha il tag `stars` solo per alcune strutture → se mancante, l'hotel
  passa comunque (assumendo "almeno 2 stelle" come baseline).
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

# Forza UTF-8 su stdout/stderr (Windows console di default è cp1252)
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
USER_AGENT = "LeadHotelAPS-DreamTeamClown/1.0 (teniamocipermanoonlus.net)"
SLEEP_BETWEEN_QUERIES_SEC = 5.0      # ↑ era 2.0: ridotto rate-limit HTTP 429
RETRY_BACKOFF_SEC = [5, 15, 45]      # ritentativi su 429/504 (3 tentativi totali)
HTTP_TIMEOUT_SEC = 90                 # ↑ era 60: più tolleranza server lento
BATCH_SIZE_POST = 100  # invio max 100 hotel per POST (Apps Script timeout 30s lato server)

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

# Lista estesa: comuni locali e specifici di interesse APS (~93 voci, esclusi i 3 già presenti
# in CITIES_MAIN: Latina/Siracusa/Cagliari). Include alcune frazioni che potrebbero non avere
# boundary OSM dedicati (Mestre/Zelarino/Chirignago/Cazzago/Xitta/Settignano) → in tal caso
# Overpass restituirà 0 hotel per quelle voci.
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
    # Veneto (include frazioni di Venezia)
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
    # Sardegna (provincia CA tradizionale come da scelta utente)
    ("Sestu","CA"),("Capoterra","CA"),("Quartu Sant'Elena","CA"),("Pula","CA"),
    ("Ussana","CA"),("Selargius","CA"),
    # Toscana (frazione di Firenze)
    ("Settignano","FI"),
]

# Tutto il dataset disponibile per il flag --dataset all
CITIES_ALL = CITIES_MAIN + CITIES_EXTENDED

# Default: dataset main (compat retroattivo)
CITIES = CITIES_MAIN

# Tag OSM considerati "hotel ≥2 stelle" candidati
HOTEL_TOURISM_TAGS = ("hotel", "guest_house", "hostel", "motel")


# ============================================================
# DATA
# ============================================================

@dataclass
class HotelRecord:
    osm_id: str
    citta: str
    provincia: str
    nome_hotel: str
    indirizzo: str
    stelle: int
    telefono: str
    email: str
    sito_web: str

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# OVERPASS QUERY
# ============================================================

def build_overpass_query(city_name: str) -> str:
    """Query: tutti gli hotel/guest_house/hostel/motel dentro il poligono area:'<city>',IT.
    admin_level=8 → comuni; admin_level=9-10 → frazioni/quartieri (Mestre, Settignano, ecc.).
    """
    tags_filter = "|".join(HOTEL_TOURISM_TAGS)
    return f"""
[out:json][timeout:50];
area["name"="{city_name}"]["boundary"="administrative"]["admin_level"~"^(8|9|10)$"]->.searchArea;
(
  node["tourism"~"^({tags_filter})$"](area.searchArea);
  way["tourism"~"^({tags_filter})$"](area.searchArea);
  relation["tourism"~"^({tags_filter})$"](area.searchArea);
);
out tags center;
"""


def fetch_overpass(query: str) -> dict:
    """Esegue query Overpass con retry esponenziale su HTTP 429/504 e fallback su endpoint alternativi.
    - Round-robin tra OVERPASS_ENDPOINTS (3 mirror).
    - Su 429 (rate limit) o 504 (timeout): backoff progressivo (5s, 15s, 45s) e tentativo successivo
      su endpoint diverso.
    - Su altri errori: raise immediato (no retry).
    Totale: fino a len(RETRY_BACKOFF_SEC)+1 = 4 tentativi.
    """
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
                payload = resp.read().decode("utf-8")
                return json.loads(payload)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            last_err = RuntimeError(f"Overpass HTTP {e.code} ({endpoint}): {body[:200]}")
            # Retry solo su 429 (rate limit) o 5xx (server overloaded)
            if e.code in (429, 500, 502, 503, 504) and attempt < len(RETRY_BACKOFF_SEC):
                wait_s = RETRY_BACKOFF_SEC[attempt]
                print(f"    ↳ HTTP {e.code} su {endpoint.split('/')[2]}, retry tra {wait_s}s "
                      f"(tentativo {attempt+2}/{len(RETRY_BACKOFF_SEC)+1})", flush=True)
                time.sleep(wait_s)
                continue
            raise last_err
        except urllib.error.URLError as e:
            last_err = RuntimeError(f"Overpass URL error ({endpoint}): {e}")
            if attempt < len(RETRY_BACKOFF_SEC):
                wait_s = RETRY_BACKOFF_SEC[attempt]
                print(f"    ↳ URL error su {endpoint.split('/')[2]}, retry tra {wait_s}s "
                      f"(tentativo {attempt+2}/{len(RETRY_BACKOFF_SEC)+1})", flush=True)
                time.sleep(wait_s)
                continue
            raise last_err
    # Non dovremmo arrivare qui, ma per sicurezza
    raise last_err if last_err else RuntimeError("Overpass: tutti i tentativi falliti")


# ============================================================
# PARSING / FILTERING
# ============================================================

def stars_int(s: str | None) -> int:
    """OSM 'stars' può essere '3', '3S', '4 stelle', '*', vuoto. Restituisce 0 se non parseable."""
    if not s:
        return 0
    s = str(s).strip()
    # Prova int diretto
    try:
        return int(float(s.split()[0]))
    except (ValueError, IndexError):
        pass
    # Conta '*'
    if "*" in s:
        return s.count("*")
    return 0


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


def sanitize_phone(p: str) -> str:
    """Sanitizza il telefono per evitare #ERROR! in Google Sheets e
    pulire i casi di mis-tag OSM (email nel tag phone).
    - Sheets interpreta valori che iniziano con +/=/-/@ come formule → sostituiamo + con 00.
    - Se il valore contiene @ è probabilmente un'email mis-taggata → scarta.
    - Se non contiene almeno 6 cifre (telefono valido minimo) → scarta.
    Esempi: "+39 06 1234567" -> "0039 06 1234567"
            "info@hotel.it" -> ""  (email mis-taggata, scartata)
            "abc def" -> ""  (no cifre, scartato)
    """
    if not p:
        return ""
    p = p.strip()
    if not p:
        return ""
    # Email mis-taggata nel tag phone (errore comune in OSM)
    if "@" in p:
        return ""
    # Deve contenere almeno 6 cifre per essere un telefono plausibile
    n_digits = sum(1 for c in p if c.isdigit())
    if n_digits < 6:
        return ""
    # Rimuove caratteri formula-like iniziali
    if p[0] in ("+", "=", "-", "@"):
        if p.startswith("+"):
            p = "00" + p[1:]
        else:
            # Per = - @ improbabili nei telefoni: prefissa con spazio per forzare testo
            p = " " + p
    return p


def osm_element_to_record(el: dict, city_name: str, provincia: str, min_stars: int) -> HotelRecord | None:
    tags = el.get("tags", {}) or {}
    name = (tags.get("name") or "").strip()
    if not name:
        return None
    stars = stars_int(tags.get("stars"))
    # Se OSM non ha stelle → accetta comunque (baseline ≥2 assunta).
    # Se OSM HA stelle ed è < min_stars → scarta.
    if stars > 0 and stars < min_stars:
        return None
    osm_type = el.get("type", "?")[0]  # n, w, r
    osm_id = f"{osm_type}{el.get('id')}"
    return HotelRecord(
        osm_id=osm_id,
        citta=city_name,
        provincia=provincia,
        nome_hotel=name,
        indirizzo=build_address(tags),
        stelle=stars if stars > 0 else 2,
        telefono=sanitize_phone(tags.get("phone") or tags.get("contact:phone") or ""),
        email=(tags.get("email") or tags.get("contact:email") or "").strip(),
        sito_web=normalize_url(tags.get("website") or tags.get("contact:website") or "")
    )


def fetch_city(city_name: str, provincia: str, min_stars: int) -> list[HotelRecord]:
    query = build_overpass_query(city_name)
    raw = fetch_overpass(query)
    elements = raw.get("elements", [])
    records: list[HotelRecord] = []
    seen_ids: set[str] = set()
    for el in elements:
        rec = osm_element_to_record(el, city_name, provincia, min_stars)
        if rec and rec.osm_id not in seen_ids:
            records.append(rec)
            seen_ids.add(rec.osm_id)
    return records


# ============================================================
# UPSERT VIA APPS SCRIPT WEB APP
# ============================================================

def post_to_apps_script(url: str, secret: str, hotels: list[dict]) -> dict:
    payload = json.dumps({"secret": secret, "action": "upsert_hotels", "hotels": hotels}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    # Apps Script Web App redirige spesso a googleusercontent.com — urllib gestisce redirect ma
    # per i POST il default non re-invia il body. Usa un opener custom.
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
    parser = argparse.ArgumentParser(description="Fetch hotels from Overpass and upsert to Google Sheet")
    parser.add_argument("--dry-run", action="store_true", help="Non inviare ad Apps Script; stampa JSON a stdout")
    parser.add_argument("--city", help="Limita a una sola città (per test). Es: --city Firenze")
    parser.add_argument("--min-stars", type=int, default=2, help="Soglia stelle minime per inclusione (default: 2)")
    parser.add_argument("--dataset", choices=["main","extended","all"], default="main",
                        help="Quale lista città processare: main (50 originali), extended (~93 nuove), all (entrambe)")
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
            print(f"Città '{args.city}' non in lista", file=sys.stderr)
            sys.exit(2)

    apps_url = os.environ.get("APPS_SCRIPT_URL", "")
    apps_secret = os.environ.get("APPS_SCRIPT_SECRET", "")
    if not args.dry_run and (not apps_url or not apps_secret):
        print("ERRORE: APPS_SCRIPT_URL / APPS_SCRIPT_SECRET non impostati", file=sys.stderr)
        sys.exit(2)

    total_records = 0
    grand_totals = {"inserted": 0, "updated": 0, "skipped": 0}
    failed_cities: list[str] = []        # errori Overpass (tollerabili)
    write_failed_cities: list[str] = []  # errori scrittura Apps Script (gravi)

    for idx, (city, prov) in enumerate(cities):
        print(f"[{idx+1}/{len(cities)}] {city} ({prov}) ...", flush=True)
        try:
            records = fetch_city(city, prov, args.min_stars)
        except Exception as e:
            print(f"  ERRORE Overpass: {e}", file=sys.stderr)
            failed_cities.append(city)
            time.sleep(SLEEP_BETWEEN_QUERIES_SEC)
            continue

        total_records += len(records)
        print(f"  → {len(records)} hotel trovati")

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
    print(f"COMPLETATO. Hotel trovati totali: {total_records}")
    if not args.dry_run:
        print(f"  - Inseriti: {grand_totals['inserted']}")
        print(f"  - Aggiornati: {grand_totals['updated']}")
        print(f"  - Skipped: {grand_totals['skipped']}")
    if failed_cities:
        print(f"  Città con errori Overpass (timeout/rate-limit): {', '.join(failed_cities)}")

    # === ESITO ===
    # Errori di SCRITTURA = sempre gravi (perdita dati) → exit 1.
    if write_failed_cities:
        print(f"  ❌ ERRORE SCRITTURA sul Sheet per: {', '.join(write_failed_cities)}")
        print("     Verifica APPS_SCRIPT_URL / APPS_SCRIPT_SECRET e il deployment Apps Script.")
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
