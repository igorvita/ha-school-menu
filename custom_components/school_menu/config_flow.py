import voluptuous as vol
from homeassistant import config_entries
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

    # Validazione date
    for field in ("data_inizio_inv", "data_inizio_est"):
        try:
            datetime.strptime(user_input[field], "%Y-%m-%d")
        except ValueError:
            errors[field] = "invalid_date"

    # Validazione coerenza nomi portate / portate_per_giorno
    # (solo in modalità 'fisso', dove portate_per_giorno è significativo)
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


class SchoolMenuConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gestisce il modulo di configurazione dell'integrazione."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            errors = _valida_input(user_input)
            if not errors:
                # Normalizziamo portate_nomi come lista pulita
                user_input["portate_nomi"] = [
                    n.strip()
                    for n in user_input["portate_nomi"].split(",")
                    if n.strip()
                ]
                return self.async_create_entry(title="Menù Scuola", data=user_input)

        data_schema = vol.Schema({
            vol.Required("pdf_url_inv"): str,
            vol.Required("data_inizio_inv"): str,
            vol.Required("pdf_url_est"): str,
            vol.Required("data_inizio_est"): str,
            vol.Required("settimane_ciclo", default=6): int,
            vol.Required("modalita_blocco", default="auto"): vol.In(MODALITA_BLOCCO_OPTIONS),
            vol.Required("portate_nomi", default=PORTATE_DEFAULT): str,
            # portate_per_giorno è usato solo in modalità 'fisso'
            vol.Optional("portate_per_giorno", default=5): int,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )
