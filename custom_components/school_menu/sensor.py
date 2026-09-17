from homeassistant.components.sensor import SensorEntity
from homeassistant.util import dt as dt_util
from datetime import datetime, timedelta
import requests
import pdfplumber
import logging
import io

_LOGGER = logging.getLogger(__name__)

PORTATE_NOMI_DEFAULT = ["primo", "secondo", "contorno", "frutta", "pane"]

PORTATE_WEEKEND_DEFAULT = [
    "Cucina mamma/papà",
    "Riposo mensa",
    "Niente mensa",
    "Frutta di casa",
    "Pane fresco",
]

GIORNI_CHIAVE = ["LUN", "MAR", "MER", "GIO", "VEN"]
GIORNI_IDENTIFICATORI = [{"U"}, {"A"}, {"C"}, {"G"}, {"N", "R"}]

# Costanti periodi
PERIODO_FUORI_ANNO = "fuori_anno"
PERIODO_EST_1      = "estivo_1"
PERIODO_INV        = "invernale"
PERIODO_EST_2      = "estivo_2"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _pulisci_cella(cella) -> str:
    if cella is None:
        return ""
    return str(cella).strip()


def _e_riga_giorno(cella_col0: str) -> bool:
    pulita = cella_col0.upper().replace("\n", "").replace("Ì", "").replace(" ", "")
    return any(id_set.issubset(set(pulita)) for id_set in GIORNI_IDENTIFICATORI)


def _e_riga_vuota(riga: list) -> bool:
    return not any(riga)


def _pulisci_tabella(raw_table: list) -> list:
    risultato = []
    for riga in raw_table:
        riga_pulita = [_pulisci_cella(c) for c in riga]
        if any("Ingredienti" in c for c in riga_pulita):
            continue
        if any("SETTIMANA" in c.upper() for c in riga_pulita):
            continue
        risultato.append(riga_pulita)
    return risultato


def _trova_indice_giorno(clean_table: list, giorno_index: int) -> int:
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
    righe_blocco = [
        clean_table[i]
        for i in range(start_index, fine_blocco)
        if not _e_riga_vuota(clean_table[i])
    ]
    if not righe_blocco:
        return 1
    n_cols = max(len(r) for r in righe_blocco)
    medie_virgole: dict = {}
    for col in range(1, n_cols):
        valori = [r[col] for r in righe_blocco if len(r) > col and r[col]]
        if not valori:
            continue
        media = sum(v.count(",") for v in valori) / len(valori)
        medie_virgole[col] = media
        _LOGGER.debug("Colonna %d: media virgole = %.2f  (campione: %s)", col, media, valori[:2])
    if not medie_virgole:
        return 1
    col_piatto = min(medie_virgole, key=lambda c: (medie_virgole[c], c))
    _LOGGER.debug("Colonna piatto rilevata: %d", col_piatto)
    return col_piatto


def _trova_fine_blocco(clean_table: list, start_index: int, modalita: str, portate_per_giorno: int) -> int:
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
            if i >= start_index + portate_per_giorno:
                return i
    return len(clean_table)


def _estrai_portate_blocco(clean_table, start_index, modalita, portate_per_giorno=0):
    fine_blocco = _trova_fine_blocco(clean_table, start_index, modalita, portate_per_giorno)
    col_valore = _rileva_colonna_piatto(clean_table, start_index, fine_blocco)
    portate = []
    for i in range(start_index, fine_blocco):
        riga = clean_table[i]
        if _e_riga_vuota(riga):
            continue
        valore = riga[col_valore] if len(riga) > col_valore else ""
        portate.append(valore)
    _LOGGER.debug("Portate estratte dalla colonna %d (%d totali): %s", col_valore, len(portate), portate)
    return portate


def _abbina_nomi_portate(portate: list, nomi: list) -> dict:
    risultato = {}
    for i, valore in enumerate(portate):
        nome = nomi[i] if i < len(nomi) else f"portata_{i + 1}"
        risultato[nome] = valore
    return risultato


# ---------------------------------------------------------------------------
# Logica periodi scolastici
# ---------------------------------------------------------------------------

def _calcola_offset_continua(data_inizio_periodo: object, data_fine_periodo: object,
                              offset_precedente: int, settimane_ciclo: int) -> int:
    """
    Calcola l'offset di partenza per un periodo che "continua" dal precedente.

    Conta quante settimane intere sono trascorse nel periodo precedente,
    le somma all'offset di quel periodo e restituisce il risultato modulo
    il ciclo — cioè la settimana in cui si sarebbe arrivati se il ciclo
    fosse proseguito senza interruzioni.

    Esempio: periodo precedente durato 7 settimane, partito dall'offset 0
    (settimana 1) con ciclo di 6 → 7 settimane → offset = (0 + 7) % 6 = 1
    → il nuovo periodo parte dalla settimana 2.
    """
    giorni_periodo = (data_fine_periodo - data_inizio_periodo).days
    settimane_periodo = giorni_periodo // 7
    return (offset_precedente + settimane_periodo) % settimane_ciclo


