import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from datetime import datetime

DOMAIN = "school_menu"

PORTATE_DEFAULT = "primo, secondo, contorno, frutta, pane"
MODALITA_BLOCCO_OPTIONS = ["auto", "riga_vuota", "nuovo_giorno", "fisso"]


def _valida_input(user_input: dict) -> dict:
    """
    Valida i campi del form.
    Restituisce un dizionario di errori (vuoto = tutto ok).
    """
    errors = {}

    # Le date vengono già validate dal DateSelector di HA,
    # ma verifichiamo l'ordine cronologico
    date_fields = [
        "data_inizio_anno",
        "data_fine_est_1",
        "data_inizio_est_2",
        "data_fine_anno",
    ]

    try:
        dates = {
            f: datetime.strptime(user_input[f], "%Y-%m-%d").date()
            for f in date_fields
        }
        if not (
            dates["data_inizio_anno"]
            < dates["data_fine_est_1"]
            < dates["data_inizio_est_2"]
            < dates["data_fine_anno"]
        ):
            errors["data_inizio_anno"] = "date_order_invalid"
    except (ValueError, KeyError):
        errors["data_inizio_anno"] = "invalid_date"

    # Validazione settimane di partenza:
    # 0 = continua dal periodo precedente (non valido per est_1 che è sempre fisso)
    # 1..settimane_ciclo = settimana fissa
    settimane_ciclo = user_input.get("settimane_ciclo", 6)

    val_est_1 = user_input.get("settimana_inizio_est_1", 1)
    if not (1 <= val_est_1 <= settimane_ciclo):
        errors["settimana_inizio_est_1"] = "settimana_fuori_range"

    for field in ("settimana_inizio_inv", "settimana_inizio_est_2"):
        val = user_input.get(field, 1)
        if not (0 <= val <= settimane_ciclo):
            errors[field] = "settimana_fuori_range"

    # Validazione coerenza nomi portate / portate_per_giorno
    if user_input.get("modalita_blocco") == "fisso":
        nomi = [
            n.strip()
            for n in user_input.get("portate_nomi", "").split(",")
            if n.strip()
        ]
        portate_per_giorno = user_input.get("portate_per_giorno", 5)
        if len(nomi) != portate_per_giorno:
            errors["portate_nomi"] = "portate_nomi_mismatch"

    return errors


def _normalizza_input(user_input: dict) -> dict:
    """Normalizza portate_nomi da stringa CSV a lista pulita."""
    result = dict(user_input)
    if isinstance(result.get("portate_nomi"), str):
        result["portate_nomi"] = [
            n.strip()
            for n in result["portate_nomi"].split(",")
            if n.strip()
        ]
    return result


def _build_schema(defaults: dict) -> vol.Schema:
    """
    Costruisce lo schema del form usando i valori di default forniti.
    Usato sia dal config flow iniziale che dall'options flow.
    """
    portate_nomi = defaults.get("portate_nomi", PORTATE_DEFAULT)
    if isinstance(portate_nomi, list):
        portate_nomi = ", ".join(portate_nomi)

    return vol.Schema({
        # --- URL dei PDF ---
        vol.Required("pdf_url_est",
                     default=defaults.get("pdf_url_est", "")): str,
        vol.Required("pdf_url_inv",
                     default=defaults.get("pdf_url_inv", "")): str,

        # --- Date anno scolastico (DateSelector: mostra calendar picker in HA) ---
        vol.Required("data_inizio_anno",
                     default=defaults.get("data_inizio_anno", "")): selector.selector({"date": {}}),
        vol.Required("data_fine_est_1",
                     default=defaults.get("data_fine_est_1", "")): selector.selector({"date": {}}),
        vol.Required("data_inizio_est_2",
                     default=defaults.get("data_inizio_est_2", "")): selector.selector({"date": {}}),
        vol.Required("data_fine_anno",
                     default=defaults.get("data_fine_anno", "")): selector.selector({"date": {}}),

        # --- Ciclo settimane ---
        vol.Required("settimane_ciclo",
                     default=defaults.get("settimane_ciclo", 6)): int,

        # --- Settimane di partenza ---
        # est_1: sempre fisso (è il primo periodo, non c'è un precedente)
        vol.Optional("settimana_inizio_est_1",
                     default=defaults.get("settimana_inizio_est_1", 1)): int,
        # inv e est_2: 0 = continua automaticamente dal periodo precedente
        vol.Optional("settimana_inizio_inv",
                     default=defaults.get("settimana_inizio_inv", 0)): int,
        vol.Optional("settimana_inizio_est_2",
                     default=defaults.get("settimana_inizio_est_2", 0)): int,

        # --- Struttura del menù ---
        vol.Required("modalita_blocco",
                     default=defaults.get("modalita_blocco", "auto")): vol.In(MODALITA_BLOCCO_OPTIONS),
        vol.Required("portate_nomi",
                     default=portate_nomi): str,
        vol.Optional("portate_per_giorno",
                     default=defaults.get("portate_per_giorno", 5)): int,
    })


class SchoolMenuConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gestisce il modulo di configurazione dell'integrazione."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            errors = _valida_input(user_input)
            if not errors:
                return self.async_create_entry(
                    title="Menù Scuola",
                    data=_normalizza_input(user_input),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(user_input or {}),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Collega l'options flow a questa integrazione."""
        return SchoolMenuOptionsFlow(config_entry)


class SchoolMenuOptionsFlow(config_entries.OptionsFlow):
    """
    Gestisce la modifica della configurazione di un'integrazione già installata.
    Accessibile da: Impostazioni → Dispositivi e servizi → School Menu → Configura.
    """

    def __init__(self, config_entry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        errors = {}

        if user_input is not None:
            errors = _valida_input(user_input)
            if not errors:
                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    data=_normalizza_input(user_input),
                )
                await self.hass.config_entries.async_reload(self._config_entry.entry_id)
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(self._config_entry.data),
            errors=errors,
        )
