# SOP — Schema Dati Hotel & Eventi

## Obiettivo
Definire la forma canonica dei record hotel e dei record evento, e le regole di parsing CSV ↔ JSON.

## Schema `Hotel` (JSON)
```json
{
  "id": "uuid v4",
  "citta": "string (uno tra le 50 città del progetto)",
  "provincia": "string sigla a 2 lettere (es. FI)",
  "nome_hotel": "string (obbligatorio)",
  "indirizzo": "string",
  "stelle": "integer 1-5",
  "telefono": "string (formato E.164 raccomandato: +39 ...)",
  "email": "string (validazione email base)",
  "sito_web": "string (URL completo con https://)",
  "instagram": "string (handle o URL)",
  "facebook": "string (handle o URL)",
  "linkedin": "string (handle o URL)",
  "altro_social": "string (TikTok, X, ecc.)",
  "note": "string libero",
  "stato": "enum: da_contattare | contattato | positivo | negativo | no_risposta",
  "createdAt": "ISO 8601",
  "updatedAt": "ISO 8601"
}
```

## Schema `Evento per Città` (JSON)
```json
{
  "<NomeCitta>": {
    "data_evento": "string libero (es. '11-12 Aprile 2026' o '21/04/2026')",
    "strutture": ["array di stringhe (nomi RSA / ospedali)"],
    "referente_nome": "string",
    "referente_ruolo": "string",
    "referente_contatto": "string (email/tel del referente)"
  }
}
```

## Schema CSV (Import/Export)

### Header canonico (riga 1, esatto e case-sensitive)
```
citta,provincia,nome_hotel,indirizzo,stelle,telefono,email,sito_web,instagram,facebook,linkedin,altro_social,note,stato
```

### Regole di parsing
- **Encoding**: UTF-8 (con o senza BOM).
- **Separatore**: virgola `,`. Punto e virgola `;` NON supportato (incompatibilità Excel italiano → istruire utente a "Salva come → CSV UTF-8" e impostare separatore virgola, oppure usare LibreOffice).
- **Quoting**: RFC 4180 minimal. Campo che contiene `,`, `"` o newline deve essere racchiuso tra `"`. Le `"` interne si escapano raddoppiandole (`""`).
- **Campi vuoti**: rappresentati come nulla (`a,,b`). NON usare `null` o `N/A` letterali.
- **Stelle**: integer. Se mancante o non valido → default `2`.
- **Stato**: se mancante → default `da_contattare`. Valori non riconosciuti → `da_contattare`.

### Modalità Import
Quando l'utente importa un CSV, gli si offrono 3 modalità:
1. **Append**: aggiungi nuove righe, mantieni esistenti.
2. **Replace**: cancella tutto e sostituisci.
3. **Merge**: identifica duplicati per `(nome_hotel + citta)` case-insensitive, aggiorna i campi non-vuoti del nuovo, mantieni il resto.

### Validazione post-import
- `nome_hotel` vuoto → riga scartata, contata in report errori.
- `citta` non in lista 50 → riga importata ma flaggata "città fuori-lista" (utente decide se aggiungere alla lista o correggere).
- Telefono/email malformati → importati ma evidenziati in rosso nella cella.

## Lista canonica delle 50 città
(con provincia — duplicati FC ammessi: Forlì + Cesena)
Vedere `findings.md` o costante `CITIES` in `dashboard.html`.

## Lezioni apprese (Self-Annealing)
_(Da popolare quando emergono bug)_