def _determina_periodo(oggi_date, config: dict):
    """
    Determina in quale periodo scolastico ci troviamo e restituisce
    (periodo, pdf_url, data_rif, settimana_offset) dove settimana_offset
    è il numero 0-based della settimana da cui parte il ciclo nel periodo.

    Gestione settimane_inizio:
      - est_1 : sempre un numero fisso (1..N), non può "continuare"
      - inv   : 0 = continua dal termine di est_1; 1..N = fisso
      - est_2 : 0 = continua dal termine di inv;   1..N = fisso
    """
    data_inizio_anno  = datetime.strptime(config["data_inizio_anno"],  "%Y-%m-%d").date()
    data_fine_est_1   = datetime.strptime(config["data_fine_est_1"],   "%Y-%m-%d").date()
    data_inizio_est_2 = datetime.strptime(config["data_inizio_est_2"], "%Y-%m-%d").date()
    data_fine_anno    = datetime.strptime(config["data_fine_anno"],    "%Y-%m-%d").date()

    pdf_url_est = config.get("pdf_url_est", "")
    pdf_url_inv = config.get("pdf_url_inv", "")

    settimane_ciclo        = int(config.get("settimane_ciclo", 6))
    settimana_inizio_est_1 = int(config.get("settimana_inizio_est_1", 1))
    settimana_inizio_inv   = int(config.get("settimana_inizio_inv",   0))
    settimana_inizio_est_2 = int(config.get("settimana_inizio_est_2", 0))

    # Offset 0-based per est_1 (sempre fisso)
    offset_est_1 = settimana_inizio_est_1 - 1
    data_rif_est_1 = data_inizio_anno - timedelta(days=data_inizio_anno.weekday())

    # Offset invernale: fisso o continua da est_1
    if settimana_inizio_inv == 0:
        offset_inv = _calcola_offset_continua(
            data_rif_est_1, data_fine_est_1, offset_est_1, settimane_ciclo
        )
    else:
        offset_inv = settimana_inizio_inv - 1
    data_rif_inv = data_fine_est_1 - timedelta(days=data_fine_est_1.weekday())

    # Offset est_2: fisso o continua da inv
    if settimana_inizio_est_2 == 0:
        offset_est_2 = _calcola_offset_continua(
            data_rif_inv, data_inizio_est_2, offset_inv, settimane_ciclo
        )
    else:
        offset_est_2 = settimana_inizio_est_2 - 1
    data_rif_est_2 = data_inizio_est_2 - timedelta(days=data_inizio_est_2.weekday())

    # Determinazione periodo
    if oggi_date < data_inizio_anno or oggi_date >= data_fine_anno:
        return PERIODO_FUORI_ANNO, None, None, 0

    if oggi_date < data_fine_est_1:
        return PERIODO_EST_1, pdf_url_est, data_rif_est_1, offset_est_1

    if oggi_date < data_inizio_est_2:
        return PERIODO_INV, pdf_url_inv, data_rif_inv, offset_inv

    return PERIODO_EST_2, pdf_url_est, data_rif_est_2, offset_est_2


# ---------------------------------------------------------------------------
# Setup HA
# ---------------------------------------------------------------------------

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([SchoolMenuSensor(hass, entry, entry.data)], True)


# ---------------------------------------------------------------------------
# Sensore
# ---------------------------------------------------------------------------

class SchoolMenuSensor(SensorEntity):

    def __init__(self, hass, entry, config):
        self._hass = hass
        self._config = config
        self._attr_name = "Menù Scuola"
        self._attr_unique_id = f"school_menu_{entry.entry_id}"
        self._attr_native_value = "Inizializzazione..."
        self._cached_pdf_url = None
        self._cached_pdf_bytes = None
        self._cached_pdf_date = None
        self._portate: dict = {}
        self._n_settimana = None
        self._stagione = None

    def _get_portate_nomi(self) -> list:
        nomi = self._config.get("portate_nomi", PORTATE_NOMI_DEFAULT)
        if isinstance(nomi, str):
            nomi = [n.strip() for n in nomi.split(",") if n.strip()]
        return nomi if nomi else PORTATE_NOMI_DEFAULT

    def _get_modalita(self) -> str:
        return self._config.get("modalita_blocco", "auto")

    def _get_portate_per_giorno(self) -> int:
        return int(self._config.get("portate_per_giorno", 5))

    @property
    def extra_state_attributes(self):
        return {
            "stagione": self._stagione,
            "settimana": self._n_settimana,
            **self._portate,
        }

    async def async_update(self):
        await self._hass.async_add_executor_job(self._update_sync)

    def _update_sync(self):
        try:
            oggi = dt_util.now()
            oggi_date = oggi.date()
            portate_nomi = self._get_portate_nomi()
            modalita = self._get_modalita()

            periodo, pdf_url, data_rif, settimana_offset = _determina_periodo(
                oggi_date, self._config
            )

            # --- Fuori anno o weekend ---
            if periodo == PERIODO_FUORI_ANNO or oggi.weekday() > 4:
                if periodo == PERIODO_FUORI_ANNO:
                    self._stagione = "Fuori anno"
                elif periodo in (PERIODO_EST_1, PERIODO_EST_2):
                    self._stagione = "Estiva"
                else:
                    self._stagione = "Invernale"
                self._attr_native_value = "Si mangia a casa!"
                self._n_settimana = "-"
                self._portate = self._build_portate_weekend(portate_nomi)
                return

            # --- Stagione ---
            stagioni = {
                PERIODO_EST_1: "Estiva (periodo 1)",
                PERIODO_INV:   "Invernale",
                PERIODO_EST_2: "Estiva (periodo 2)",
            }
            self._stagione = stagioni[periodo]

            # --- Calcolo settimana ---
            settimane_ciclo = int(self._config["settimane_ciclo"])
            giorni_passati = (oggi_date - data_rif).days
            n_settimana = (settimana_offset + giorni_passati // 7) % settimane_ciclo
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
            _LOGGER.debug("Tabella pulita settimana %d: %s", self._n_settimana, clean_table)

            start_index = _trova_indice_giorno(clean_table, oggi.weekday())
            if start_index == -1:
                self._attr_native_value = "Giorno non trovato"
                return

            portate_valori = _estrai_portate_blocco(
                clean_table, start_index,
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
