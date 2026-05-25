# 🚀 SETUP — Lead Hotel APS · Dream Team Clown

Guida passo-passo per attivare la dashboard condivisa con ricerca automatica degli hotel.

**Tempo richiesto**: ~45 minuti la prima volta. Dopo non tocchi più nulla.

**Prerequisiti**:
- Un account Google (anche personale va bene)
- Un account GitHub gratuito (te ne creiamo uno se non ce l'hai)
- Il browser Chrome o Firefox

---

## 🗂 Cosa stai per creare

```
1. Un Google Sheet condiviso col team APS (i dati vivono qui)
2. Un account/repo GitHub (per ospitare gratis dashboard + script)
3. Una dashboard online con un link che condividi alle colleghe
4. Un robottino che ogni domenica notte aggiorna il Sheet con hotel nuovi
```

Quando hai finito, **costo mensile = 0 €**.

---

## PARTE 1 — Google Sheet (~10 min)

### 1.1 Crea il Sheet
1. Vai su [sheets.google.com](https://sheets.google.com) → **+ Vuoto**
2. Rinominalo **"Lead Hotel APS - Dream Team Clown"**
3. In basso vedi la tab `Foglio1`. Rinominala in **`Hotel`** (doppio click sul nome)
4. Clicca **+** in basso per creare una nuova tab. Rinominala **`Eventi`**

### 1.2 Importa i template
1. Apri il file `execution/sheet_template/Hotel.csv` che hai sul PC
2. Nella tab `Hotel`: **File → Importa → Carica → seleziona Hotel.csv**
3. Importa la posizione: **"Sostituisci il foglio corrente"**, separatore: **"Virgola"**
4. Ripeti per `Eventi.csv` nella tab `Eventi`

✅ **Check**: nella tab Hotel vedi 1 riga (Hotel del Sole DEMO). Nella tab Eventi vedi 1 riga (Firenze).

### 1.3 Pubblica le 2 tab come CSV
1. **File → Condividi → Pubblica sul web**
2. Nella finestra:
   - Selettore di sinistra: scegli tab **`Hotel`**
   - Selettore di destra: scegli **`Valori separati da virgole (.csv)`**
3. Clicca **Pubblica** → **OK**
4. **COPIA L'URL** che ti dà → incollalo da qualche parte temporanea (Note, file di testo) con etichetta `HOTEL_CSV_URL`
5. Senza chiudere la finestra: cambia il selettore di sinistra in **`Eventi`** → **Pubblica** → copia l'URL come `EVENTI_CSV_URL`
6. Chiudi la finestra

### 1.4 Copia anche l'URL "normale" del Sheet
- Dalla barra indirizzi del browser, copia l'URL del Sheet (quello che inizia con `https://docs.google.com/spreadsheets/d/.../edit`)
- Salvalo come `SHEET_EDIT_URL`

### 1.5 Condividi col team
- Clicca **🔒 Condividi** (in alto a destra del Sheet)
- Aggiungi le email delle colleghe come **Editor**
- Salva

✅ **Check**: hai 3 URL salvati (HOTEL_CSV_URL, EVENTI_CSV_URL, SHEET_EDIT_URL) e il team ha accesso al Sheet.

---

## PARTE 2 — Apps Script (lo "scrittore" del Sheet) (~10 min)

Lo script che gira ogni settimana ha bisogno di un endpoint per scrivere nel Sheet. Quell'endpoint vive nel Sheet stesso, come "Apps Script".

### 2.1 Apri l'editor Apps Script
1. Nel Sheet: **Estensioni → Apps Script**
2. Si apre una nuova scheda con un editor di codice. Vedi un file `Code.gs` con un `function myFunction() {}` di default
3. **Cancella tutto il contenuto** di Code.gs

### 2.2 Incolla il nostro codice
1. Apri `execution/apps_script/Code.gs` dal PC con un editor di testo (Notepad va bene)
2. **Copia tutto il contenuto** e incollalo nell'editor Apps Script vuoto

### 2.3 Imposta la "chiave segreta"
1. In cima al file, cerca la riga:
   ```js
   const SHARED_SECRET = "CAMBIA-QUESTA-STRINGA-CON-UNA-RANDOM-LUNGA-32-CHARS";
   ```
2. Vai su [1password.com/password-generator](https://1password.com/password-generator/), genera una password lunga 32 caratteri (senza simboli strani, solo lettere+numeri)
3. Sostituisci la stringa segnaposto con la password generata. **Salvala anche da parte** come `APPS_SCRIPT_SECRET` — ci servirà tra poco
4. Salva (icona 💾 o `Ctrl+S`). Il file si chiama "Senza titolo" → rinominalo "Lead Hotel APS"

### 2.4 Test rapido
1. Nel menu in alto dell'editor: scegli funzione **`testWrite`** → clicca **▶ Esegui**
2. Google ti chiederà i permessi → **Rivedi le autorizzazioni → scegli il tuo account → Avanzate → "Vai a Lead Hotel APS (non sicuro)" → Consenti**
   (è la procedura standard per script personali; il Sheet rimane tuo)
3. Vedrai nell'esito: `OK: sheet 'Hotel' raggiungibile, righe: 2` → tutto a posto

### 2.5 Deploy come Web App
1. In alto a destra: **Deploy → New deployment**
2. Clicca l'ingranaggio ⚙ accanto a "Select type" → **Web app**
3. Compila:
   - **Description**: `Endpoint scrittura hotel`
   - **Execute as**: `Me (tua email)`
   - **Who has access**: **`Anyone`** ⚠️ Sì, "Anyone" — la nostra password segreta protegge l'endpoint
4. **Deploy** → autorizza di nuovo se richiesto
5. **COPIA L'URL** che termina con `/exec` → salvalo come `APPS_SCRIPT_URL`

✅ **Check**: hai salvato `APPS_SCRIPT_URL` (URL del Web App) e `APPS_SCRIPT_SECRET` (la password).

---

## PARTE 3 — GitHub (hosting dashboard + cron automatico) (~15 min)

### 3.1 Crea account (se non ne hai uno)
1. Vai su [github.com/signup](https://github.com/signup)
2. Email APS o personale, username (es. `francesca-aps`), password
3. Conferma email

### 3.2 Crea il repository
1. In alto a destra dopo il login: **+ → New repository**
2. Compila:
   - **Repository name**: `lead-hotel-dream-team`
   - **Description**: `Dashboard lead hotel sponsorship per Dream Team Clown`
   - **Public** ← obbligatorio per usare GitHub Pages gratis
   - ✅ **Add a README file**
3. **Create repository**

### 3.3 Carica i file del progetto
Devi caricare l'intera cartella locale (eccetto `memory/` e `.tmp/` che sono interni).

1. Nel repo appena creato: clicca **Add file → Upload files**
2. **Trascina** le seguenti cartelle/file dal tuo PC (cartella `Agente AI Lead`):
   - `execution/` (la cartella intera)
   - `.github/` (la cartella intera con dentro `workflows/fetch-hotels.yml`)
   - `architecture/` (utile per riferimento)
   - `CLAUDE.md`
   - `SETUP.md` (questo file)
3. **Scroll giù → Commit changes** (lascia il messaggio default)

✅ **Check**: nel repo vedi le cartelle caricate. Apri `.github/workflows/fetch-hotels.yml` → c'è.

### 3.4 Aggiungi i segreti
1. Nel repo: **Settings** (in alto) → **Secrets and variables → Actions** (menu sinistro)
2. **New repository secret** → nome: `APPS_SCRIPT_URL`, valore: l'URL salvato in 2.5 → **Add secret**
3. **New repository secret** → nome: `APPS_SCRIPT_SECRET`, valore: la password salvata in 2.3 → **Add secret**

✅ **Check**: vedi 2 secrets nella lista.

### 3.5 Attiva GitHub Pages
1. **Settings → Pages** (menu sinistro)
2. Sotto **Source**: scegli **Deploy from a branch**
3. **Branch**: `main`, **Folder**: `/execution` → **Save**
4. Attendi 1-2 minuti. Ricarica la pagina. In alto vedrai un riquadro con l'URL della tua dashboard pubblica, tipo:
   ```
   https://francesca-aps.github.io/lead-hotel-dream-team/
   ```
5. **Copia e salva questo URL** — è il link che darai alle colleghe!

✅ **Check**: aprendo quell'URL vedi la dashboard (ti reindirizzerà su `dashboard.html`).

### 3.6 Configura la dashboard
1. Apri l'URL della tua dashboard
2. Clicca **⚙ Sorgente dati**
3. Incolla:
   - **URL CSV tab Hotel**: `HOTEL_CSV_URL` (dal 1.3)
   - **URL CSV tab Eventi**: `EVENTI_CSV_URL` (dal 1.3)
   - **URL Sheet**: `SHEET_EDIT_URL` (dal 1.4)
4. **Salva e Sync** → dovresti vedere "✓ sincronizzato ora" e l'hotel demo che hai messo nel Sheet

✅ **Check**: la dashboard mostra i dati del Sheet. Il badge dice "sincronizzato ora".

---

## PARTE 4 — Prima esecuzione del bot Overpass (~5 min)

### 4.1 Trigger manuale
1. Nel repo GitHub: **Actions** (menu in alto)
2. A sinistra: clicca **Fetch Hotels (OSM → Google Sheet)**
3. A destra in alto: **Run workflow ▾** → lascia i campi vuoti → **Run workflow**
4. La pagina ricarica e vedi una run in corso (icona gialla 🟡)

### 4.2 Attendi (~5 minuti)
- Lo script processa 50 città, con 2 secondi di pausa tra una e l'altra → ~3-4 minuti
- Quando finisce: icona ✅ verde

### 4.3 Verifica
1. Apri il Google Sheet → tab `Hotel`: dovresti vedere **migliaia di righe nuove** (OSM ha molti dati)
2. Apri la dashboard → clicca **🔄 Sync ora** → vedi tutti i nuovi hotel suddivisi per città
3. La maggior parte avranno nome+indirizzo, alcuni anche email/telefono

✅ **Check**: la dashboard mostra ~migliaia di hotel reali da OSM, ognuno con `fonte=osm` nel Sheet.

---

## 🎉 Sei online!

D'ora in poi:
- **Settimanale automatico**: ogni domenica notte UTC, il bot aggiorna il Sheet con hotel nuovi/modificati su OSM (senza toccare quelli che tu/le colleghe avete modificato manualmente)
- **Le colleghe** aprono il link dashboard e vedono dati live
- **Modifiche al Sheet** (es. aggiungere email, cambiare stato lead, aggiungere note) → si vedono nella dashboard al prossimo Sync (basta cliccare 🔄 Sync ora)
- **Generazione email**: clic su `✉️ Email` → modal → `Copia testo` → incolla nel client mail

---

## 🛠 Operazioni comuni dopo il setup

### Configurare un nuovo evento per una città
1. Apri il Sheet → tab `Eventi`
2. Aggiungi una riga: `citta, data_evento, strutture` (strutture separate da `;`), `referente_nome, referente_ruolo, referente_contatto`
3. Nella dashboard: **🔄 Sync** → ora gli hotel di quella città possono generare email complete

### Aggiornare lo stato di un lead dopo il contatto
1. Apri il Sheet → tab `Hotel` → cerca l'hotel → cambia colonna `stato` (`contattato`, `positivo`, ecc.)
2. Nella dashboard: **🔄 Sync** → stato aggiornato per tutti

### Triggerare il bot fuori cron (es. dopo nuove zone aggiunte)
- GitHub → Actions → Fetch Hotels → Run workflow

### Cambiare il template email
- Apri `execution/dashboard.html` nel repo GitHub (clicca → matita ✏ per editare online)
- Cerca `EMAIL_TEMPLATE` (Ctrl+F)
- Modifica il testo (mantieni i `{{TOKEN}}` come sono)
- Commit changes → GitHub Pages si re-deploya in ~1 min

---

## ❓ Problemi frequenti

**Dashboard non si carica**: assicurati che GitHub Pages sia attivo (Settings → Pages mostra "Your site is live at...")

**Sync fallisce**: controlla che gli URL CSV nel modal config siano quelli pubblicati (terminano con `output=csv`, non con `/edit`)

**Workflow Actions fallisce con 401**: la `APPS_SCRIPT_SECRET` nei secrets GitHub non corrisponde a quella in `Code.gs` del Apps Script

**Workflow Actions fallisce con 403/404**: l'`APPS_SCRIPT_URL` non punta al deploy giusto. Vai in Apps Script → Deploy → Manage deployments → copia di nuovo l'URL `/exec`

**Le colleghe non vedono dati nuovi**: ricordagli di cliccare 🔄 Sync ora (la dashboard non si auto-aggiorna nel browser)

---

## Riassunto delle credenziali da non perdere

| Cosa | Dove conservarla |
|---|---|
| `HOTEL_CSV_URL` | nei segreti del config dashboard |
| `EVENTI_CSV_URL` | nei segreti del config dashboard |
| `SHEET_EDIT_URL` | nei segreti del config dashboard |
| `APPS_SCRIPT_URL` | GitHub repo → Secrets |
| `APPS_SCRIPT_SECRET` | GitHub repo → Secrets + dentro `Code.gs` del Apps Script |
| URL dashboard pubblica | da condividere con le colleghe |

Tieni tutto in un password manager (Bitwarden gratis, ad esempio).

---

## Costi mensili

| Servizio | Costo |
|---|---|
| Google Sheets | 0 € |
| GitHub Pages | 0 € |
| GitHub Actions (~5 min/settimana) | 0 € (limite gratis 2000 min/mese) |
| Apps Script | 0 € |
| OpenStreetMap | 0 € |
| **TOTALE** | **0 €/mese** |
