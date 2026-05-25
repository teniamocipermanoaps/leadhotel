# SOP — Template Email Sponsorship

## Obiettivo
Generare per ogni hotel una bozza email di richiesta sponsorship (donazione camera per volontari Dream Team Clown) che sia:
- **Professionale**: forma "Spett.le", italiano corretto, struttura business-letter.
- **Empatica**: storytelling sui bambini, sulle strutture socio-sanitarie, sul valore umano del progetto.
- **Specifica**: nome hotel, città, date evento, strutture RSA dove i volontari opereranno.
- **Pronta all'invio**: l'utente la copia e la incolla nel suo client mail senza ritocchi (salvo personalizzazioni opzionali).

## Tone of Voice
- Caldo ma formale ("Spett.le", "Vi", "Vostra")
- Mai supplichevole. Mai "Vi prego". Sì "speriamo di poter contare", "sarei felicissima di".
- Centrato sull'altro: l'hotel è invitato a un'esperienza, non solo a pagare.
- Concreto: cifre (200 ore di formazione, 180 strutture, 10 clown), nomi (Patch Adams, Ginevra Sanguigno), luoghi.
- Doppia opzione di sostegno (camera OR donazione IBAN) → riduce la frizione del rifiuto.

## Struttura (fisso)
1. **Oggetto**: `RICHIESTA SPONSORSHIP - TENIAMOCI PER MANO APS "DREAM TEAM CLOWN" {{CITTA_UPPER}}`
2. **Apertura**: `Spett.le {{HOTEL_NOME}},`
3. **Self-intro referente**: nome + ruolo
4. **Hook emotivo**: "vorrei coinvolgervi in un progetto di grande valore sociale"
5. **Chi siamo (APS)**: 1 paragrafo, sito web
6. **Credibilità (Dream Team Clown)**: formazione, Sanguigno, Patch Adams
7. **Dove operiamo**: 180 strutture nazionali
8. **Specifico evento per questa città**: nome città, date, lista strutture
9. **Doppia call-to-action**: camera gratuita OR donazione IBAN (con causale)
10. **Chiusura empowering**: "Una donazione di qualsiasi importo può fare davvero la differenza"
11. **Promessa di follow-up + ringraziamento**
12. **Firma referente**

## Merge Fields canonici
| Token | Origine | Esempio |
|---|---|---|
| `{{HOTEL_NOME}}` | record hotel | "Hotel Centrale" |
| `{{CITTA}}` | record hotel | "Firenze" |
| `{{CITTA_UPPER}}` | derivato (.toUpperCase()) | "FIRENZE" |
| `{{DATA_EVENTO}}` | eventi[citta] | "11-12 Aprile 2026" |
| `{{STRUTTURE_LISTA}}` | eventi[citta] (lista → multi-line) | "RSA Villa Canova\nRSA Guido Raggi\nRSA Villa Giselle" |
| `{{REFERENTE_NOME}}` | eventi[citta] | "Francesca Selcia" |
| `{{REFERENTE_RUOLO}}` | eventi[citta] | "Referente Corporate Fundraising - Event Manager" |
| `{{REFERENTE_CONTATTO}}` | eventi[citta] (opzionale: email/tel) | "francesca@..." |

**Costanti hard-coded nel template** (modificabili in un solo punto del codice):
- `{{APS_NOME}}` = "Teniamoci per Mano APS"
- `{{APS_SITO}}` = "https://www.teniamocipermanoonlus.net"
- `{{IBAN}}` = "IT57H0760103400000006953031"
- `{{CAUSALE}}` = "Donazione a sostegno di Dream Team Clown"

## Regole di validazione
- Se `eventi[citta]` non esiste o `data_evento` è vuoto → **non generare email**, mostra warning + scorciatoia a config.
- Se `strutture` è array vuoto → rendi come "presso le strutture socio-sanitarie convenzionate" (fallback testuale).
- Se `referente_contatto` vuoto → ometti la riga (no `undefined` letterale).

## Personalizzazione futura
Quando l'utente fornirà una versione "ottimizzata" del testo:
1. Aprire `dashboard.html` → cercare la costante `EMAIL_TEMPLATE` nel `<script>`.
2. Sostituire il contenuto preservando i `{{TOKEN}}` esattamente come sopra.
3. Salvare. Niente altro da toccare.

## Lezioni apprese (Self-Annealing)
_(Da popolare quando emergono bug)_
