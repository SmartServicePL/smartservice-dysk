# © Smart Service Tczew. Wszelkie prawa zastrzeżone.
"""Smart Service Dysk constants."""

DOMAIN = "smartservice_dysk"
SERVICE_DOMAIN = "google_drive"
IMPLEMENTATION_NAME = "Smart Service"
CONF_KEY = "klucz"
DATA_STATE = f"{DOMAIN}_stan"
# The panel keeps a session 10 min; the integration asks for the result that long at most.
RESULT_WAIT_S = 600
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
