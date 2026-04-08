from homeassistant.components.sensor import SensorEntity
from homeassistant.util import dt as dt_util
from datetime import datetime, timedelta
import requests
import pdfplumber
import logging
import io

_LOGGER = logging.getLogger(__name__)

# Nomi standard per le portate (usati se l'utente non ne configura altri)
PORTATE_NOMI_DEFAULT = ["primo", "secondo", "contorno", "frutta", "pane"]

# Valori fittizi per il weekend, posizionali
PORTATE_WEEKEND_DEFAULT = [
    "Cucina mamma/papà",
    "Riposo mensa",
    "Niente mensa",
    "Frutta di casa",
    "Pane fresco",
]

# Identificatori univoci per riconoscere ogni giorno nella colonna 0 scritta
# in verticale da pdfplumber. Ogni entry è un set di lettere che, trovate
# tutte insieme nella cella, identificano univocamente quel giorno.
# Derivati dalle stringhe reali del PDF (es. 'Ì\nD\nE\nL\nO\nC\nR\nE\nM' per MER).
#   LUN → U  (unica tra tutti i giorni)
#   MAR → A  (unica tra tutti i giorni)
#   MER → C  (unica tra tutti i giorni, dalla C di merCOledì)
#   GIO → G  (unica tra tutti i giorni)
#   VEN → N+R (nessuna lettera singola è esclusiva, ma N e R insieme sì)
GIORNI_CHIAVE = ["LUN", "MAR", "MER", "GIO", "VEN"]
GIORNI_IDENTIFICATORI = [{"U"}, {"A"}, {"C"}, {"G"}, {"N", "R"}]


# ---------------------------------------------------------------------------
# Parsing helpers — funzioni pure, facili da testare in isolamento
# ---------------------------------------------------------------------------

def _pulisci_cella(cella) -> str:
    """Normalizza una cella: None → stringa vuota, strip degli spazi."""
    if cella is None:
        return ""
    return str(cella).strip()


def _e_riga_giorno(cella_col0: str) -> bool:
    """
    Restituisce True se la cella contiene le lettere identificative di un
    giorno scritto in verticale (es. 'Ì\\nD\\nE\\nN\\nU\\nL' → LUNEDÌ).
    """
    pulita = cella_col0.upper().replace("\n", "").replace("Ì", "").replace(" ", "")
    return any(id_set.issubset(set(pulita)) for id_set in GIORNI_IDENTIFICATORI)


def _e_riga_vuota(riga: list) -> bool:
    """Restituisce True se tutte le celle della riga sono vuote."""
    return not any(riga)


def _pulisci_tabella(raw_table: list) -> list:
    """
    Converte la tabella grezza di pdfplumber in una lista di righe pulite.
    - Converte None in stringa vuota
    - Rimuove solo le righe di intestazione (Ingredienti / SETTIMANA)
    - MANTIENE le righe vuote: sono i separatori naturali tra giorni
    """
    risultato = []
    for riga in raw_table:
        riga_pulita = [_pulisci_cella(c) for c in riga]
        # Salta intestazioni di pagina
        if any("Ingredienti" in c for c in riga_pulita):
            continue
        if any("SETTIMANA" in c.upper() for c in riga_pulita):
            continue
        risultato.append(riga_pulita)
    return risultato


def _trova_indice_giorno(clean_table: list, giorno_index: int) -> int:
    """
    Cerca la riga che corrisponde al giorno richiesto (0=LUN … 4=VEN).
    Usa set di lettere univoche per ogni giorno per evitare falsi positivi.
    Restituisce l'indice della riga, o -1 se non trovata.
    """
    id_set = GIORNI_IDENTIFICATORI[giorno_index]
    for i, riga in enumerate(clean_table):
        if not riga:
            continue
        cella = riga[0].upper().replace("\n", "").replace("Ì", "").replace(" ", "")
        if cella and id_set.issubset(set(cella)):
            _LOGGER.debug(
                "Giorno '%s' (id=%s) trovato alla riga %d: %s",
                GIORNI_CHIAVE[giorno_index], id_set, i, cella
            )
            return i
    return -1


