import logging
from datetime import datetime
import requests
import pdfplumber
import io
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.event import async_track_time_interval
from datetime import timedelta

_LOGGER = logging.getLogger(__name__)

# Configurazione (in un'integrazione vera questi verrebbero dal file yaml o UI)
URL_INVERNALE = "https://municipium-images-production.s3-eu-west-1.amazonaws.com/s3/6115/allegati/sito-pnrr/documenti-e-dati/001-menu_aut-_inv_2023_2024_sbt_def_.pdf"
URL_ESTIVO = "https://municipium-images-production.s3-eu-west-1.amazonaws.com/s3/6115/allegati/sito-pnrr/documenti-e-dati/006-menu_primavera_estate_2023-24_sbt_def_.pdf"
DATA_INIZIO_CICLO = datetime(2025, 9, 1) # Lunedì Settimana 1

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Setup dell'integrazione via configuration.yaml."""
    sensor = SchoolMenuSensor()
    async_add_entities([sensor], True)

class SchoolMenuSensor(SensorEntity):
    def __init__(self):
        self._attr_name = "Menù Scuola Oggi"
        self._state = "In aggiornamento..."
        self._attr_unique_id = "school_menu_sbt_01"
        # Inizializziamo le variabili per gli attributi
        self._primo = None
        self._secondo = None
        self._contorno = None
        self._frutta = None
        self._pane = None
        self._n_settimana = None

    @property
    def extra_state_attributes(self):
        """Definiamo gli attributi extra del sensore."""
        return {
            "settimana_ciclo": self._n_settimana,
            "primo": self._primo,
            "secondo": self._secondo,
            "contorno": self._contorno,
            "frutta": self._frutta,
            "pane": self._pane
        }

    def update(self):
        """Metodo che scarica il PDF e aggiorna lo stato."""
        try:
            oggi = datetime.now()
            # 0=Lunedì, 4=Venerdì. Se weekend, non c'è menù.
            if oggi.weekday() > 4:
                self._state = "Nessun servizio (Weekend)"
                return

            # --- LOGICA CAMBIO MENÙ AUTOMATICO ---
            # Definiamo il periodo estivo (dal 1 Aprile al 31 Ottobre)
            if 4 <= oggi.month <= 10:
                pdf_url = URL_ESTIVO
                _LOGGER.info("Utilizzo menù ESTIVO")
            else:
                pdf_url = URL_INVERNALE
                _LOGGER.info("Utilizzo menù INVERNALE")
            
            # Calcolo settimana (1-6)
            settimane_trascorse = (oggi - DATA_INIZIO_CICLO).days // 7
            n_settimana = (settimane_trascorse % 6) # 0 to 5 (indice pagina)
            giorno_index = oggi.weekday() # 0=Lun, 1=Mar...

            response = requests.get(pdf_url, timeout=10)
            with pdfplumber.open(io.BytesIO(response.content)) as pdf:
                # Selezioniamo la pagina della settimana corrente
                page = pdf.pages[n_settimana]
                table = page.extract_table()
                
                # Logica di estrazione basata sull'output che mi hai inviato:
                # I giorni sembrano separati da righe vuote o pattern fissi.
                # In base all'output Colab, ogni giorno ha circa 5 righe.
                
                menu_items = []
                # Filtriamo la tabella per prendere solo la colonna dei piatti (indice 2 nell'output Colab)
                all_dishes = [row[2] for row in table if row[2] is not None and row[2] != ""]
                
                # Dividiamo i piatti per giorno (assumendo 4/5 portate per giorno)
                # NOTA: Questa parte va rifinita guardando bene quante righe ha ogni giorno
                # Per ora facciamo uno split logico grezzo:
                dishes_per_day = 5 
                start_idx = giorno_index * dishes_per_day
                oggi_menu = all_dishes[start_idx : start_idx + dishes_per_day]
                
                self._state = " | ".join(oggi_menu)
            
            if len(oggi_menu) >= 5:
                self._primo = oggi_menu[0]
                self._secondo = oggi_menu[1]
                self._contorno = oggi_menu[2]
                self._frutta = oggi_menu[3]
                self._pane = oggi_menu[4]
                self._n_settimana = n_settimana + 1 # +1 perché l'indice parte da 0
                
                # Lo stato principale mostrerà solo il piatto forte (o quello che preferisci)
                self._state = f"{self._primo} e {self._secondo}"
            else:
                self._state = "Dati incompleti nel PDF"

        except Exception as e:
            _LOGGER.error(f"Errore aggiornamento menù: {e}")
            self._state = "Errore lettura PDF"
