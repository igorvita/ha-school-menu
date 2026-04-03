from homeassistant.components.sensor import SensorEntity
from datetime import datetime, timedelta # <-- AGGIUNTO timedelta QUI
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
        self._attr_native_value = "Inizializzazione..." # <-- Sostituito self._state
        
        # Inizializziamo gli attributi piatti
        self._primo = None
        self._secondo = None
        self._contorno = None
        self._frutta = None
        self._pane = None
        self._n_settimana = None
        self._stagione = None

    @property
    def extra_state_attributes(self):
        return {
            "stagione": self._stagione,
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

            # SPOSTATO IN ALTO: Carichiamo le variabili prima di usarle!
            data_inv = datetime.strptime(self._config["data_inizio_inv"], "%Y-%m-%d")
            data_est = datetime.strptime(self._config["data_inizio_est"], "%Y-%m-%d")
            
            # Controllo Weekend
            if oggi.weekday() > 4:
                self._stagione = "Estiva" if oggi >= data_est else "Invernale"
                self._attr_native_value = "Si mangia a casa!"
                self._primo = "Cucina mamma/papà"
                self._secondo = "Riposo mensa"
                self._contorno = "Niente mensa"
                self._frutta = "Frutta di casa"
                self._pane = "Pane fresco"
                self._n_settimana = "-"
                return

            # Logica di switch Stagionale (Se oggi >= data inizio estiva, usa Estivo)
            if oggi >= data_est:
                pdf_url = self._config["pdf_url_est"]
                self._stagione = "Estiva"
                
                # TROVIAMO IL LUNEDÌ DELLA SETTIMANA DEL 1° APRILE
                data_rif = data_est - timedelta(days=data_est.weekday())
            else:
                pdf_url = self._config["pdf_url_inv"]
                data_rif = data_inv
                self._stagione = "Invernale" # <-- CORRETTO (prima era Estiva)

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
                table = page.extract_table()
                
                if not table:
                    self._attr_native_value = "Tabella non trovata"
                    return

                # Pulizia righe
                clean_table = []
                for row in table:
                    clean_row = [str(cell).strip() if cell else "" for cell in row]
                    if any(clean_row) and "Comune" not in clean_row[0] and "Settimana" not in clean_row[0]:
                        clean_table.append(clean_row)

                _LOGGER.warning(f"DEBUG RIGHE PULITE: {clean_table}")

                # --- NUOVA LOGICA DI RICERCA ROBUSTA ---
                # Cerchiamo le lettere chiave dei giorni nella prima colonna
                giorni_chiave = ["LUN", "MAR", "MER", "GIO", "VEN"]
                target_giorno = giorni_chiave[giorno_index]

                start_index = -1
                for i, row in enumerate(clean_table):
                    # Puliamo la cella eliminando i ritorni a capo e la 'Ì'
                    # per rendere la cella una stringa piatta (es: "IDRENEV")
                    cella_pulita = str(row[0]).upper().replace('\n', '').replace('Ì', '').replace(' ', '')
                    
                    # Verifichiamo se le lettere (es. V, E, N) sono presenti nella cella
                    if all(lettera in cella_pulita for lettera in target_giorno):
                        start_index = i
                        _LOGGER.warning(f"GIORNO TROVATO alla riga {i}: {cella_pulita}")
                        break

                if start_index != -1:
                    try:
                        # Estraiamo i piatti dalla colonna 2 (indice 2)
                        # Usiamo min/max o controlli per evitare di andare fuori dai bordi della tabella
                        self._primo = clean_table[start_index][2] if len(clean_table[start_index]) > 2 else "N/D"
                        self._secondo = clean_table[start_index + 1][2] if len(clean_table) > (start_index + 1) else "N/D"
                        self._contorno = clean_table[start_index + 2][2] if len(clean_table) > (start_index + 2) else "N/D"
                        self._frutta = clean_table[start_index + 3][2] if len(clean_table) > (start_index + 3) else "N/D"
                        self._pane = clean_table[start_index + 4][2] if len(clean_table) > (start_index + 4) else "N/D"
                        
                        self._attr_native_value = f"{self._stagione} - Sett. {self._n_settimana}"
                    except Exception as e:
                        _LOGGER.error(f"Errore estrazione piatti: {e}")
                        self._attr_native_value = "Errore Tabella"
                else:
                    self._attr_native_value = "Giorno non trovato"

        except Exception as e:
            _LOGGER.error(f"Errore generale aggiornamento: {e}")
            self._attr_native_value = "Errore"
