from homeassistant.components.sensor import SensorEntity
from datetime import datetime
import requests
import pdfplumber
import logging
import io

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Configura il sensore dai dati della UI."""
    config = entry.data
    async_add_entities([SchoolMenuSensor(config)], True)

class SchoolMenuSensor(SensorEntity):
    def __init__(self, config):
        self._config = config
        self._attr_name = "Menù Scuola"
        self._attr_unique_id = "school_menu_sensor_unique"
        self._state = "Inizializzazione..."
        
        # Inizializziamo gli attributi piatti
        self._primo = None
        self._secondo = None
        self._contorno = None
        self._frutta = None
        self._pane = None
        self._n_settimana = None

    @property
    def extra_state_attributes(self):
        return {
            "settimana": self._n_settimana,
            "primo": self._primo,
            "secondo": self._secondo,
            "contorno": self._contorno,
            "frutta": self._frutta,
            "pane": self._pane
        }

    def update(self):
        try:
            oggi = datetime.now()
            if oggi.weekday() > 4:
                self._state = "Weekend"
                return

            # Carichiamo le variabili dalla configurazione
            data_inv = datetime.strptime(self._config["data_inizio_inv"], "%Y-%m-%d")
            data_est = datetime.strptime(self._config["data_inizio_est"], "%Y-%m-%d")
            
            # Logica di switch Stagionale (Se oggi >= data inizio estiva, usa Estivo)
            if oggi >= data_est:
                pdf_url = self._config["pdf_url_est"]
                data_rif = data_est
                tipo_menu = "Estivo"
            else:
                pdf_url = self._config["pdf_url_inv"]
                data_rif = data_inv
                tipo_menu = "Invernale"

            # Calcolo settimana basato sul numero settimane impostato
            settimane_ciclo = self._config["settimane_ciclo"]
            giorni_passati = (oggi - data_rif).days
            settimane_passate = giorni_passati // 7
            n_settimana = (settimane_passate % settimane_ciclo)
            
            self._n_settimana = n_settimana + 1
            giorno_index = oggi.weekday()

            # Scaricamento e Parsing PDF
            response = requests.get(pdf_url, timeout=15)
            with pdfplumber.open(io.BytesIO(response.content)) as pdf:
                page = pdf.pages[n_settimana]
                text = page.extract_text()
                # Pulizia righe vuote
                all_rows = [r.strip() for r in text.split('\n') if r.strip()]
                
                # Calcoliamo l'offset in base alle portate per giorno
                n_portate = self._config["portate_per_giorno"]
                start_index = giorno_index * n_portate
                menu_del_giorno = all_rows[start_index : start_index + n_portate]

                if len(menu_del_giorno) >= n_portate:
                    self._primo = menu_del_giorno[0]
                    self._secondo = menu_del_giorno[1]
                    self._contorno = menu_del_giorno[2]
                    self._frutta = menu_del_giorno[3] if n_portate > 3 else ""
                    self._pane = menu_del_giorno[4] if n_portate > 4 else ""
                    self._state = f"{tipo_menu} - Sett. {self._n_settimana}"
                else:
                    self._state = "Errore righe PDF"

        except Exception as e:
            _LOGGER.error(f"Errore aggiornamento: {e}")
            self._state = "Errore"
