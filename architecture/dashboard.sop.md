# SOP — Dashboard `dashboard.html`

## Obiettivo
Consentire alla referente APS di visualizzare, filtrare, aggiornare e arricchire un elenco di hotel italiani (≥2 stelle) suddivisi per Comune, e generare per ognuno una bozza email di sponsorship pronta per invio manuale.

## Input
- File CSV (UTF-8, header canonico — vedi `data_schema.sop.md`) importato dall'utente.
- Inserimento manuale tramite modal "Aggiungi hotel".
- Edit inline su righe esistenti.

## Output
- Tabella organizzata per Comune (50 sezioni preconfigurate, anche se vuote).
- Email generata in modal (oggetto + corpo), con bottoni "Copia oggetto", "Copia testo", "Apri in client mail" (mailto:).
- Export CSV scaricabile.

## Componenti UI

### Header (sticky in alto)
- Titolo brand "Dream Team Clown · Lead Hotel"
- Sottotitolo "Teniamoci per Mano APS"
- Campo `search` (filtra per nome hotel, indirizzo, email — substring case-insensitive)
- Dropdown `città` (default: "Tutte le città" + lista delle 50 città in ordine alfabetico)
- Dropdown `stato lead` (`Tutti / Da contattare / Contattato / Risposto: sì / Risposto: no / Nessuna risposta`)
- Dropdown `stelle minime` (≥2, ≥3, ≥4)

### Stats bar
4 contatori live: hotel totali · città con almeno 1 hotel · hotel contattati · risposte positive.

### Toolbar
- `+ Aggiungi hotel` (apre modal hotel)
- `Importa CSV` (file picker, accetta `.csv` `.json`)
- `Esporta CSV` (download dello stato corrente)
- `Imposta eventi per città` (apre modal eventi → date/strutture/referente per ogni città)
- `Svuota dati locali` (richiede conferma esplicita)

### Lista città (main area)
- Sezione collapsibile per ogni città (chiusa di default se 0 hotel, aperta se >0).
- Header sezione: nome città (es. "Firenze (FI)") + counter `n hotel` + bottoncino `+ aggiungi qui`.
- Tabella con colonne: Nome, Indirizzo, ⭐, Telefono, Email, Sito, Social, Stato, Azioni.
- Su mobile (<768px) la tabella collassa in card verticali.

### Modal "Genera Email"
- Mostra il testo finale già renderizzato (oggetto + corpo) con i merge fields sostituiti.
- Se manca la config eventi per la città, mostra warning: "Configura prima i dati evento per [Città] →" con bottone scorciatoia.
- 3 azioni: `Copia oggetto`, `Copia testo`, `Apri in mail client` (mailto con oggetto + body pre-compilati).

### Modal "Aggiungi/Modifica Hotel"
- Form con tutti i campi dello schema. Campi obbligatori: `nome_hotel`, `citta`. Stelle: select 1-5.

### Modal "Eventi per Città"
- Una card per ognuna delle 50 città con form: `data_evento`, `strutture` (lista, virgola-separata), `referente_nome`, `referente_ruolo`, `referente_contatto`.
- Cambiamenti salvati in `localStorage.tpm_eventi_v1`.

## Regole comportamentali

1. **Filtro additivo**: città AND stato AND stelle AND ricerca testo. Risultati vuoti → mostra messaggio "Nessun hotel corrisponde ai filtri".
2. **Persistenza automatica**: ogni modifica triggera `save()` su localStorage. Niente bottone "Salva".
3. **Email non generabile se mancano dati evento**: il modal email mostra warning + scorciatoia a config eventi invece di generare email con `{{DATA_EVENTO}}` letterale.
4. **Mai sovrascrivere senza chiedere**: import CSV propone tre modalità (Append, Replace, Merge by name+città). Default: Append.
5. **CSV in/out simmetrico**: lo stesso file esportato deve essere reimportabile senza perdita.

## Edge Cases gestiti
- **Encoding non-UTF8 all'import** → tenta UTF-8, se rileva mojibake (`Ã©`, `Ã`) mostra warning suggerendo "Salva come CSV UTF-8 in Excel".
- **CSV con campo virgolettato contenente virgola/quote** → parser implementa RFC 4180 minimal (gestione `""` come escape per `"`).
- **Caratteri non-ASCII negli ID** → uso `crypto.randomUUID()`.
- **Mailto con body lungo** → la maggior parte dei client supporta ~2000 caratteri. Per body più lunghi, mostro warning e raccomando "Copia testo" + incolla manuale.
- **Cancellazione accidentale** → toolbar `Svuota dati` richiede conferma con typing "ELIMINA".

## Verifica
1. Aprire `dashboard.html` in browser.
2. Click `Importa CSV` → caricare `execution/import_template.csv`. La tabella mostra 2 righe esempio.
3. Click `Imposta eventi per città` → compilare Firenze con date e RSA dell'esempio.
4. Click `Genera Email` su una riga di Firenze → modal mostra email completa, identica all'esempio fornito (con i merge fields sostituiti).
5. Click `Copia testo` → testo nel clipboard.
6. Click `Esporta CSV` → file scaricato. Reimportarlo (modalità Replace) → stato identico.

## Lezioni apprese (Self-Annealing)
_(Da popolare quando emergono bug)_
