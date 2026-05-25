# Costituzione del Progetto — Agente AI Lead (v2)

> Stato: **FASE A — Architect (v2 — collaborativo + semi-autonomo)**
> Architettura v2 approvata il 2026-05-25.

---

## 1. North Star
**Una dashboard HTML pubblica, condivisa, che mostra in tempo reale lead di hotel italiani (≥ 2 stelle) sulle 50 città target, alimentata in autonomia da uno script che gira ogni settimana, e che permette a Francesca + colleghe di generare bozze email di sponsorship pronte per invio manuale.**

KPI: zero euro/mese di costi infrastrutturali. Setup utente <1h. Dopo la prima settimana, il Google Sheet contiene migliaia di hotel senza intervento umano.

## 2. Integrazioni & Credenziali
- **Google Sheets** (gratis): sorgente verità unica per dati hotel + eventi.
  - 2 tab pubblicati come CSV (URL pubblici read-only).
  - 1 Apps Script Web App deployato come Web App (URL semi-segreto — sta in GitHub Secrets).
- **GitHub Pages** (gratis): hosting della dashboard HTML.
- **GitHub Actions** (gratis, 2000 min/mese sui repo pubblici): cron settimanale per lo script Overpass.
- **OpenStreetMap Overpass API** (gratis, no auth): query hotel per coordinate città.
- **Niente Google Cloud / Places API** (per ora): troppo overhead di setup per APS.
- **`.env`**: solo lato GitHub Actions (Secrets), non lato dashboard.

## 3. Fonte della Verità
- **Google Sheet "Lead Hotel APS"** (creato dall'utente, condiviso col team).
  - Tab `Hotel`: schema canonico (vedi sotto).
  - Tab `Eventi`: schema canonico (vedi sotto).
- **Dashboard**: solo lettura del Sheet. Cache locale `localStorage` per uso offline + velocità.
- **Modifiche dati**: si fanno direttamente nello Sheet (riusato per UX familiare al team).
- **Modifiche programmatiche** (dallo script Overpass): via Apps Script Web App POST endpoint.

## 4. Payload di Consegna
1. **URL dashboard pubblica**: `https://<utente>.github.io/lead-hotel-dream-team/` — apre la dashboard.
2. **Google Sheet condiviso**: link Google con permessi "chiunque con il link può modificare" (interno team).
3. **Email generata**: stesso flusso v1 (modal + copy + mailto), legge eventi dal Sheet.
4. **Cron settimanale**: ogni domenica notte (UTC), GitHub Actions esegue lo script e il Sheet si aggiorna.

## 5. Regole Comportamentali
(invariate da v1)
- Tone of voice email: professionale + empatico + emozionante.
- Mai inviare automaticamente.
- Mai inventare dati hotel — lo script Overpass usa solo dati reali OSM (e li flagga `fonte=osm`).
- Multi-evento: email parametrica per città.
- Privacy: il Sheet contiene dati pubblici (nome/indirizzo/sito) — nessuna PII rilevante.

---

## Schema Dati v2

### Tab Sheet `Hotel` (colonne riga 1)
```
id | citta | provincia | nome_hotel | indirizzo | stelle | telefono | email | sito_web | instagram | facebook | linkedin | altro_social | note | stato | fonte | osm_id | updated_at
```

Nuove colonne v2:
- `fonte`: `osm` | `manuale` | `places` — chi ha inserito la riga.
- `osm_id`: ID OSM (per dedupe negli upsert dello script).
- `updated_at`: ISO timestamp ultimo update.

### Tab Sheet `Eventi` (colonne riga 1)
```
citta | data_evento | strutture | referente_nome | referente_ruolo | referente_contatto
```
Nota: `strutture` è una stringa con strutture separate da `;` (es. `RSA Villa Canova; RSA Villa Giselle`). Più Sheet-friendly del JSON array.

---

## Invarianti Architetturali

- **Sheet è verità.** Dashboard e script Overpass sono entrambi consumer/producer del Sheet.
- **Dashboard solo-lettura.** Aggiornamenti stato lead si fanno nel Sheet (deep link disponibile da dashboard).
- **Script bot è idempotente.** Upsert per `osm_id`. Mai duplicare.
- **Script bot non sovrascrive dati manuali.** Le righe con `fonte != "osm"` sono protette.
- **Hosting zero-cost.** GitHub Pages + GitHub Actions + Google Sheets free.
- **Setup riproducibile.** SETUP.md è l'unica fonte di verità per il deploy.

---

## Trigger di Deployment
- **Manuale**: utente apre URL GitHub Pages.
- **Automatico**: cron GitHub Actions `0 2 * * 0` (ogni domenica alle 2 UTC).
- **On-demand**: utente può triggerare lo script da GitHub UI ("Run workflow").

---

## Log di Manutenzione
_(Self-Annealing: bug → fix → SOP aggiornata)_

### 2026-05-25 — Mismatch conteggio città
- Bug: conteggio 49 vs 50 città nel codice/docs.
- Fix: corretto a 50 ovunque.
- Lezione (in `data_schema.sop.md`): contare il numero di entries dell'array `CITIES` programmaticamente per evitare drift manuale.