def _rileva_colonna_piatto(clean_table: list, start_index: int, fine_blocco: int) -> int:
    """
    Rileva automaticamente quale colonna contiene i nomi dei piatti,
    analizzando tutte le righe del blocco-giorno (da start_index a fine_blocco).

    La riga start_index è inclusa perché nel PDF di San Benedetto (e in molti
    altri) la prima portata si trova sulla stessa riga del nome del giorno.

    Strategia (applicata per colonna, escludendo colonne sempre vuote):
      1. Scarta la colonna 0: contiene il giorno (scritto in verticale) o è vuota.
      2. Per ogni colonna rimanente calcola il numero medio di virgole per cella
         non vuota: più virgole → più probabile che siano ingredienti.
      3. La colonna con la media di virgole più bassa è quella dei piatti.
      4. In caso di parità (es. due colonne con media 0) sceglie quella con
         indice più basso (la più a sinistra tra le candidate).

    Restituisce l'indice della colonna, con fallback a 1 se il blocco è vuoto.
    """
    righe_blocco = [
        clean_table[i]
        for i in range(start_index, fine_blocco)  # start_index incluso
        if not _e_riga_vuota(clean_table[i])
    ]

    if not righe_blocco:
        return 1  # fallback

    # Determina quante colonne ha la tabella
    n_cols = max(len(r) for r in righe_blocco)

    # Per ogni colonna (esclusa la 0) calcola la media di virgole sulle celle non vuote
    medie_virgole: dict[int, float] = {}
    for col in range(1, n_cols):
        valori = [r[col] for r in righe_blocco if len(r) > col and r[col]]
        if not valori:
            continue  # colonna sempre vuota: la ignoriamo
        media = sum(v.count(",") for v in valori) / len(valori)
        medie_virgole[col] = media
        _LOGGER.debug("Colonna %d: media virgole = %.2f  (campione: %s)", col, media, valori[:2])

    if not medie_virgole:
        return 1  # fallback: nessuna colonna con dati

    # La colonna dei piatti è quella con meno virgole in media
    col_piatto = min(medie_virgole, key=lambda c: (medie_virgole[c], c))
    _LOGGER.debug("Colonna piatto rilevata: %d", col_piatto)
    return col_piatto


def _trova_fine_blocco(clean_table: list, start_index: int, modalita: str, portate_per_giorno: int) -> int:
    """
    Restituisce l'indice esclusivo della fine del blocco-giorno,
    cioè il primo indice che NON appartiene più al giorno corrente.

    La scansione parte da start_index + 1 perché start_index è la riga
    del giorno stesso (che fa parte del blocco ma non è mai un terminatore).
    """
    for i in range(start_index + 1, len(clean_table)):
        riga = clean_table[i]
        vuota = _e_riga_vuota(riga)
        nuovo_giorno = len(riga) > 0 and _e_riga_giorno(riga[0])

        if modalita == "auto":
            if vuota or nuovo_giorno:
                return i
        elif modalita == "riga_vuota":
            if vuota:
                return i
        elif modalita == "nuovo_giorno":
            if nuovo_giorno:
                return i
        elif modalita == "fisso":
            # +1 perché start_index stesso conta come prima portata
            if i >= start_index + portate_per_giorno:
                return i

    return len(clean_table)  # fine tabella


