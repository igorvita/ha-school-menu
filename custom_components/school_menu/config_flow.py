import voluptuous as vol
from homeassistant import config_entries
import homeassistant.helpers.config_validation as cv

DOMAIN = "school_menu"

class SchoolMenuConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gestisce il modulo di configurazione dell'integrazione."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Step visualizzato all'utente."""
        errors = {}

        if user_input is not None:
            # Qui potremmo validare le date se volessimo
            return self.async_create_entry(title="Menù Scuola", data=user_input)

        # Schema del modulo UI
        data_schema = vol.Schema({
            vol.Required("pdf_url_inv"): str,
            vol.Required("data_inizio_inv"): str, # Esempio: 2025-09-15
            vol.Required("pdf_url_est"): str,
            vol.Required("data_inizio_est"): str, # Esempio: 2026-04-01
            vol.Required("settimane_ciclo", default=6): int,
            vol.Required("portate_per_giorno", default=5): int,
        })

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )
