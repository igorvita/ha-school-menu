# 🍽️ School Menu — Custom Component per Home Assistant

Un'integrazione custom per Home Assistant che legge il **menù scolastico giornaliero da un PDF** e lo espone come sensore con attributi, uno per ogni portata.

Sviluppata originariamente per le scuole del Comune di San Benedetto del Tronto (AP), è progettata per adattarsi a diversi formati di PDF scolastici italiani.

---

## 📋 Indice

- [Funzionalità](#-funzionalità)
- [Requisiti](#-requisiti)
- [Installazione](#-installazione)
- [Configurazione](#-configurazione)
- [Il Sensore](#-il-sensore)
- [Compatibilità PDF](#-compatibilità-pdf)
- [Limitazioni note](#-limitazioni-note)
- [Risoluzione dei problemi](#-risoluzione-dei-problemi)
- [Changelog](#-changelog)

---

## ✨ Funzionalità

- 📄 Legge il menù direttamente da un **PDF pubblicato online** (nessun file locale necessario)
- 🔄 Supporta **due menù stagionali** (invernale ed estivo) con cambio automatico alla data configurata
- 📅 Gestisce cicli di **N settimane** (configurabile)
- 🍝 Espone ogni portata come **attributo separato** del sensore, con nomi personalizzabili
- 🔍 **Rilevamento automatico** della colonna dei piatti nel PDF (distingue i nomi dei piatti dagli ingredienti)
- 📐 **Rilevamento automatico** del numero di portate per giorno (gestisce giorni con piatto unico o portate extra)
- 🏠 Gestione weekend con valori placeholder
- ⚡ Aggiornamento **non bloccante** (eseguito nel thread pool di HA)
- 💾 **Cache giornaliera** del PDF per evitare download ripetuti
- 🏫 Supporto **multi-istanza** (es. due scuole diverse)

---

## 📦 Requisiti

- Home Assistant **2023.x** o superiore
- Connessione internet per scaricare il PDF
- Il PDF del menù deve essere **accessibile pubblicamente** tramite URL
- Dipendenze Python (installate automaticamente da HA):
  - `pdfplumber`
  - `requests`

---

## 🔧 Installazione

### Tramite HACS (consigliato)

1. Apri HACS in Home Assistant
2. Vai su **Integrazioni** → menu (⋮) → **Repository personalizzati**
3. Aggiungi l'URL `https://github.com/igorvita/ha-school-menu` con categoria **Integrazione**
4. Cerca "School Menu" in HACS e installala
5. Riavvia Home Assistant

### Manuale

1. Scarica o clona questo repository
2. Copia la cartella `custom_components/school_menu/` nella cartella `custom_components/` della tua installazione di Home Assistant
3. Riavvia Home Assistant

---

## ⚙️ Configurazione

Dopo l'installazione e il riavvio, aggiungi l'integrazione dall'interfaccia di HA:

**Impostazioni → Dispositivi e servizi → Aggiungi integrazione → School Menu**

### Campi del modulo

| Campo | Descrizione | Esempio |
|---|---|---|
| **URL PDF Menù Invernale** | URL diretto al PDF del menù invernale | `https://esempio.comune.it/menu-inverno.pdf` |
| **Data inizio Invernale** | Prima data di validità del menù invernale | `2025-09-15` |
| **URL PDF Menù Estivo** | URL diretto al PDF del menù primaverile/estivo | `https://esempio.comune.it/menu-estate.pdf` |
| **Data inizio Estivo** | Prima data di validità del menù estivo | `2026-04-06` |
| **Numero settimane nel ciclo** | Quante settimane si ripete il ciclo (es. 4 o 6) | `6` |
| **Modalità rilevamento blocco-giorno** | Come il componente identifica la fine di un giorno nel PDF | `auto` |
| **Nomi delle portate** | Nomi personalizzati separati da virgola, nell'ordine in cui appaiono nel PDF | `primo, secondo, contorno, frutta, pane` |
| **Portate per giorno** *(solo modalità fisso)* | Numero fisso di portate, usato solo con modalità `fisso` | `5` |

### Modalità di rilevamento blocco-giorno

Questo parametro determina come il componente capisce dove finisce un giorno e inizia il successivo nella tabella del PDF.

| Modalità | Quando usarla |
|---|---|
| **`auto`** *(consigliata)* | Il blocco termina alla prima riga vuota **oppure** alla prima riga con un nuovo giorno. Funziona per la maggior parte dei PDF italiani. |
| **`riga_vuota`** | Il blocco termina solo alla prima riga vuota. Utile se i giorni non sono etichettati esplicitamente. |
| **`nuovo_giorno`** | Il blocco termina solo quando appare la riga del giorno successivo. Utile se non ci sono righe vuote di separazione. |
| **`fisso`** | Estrae sempre un numero fisso di portate. Usa il campo "Portate per giorno". Utile come fallback per PDF con struttura rigida e non standard. |

### Nomi delle portate

I nomi delle portate vengono usati come chiavi degli attributi del sensore. Inseriscili **nell'ordine in cui appaiono nel PDF**, separati da virgola.

```
primo, secondo, contorno, frutta, pane
```

Se un giorno ha **meno portate** del previsto (es. piatto unico senza secondo), i nomi in eccesso vengono semplicemente omessi — nessun attributo con valore `N/D`.

Se un giorno ha **più portate** del previsto (es. due tipi di frutta), le portate extra vengono esposte come `portata_6`, `portata_7`, ecc.

---

## 📡 Il Sensore

L'integrazione crea un'entità sensore chiamata **`sensor.menu_scuola`**.

### Valore principale (`state`)

Il valore dello stato indica la stagione e la settimana corrente:

```
Estiva - Sett. 2
```

Nei weekend il valore è:
```
Si mangia a casa!
```

In caso di errore:
```
Errore
```

### Attributi

Gli attributi esposti dipendono dai nomi configurati. Con la configurazione di default:

```yaml
stagione: Estiva
settimana: 2
primo: Pasta al pomodoro
secondo: Mozzarella
contorno: Piselli
frutta: Frutta di stagione
pane: Pane semintegrale
```

### Uso in automazioni e card

Puoi usare gli attributi direttamente nei template di HA:

```yaml
{{ state_attr('sensor.menu_scuola', 'primo') }}
{{ state_attr('sensor.menu_scuola', 'secondo') }}
```

Esempio di card Lovelace con template:

```yaml
type: markdown
content: |
  ## 🍽️ Menù di oggi
  🍝 **Primo:** {{ state_attr('sensor.menu_scuola', 'primo') }}
  🥩 **Secondo:** {{ state_attr('sensor.menu_scuola', 'secondo') }}
  🥗 **Contorno:** {{ state_attr('sensor.menu_scuola', 'contorno') }}
  🍎 **Frutta:** {{ state_attr('sensor.menu_scuola', 'frutta') }}
  🍞 **Pane:** {{ state_attr('sensor.menu_scuola', 'pane') }}
```

---

## 📄 Compatibilità PDF

### Formato supportato nativamente

Il componente è stato sviluppato e testato su PDF con questa struttura:

- Il PDF è organizzato con **una pagina per settimana**
- Ogni pagina contiene una **tabella** con (almeno) tre colonne:
  1. **Colonna 0** — nome del giorno, scritto in **verticale** (dal basso verso l'alto)
  2. **Colonna 1** — eventualmente vuota
  3. **Colonna 2** — nome del piatto
  4. **Colonna 3** *(opzionale)* — lista ingredienti
- I giorni sono separati da **righe vuote**

Esempio di struttura (menù delle scuole di San Benedetto del Tronto):

```
| LUNEDÌ (verticale) |   | Pasta al pomodoro          | Pasta di semola, pomodoro... |
|                    |   | Mozzarella                 | Mozzarella                   |
|                    |   | Piselli                    | Piselli, olio evo            |
|                    |   | Frutta di stagione         | Frutta di stagione           |
|                    |   | Pane semintegrale          | Pane semintegrale bio        |
| (riga vuota)       |   |                            |                              |
| MARTEDÌ (vert.)    |   | Passato di verdure         | Verdure miste...             |
| ...                |   | ...                        | ...                          |
```

### Adattamento ad altri formati

Il componente gestisce autonomamente:

- ✅ **Numero variabile di portate** per giorno (rilevamento automatico)
- ✅ **Colonna del piatto variabile** (rilevamento automatico tramite analisi delle virgole)
- ✅ **Piatto unico** — viene estratto nel primo attributo disponibile senza sfasare gli altri
- ✅ **Portate extra** — esposte come `portata_N`

Richiede adattamenti manuali al codice per:

- ⚠️ **Giorno scritto orizzontalmente** — la logica di riconoscimento in `_trova_indice_giorno` usa set di lettere calibrati per testo verticale; con testo orizzontale vanno aggiornati `GIORNI_CHIAVE` e `GIORNI_IDENTIFICATORI`
- ⚠️ **Struttura senza tabella** — se il PDF usa testo libero invece di tabelle, `pdfplumber` non estrarrà righe strutturate e il parsing non funzionerà
- ⚠️ **Più settimane per pagina** — il componente assume una settimana per pagina
- ⚠️ **Intestazioni diverse** — il filtro in `_pulisci_tabella` riconosce "Ingredienti" e "SETTIMANA"; intestazioni diverse andrebbero aggiunte

---

## ⚠️ Limitazioni note

- Il PDF deve essere **pubblicamente accessibile** senza autenticazione
- Il componente scarica il PDF **una volta al giorno** (cache giornaliera); se il comune aggiorna il PDF nel corso della giornata, le modifiche saranno visibili solo il giorno successivo
- Il riconoscimento del giorno è calibrato su PDF con testo verticale in italiano; PDF in altre lingue o con formati molto diversi potrebbero richiedere modifiche al codice

---

## 🔍 Risoluzione dei problemi

### Abilitare il log di debug

Aggiungi in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.school_menu: debug
```

Poi riavvia HA e controlla i log in **Impostazioni → Sistema → Log**.

### Problemi comuni

**`Giorno non trovato`**
Il componente non riesce a identificare il giorno corrente nella tabella del PDF. Possibile causa: struttura del PDF molto diversa da quella attesa. Controlla il log debug per vedere la tabella estratta e come appare la colonna del giorno.

**`Tabella non trovata`**
`pdfplumber` non ha trovato una tabella nella pagina del PDF. Il PDF potrebbe non avere una struttura tabulare riconoscibile, oppure il numero di settimana calcolato è fuori range (controlla la data di inizio e il numero di settimane nel ciclo).

**`Errore` generico**
Controlla i log: verrà riportato il traceback completo dell'eccezione. Le cause più comuni sono URL del PDF non raggiungibile, formato data non valido, o PDF protetto da password.

**Portate sfalsate o errate**
Verifica che i nomi delle portate siano nell'ordine corretto e corrispondano alla struttura del tuo PDF. Abilita il debug per vedere le portate estratte grezze prima dell'abbinamento ai nomi.

**Giorno errato (es. martedì invece di mercoledì)**
Assicurati che il timezone di Home Assistant sia configurato correttamente in **Impostazioni → Sistema → Generali**.

---

## 📝 Changelog

### 2.0.0
- Rilevamento automatico della colonna dei piatti nel PDF
- Rilevamento automatico del numero di portate per giorno (addio `portate_per_giorno` fisso)
- Nomi delle portate completamente configurabili dall'utente
- Aggiunta modalità di rilevamento blocco-giorno (`auto`, `riga_vuota`, `nuovo_giorno`, `fisso`)
- Fix blocco event loop: parsing PDF eseguito nel thread pool (`async_add_executor_job`)
- Fix timezone: uso di `dt_util.now()` per rispettare il timezone configurato in HA
- `unique_id` basato su `entry_id` per supporto multi-istanza
- Cache giornaliera del PDF per evitare download ripetuti
- Validazione date nel config flow
- Aggiunta traduzione italiana e inglese (`translations/it.json`, `translations/en.json`)
- Log di debug al posto di warning per messaggi diagnostici

### 1.7.0
- Versione iniziale pubblica