def _estrai_portate_blocco(
    clean_table: list,
    start_index: int,
    modalita: str,
    portate_per_giorno: int = 0,
) -> list:
    """
    Estrae le portate del giorno a partire da start_index + 1,
    fermandosi in base alla modalità scelta:

      'auto'        — si ferma alla prima riga vuota O alla prima riga
                      con un nuovo giorno in col 0. Raccomandata per PDF
                      con giorno scritto in verticale (come il tuo).

      'riga_vuota'  — si ferma solo alla prima riga vuota.

      'nuovo_giorno'— si ferma solo alla prima riga con un nuovo giorno.

      'fisso'       — estrae esattamente portate_per_giorno righe,
                      indipendentemente dai separatori.

    La colonna del piatto viene rilevata automaticamente analizzando
    il blocco intero: è la colonna non vuota con la media di virgole
    più bassa (i nomi dei piatti hanno poche virgole, gli ingredienti molte).

    Restituisce una lista di stringhe (nome piatto per ogni riga del blocco).
    """
    # Prima determiniamo i confini del blocco, poi rileviamo la colonna
    fine_blocco = _trova_fine_blocco(clean_table, start_index, modalita, portate_per_giorno)
    col_valore = _rileva_colonna_piatto(clean_table, start_index, fine_blocco)

    portate = []
    for i in range(start_index, fine_blocco):  # start_index incluso: prima portata è sulla riga del giorno
        riga = clean_table[i]
        if _e_riga_vuota(riga):
            continue
        valore = riga[col_valore] if len(riga) > col_valore else ""
        portate.append(valore)

    _LOGGER.debug("Portate estratte dalla colonna %d (%d totali): %s", col_valore, len(portate), portate)
    return portate


def _abbina_nomi_portate(portate: list, nomi: list) -> dict:
    """
    Abbina i valori estratti ai nomi configurati:
      - portate < nomi → i nomi in eccesso vengono omessi (nessun N/D fuorviante)
      - portate > nomi → le portate extra vanno in portata_N (N 1-based)
    """
    risultato = {}
    for i, valore in enumerate(portate):
        nome = nomi[i] if i < len(nomi) else f"portata_{i + 1}"
        risultato[nome] = valore
    return risultato


# ---------------------------------------------------------------------------
# Setup HA
# ---------------------------------------------------------------------------

async def async_setup_entry(hass, entry, async_add_entities):
    """Configura il sensore dai dati della UI."""
    async_add_entities([SchoolMenuSensor(hass, entry, entry.data)], True)


# ---------------------------------------------------------------------------
# Sensore
# ---------------------------------------------------------------------------

