/**
 * APPS SCRIPT — Lead Hotel APS · Dream Team Clown
 *
 * Da incollare nell'editor Apps Script del Google Sheet "Lead Hotel APS".
 * Espone un Web App POST endpoint che riceve hotel dallo script Overpass
 * (GitHub Actions) e li fa upsert nella tab "Hotel".
 *
 * SETUP (vedi SETUP.md):
 * 1. Apri il Sheet → Estensioni → Apps Script
 * 2. Incolla questo file in Code.gs
 * 3. Deploy → New deployment → Web app
 *    - Execute as: Me
 *    - Who has access: Anyone (sì, "Anyone" — l'URL fa da chiave)
 * 4. Copia l'URL "/exec" → mettilo nei GitHub Secrets come APPS_SCRIPT_URL
 * 5. Imposta SHARED_SECRET qui sotto + stesso valore in GitHub Secrets come APPS_SCRIPT_SECRET
 */

/* ============================================================
   CONFIGURAZIONE
   ============================================================ */

/** Sostituisci con una stringa random lunga (es. da https://1password.com/password-generator/).
    Mettila identica nei GitHub Secrets come APPS_SCRIPT_SECRET. */
const SHARED_SECRET = "CAMBIA-QUESTA-STRINGA-CON-UNA-RANDOM-LUNGA-32-CHARS";

const SHEET_HOTEL = "Hotel";
const SHEET_EVENTI = "Eventi";

const HEADERS_HOTEL = [
  "id","citta","provincia","nome_hotel","indirizzo","stelle",
  "telefono","email","sito_web","instagram","facebook","linkedin",
  "altro_social","note","stato","fonte","osm_id","updated_at"
];

const HEADERS_EVENTI = [
  "citta","data_evento","strutture","referente_nome","referente_ruolo","referente_contatto"
];

/* ============================================================
   WEB APP ENDPOINTS
   ============================================================ */

function doGet(e) {
  return jsonResponse({ ok: true, message: "Lead Hotel APS — endpoint vivo", timestamp: new Date().toISOString() });
}

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (body.secret !== SHARED_SECRET) {
      return jsonResponse({ ok: false, error: "Unauthorized" }, 401);
    }

    if (body.action === "upsert_hotels") {
      const result = upsertHotels(body.hotels || []);
      return jsonResponse({ ok: true, ...result });
    }

    if (body.action === "health") {
      return jsonResponse({ ok: true, sheet_id: SpreadsheetApp.getActiveSpreadsheet().getId() });
    }

    return jsonResponse({ ok: false, error: "Unknown action: " + body.action }, 400);
  } catch (err) {
    return jsonResponse({ ok: false, error: String(err) }, 500);
  }
}

function jsonResponse(obj, code) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/* ============================================================
   UPSERT LOGIC
   ============================================================ */

/**
 * Upsert idempotente per osm_id.
 * - Se osm_id matcha riga esistente E fonte è "osm": aggiorna i campi
 *   provenienti da OSM (nome, indirizzo, telefono, sito, stelle).
 * - Se osm_id matcha esistente MA fonte è "manuale": NON sovrascrive
 *   i campi inseriti a mano (rispetto edit umano). Aggiorna solo i campi vuoti.
 * - Se osm_id non matcha: append nuova riga.
 *
 * Campi sempre preservati dalle modifiche manuali: email, note, stato.
 */
function upsertHotels(incoming) {
  const sheet = getOrCreateSheet(SHEET_HOTEL, HEADERS_HOTEL);
  const data = sheet.getDataRange().getValues();
  if (data.length === 0) {
    // sheet vuoto — popola header
    sheet.appendRow(HEADERS_HOTEL);
  }

  const header = data[0] || HEADERS_HOTEL;
  const colIdx = {};
  header.forEach((h, i) => { colIdx[h] = i; });

  // Index: osm_id → row number (1-based, riga 2+)
  const osmIndex = {};
  for (let r = 1; r < data.length; r++) {
    const osmId = data[r][colIdx.osm_id];
    if (osmId) osmIndex[String(osmId)] = r + 1; // 1-based sheet row
  }

  let inserted = 0, updated = 0, skipped = 0;
  const now = new Date().toISOString();

  for (const h of incoming) {
    if (!h.osm_id || !h.nome_hotel || !h.citta) { skipped++; continue; }
    const key = String(h.osm_id);

    if (osmIndex[key]) {
      // Update riga esistente
      const rowNum = osmIndex[key];
      const existingRow = sheet.getRange(rowNum, 1, 1, header.length).getValues()[0];
      const existingFonte = existingRow[colIdx.fonte];

      // Campi che lo script OSM può proporre — ma solo se cella vuota o fonte=osm
      const updatable = ["citta","provincia","nome_hotel","indirizzo","stelle","telefono","sito_web"];
      let changed = false;
      for (const f of updatable) {
        const incomingVal = h[f] != null ? String(h[f]) : "";
        const existingVal = existingRow[colIdx[f]] != null ? String(existingRow[colIdx[f]]) : "";
        // Sovrascrive se: fonte=osm (OSM è verità) OPPURE cella vuota
        if (incomingVal && (existingFonte === "osm" || !existingVal)) {
          if (incomingVal !== existingVal) {
            existingRow[colIdx[f]] = incomingVal;
            changed = true;
          }
        }
      }
      if (changed) {
        existingRow[colIdx.updated_at] = now;
        sheet.getRange(rowNum, 1, 1, header.length).setValues([existingRow]);
        updated++;
      } else {
        skipped++;
      }
    } else {
      // Append nuova riga
      const row = HEADERS_HOTEL.map(k => {
        if (k === "updated_at") return now;
        if (k === "fonte") return "osm";
        if (k === "stato") return "da_contattare";
        if (k === "id") return h.id || ("osm-" + h.osm_id);
        return h[k] != null ? h[k] : "";
      });
      sheet.appendRow(row);
      inserted++;
    }
  }

  return { inserted: inserted, updated: updated, skipped: skipped, total_processed: incoming.length };
}

/* ============================================================
   UTIL
   ============================================================ */

function getOrCreateSheet(name, headers) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let s = ss.getSheetByName(name);
  if (!s) {
    s = ss.insertSheet(name);
    s.appendRow(headers);
    s.setFrozenRows(1);
  } else if (s.getLastRow() === 0) {
    s.appendRow(headers);
    s.setFrozenRows(1);
  }
  return s;
}

/**
 * Helper manuale — esegui una volta da editor Apps Script per
 * verificare che lo script ha permessi di scrittura sul Sheet.
 */
function testWrite() {
  const s = getOrCreateSheet(SHEET_HOTEL, HEADERS_HOTEL);
  Logger.log("OK: sheet '" + s.getName() + "' raggiungibile, righe: " + s.getLastRow());
  const e = getOrCreateSheet(SHEET_EVENTI, HEADERS_EVENTI);
  Logger.log("OK: sheet '" + e.getName() + "' raggiungibile, righe: " + e.getLastRow());
}