class SchoolMenuSensor(SensorEntity):

    def __init__(self, hass, entry, config):
        self._hass = hass
        self._config = config
        self._attr_name = "Menù Scuola"
        # unique_id da entry_id: permette più istanze (es. due scuole)
        self._attr_unique_id = f"school_menu_{entry.entry_id}"
        self._attr_native_value = "Inizializzazione..."

        # Cache PDF: evita di riscaricarlo ad ogni poll nella stessa giornata
        self._cached_pdf_url = None
        self._cached_pdf_bytes = None
        self._cached_pdf_date = None

        # Stato
        self._portate: dict = {}
        self._n_settimana = None
        self._stagione = None

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _get_portate_nomi(self) -> list:
        """
        Legge i nomi delle portate dalla config.
        Supporta lista (formato salvato dal config flow) e stringa CSV
        (retrocompatibilità con versioni precedenti).
        """
        nomi = self._config.get("portate_nomi", PORTATE_NOMI_DEFAULT)
        if isinstance(nomi, str):
            nomi = [n.strip() for n in nomi.split(",") if n.strip()]
        return nomi if nomi else PORTATE_NOMI_DEFAULT

    def _get_modalita(self) -> str:
        return self._config.get("modalita_blocco", "auto")

    def _get_portate_per_giorno(self) -> int:
        """Usato solo in modalità 'fisso'."""
        return int(self._config.get("portate_per_giorno", 5))

    # ------------------------------------------------------------------
    # Attributi HA
    # ------------------------------------------------------------------

    @property
    def extra_state_attributes(self):
        return {
            "stagione": self._stagione,
            "settimana": self._n_settimana,
            **self._portate,
        }

    # ------------------------------------------------------------------
    # Update — il lavoro pesante (I/O + CPU) gira nel thread pool
    # ------------------------------------------------------------------

    async def async_update(self):
        await self._hass.async_add_executor_job(self._update_sync)

    def _update_sync(self):
        try:
            oggi = dt_util.now()  # rispetta il timezone configurato in Home Assistant
            oggi_date = oggi.date()  # oggetto date puro, senza timezone, per i confronti
            portate_nomi = self._get_portate_nomi()
            modalita = self._get_modalita()

            data_inv = datetime.strptime(self._config["data_inizio_inv"], "%Y-%m-%d").date()
            data_est = datetime.strptime(self._config["data_inizio_est"], "%Y-%m-%d").date()

            # --- Weekend ---
            if oggi.weekday() > 4:
                self._stagione = "Estiva" if oggi_date >= data_est else "Invernale"
                self._attr_native_value = "Si mangia a casa!"
                self._n_settimana = "-"
                self._portate = self._build_portate_weekend(portate_nomi)
                return

            # --- Stagione e URL ---
            if oggi_date >= data_est:
                pdf_url = self._config["pdf_url_est"]
                self._stagione = "Estiva"
                data_rif = data_est - timedelta(days=data_est.weekday())
            else:
                pdf_url = self._config["pdf_url_inv"]
                self._stagione = "Invernale"
                data_rif = data_inv

            # --- Calcolo settimana ---
            settimane_ciclo = int(self._config["settimane_ciclo"])
            giorni_passati = (oggi_date - data_rif).days
            n_settimana = (giorni_passati // 7) % settimane_ciclo
            self._n_settimana = n_settimana + 1

            # --- Cache PDF ---
            if (
                self._cached_pdf_bytes is None
                or self._cached_pdf_url != pdf_url
                or self._cached_pdf_date != oggi_date
            ):
                _LOGGER.debug("Scaricamento PDF da %s", pdf_url)
                response = requests.get(pdf_url, timeout=15)
                response.raise_for_status()
                self._cached_pdf_bytes = response.content
                self._cached_pdf_url = pdf_url
                self._cached_pdf_date = oggi_date
            else:
                _LOGGER.debug("PDF già in cache per oggi (%s)", oggi_date)

            # --- Parsing PDF ---
            with pdfplumber.open(io.BytesIO(self._cached_pdf_bytes)) as pdf:
                page = pdf.pages[n_settimana]
                raw_table = page.extract_table()

            if not raw_table:
                self._attr_native_value = "Tabella non trovata"
                return

            clean_table = _pulisci_tabella(raw_table)
            _LOGGER.debug(
                "Tabella pulita settimana %d: %s", self._n_settimana, clean_table
            )

            # --- Ricerca giorno ---
            start_index = _trova_indice_giorno(clean_table, oggi.weekday())
            if start_index == -1:
                self._attr_native_value = "Giorno non trovato"
                return

            # --- Estrazione portate ---
            portate_valori = _estrai_portate_blocco(
                clean_table,
                start_index,
                modalita=modalita,
                portate_per_giorno=self._get_portate_per_giorno(),
            )

            if not portate_valori:
                self._attr_native_value = "Nessuna portata trovata"
                return

            self._portate = _abbina_nomi_portate(portate_valori, portate_nomi)
            self._attr_native_value = f"{self._stagione} - Sett. {self._n_settimana}"

        except Exception as e:
            _LOGGER.error("Errore aggiornamento school_menu: %s", e, exc_info=True)
            self._attr_native_value = "Errore"

    def _build_portate_weekend(self, portate_nomi: list) -> dict:
        portate = {}
        for i, nome in enumerate(portate_nomi):
            valore = (
                PORTATE_WEEKEND_DEFAULT[i]
                if i < len(PORTATE_WEEKEND_DEFAULT)
                else "Casa"
            )
            portate[nome] = valore
        return portate
