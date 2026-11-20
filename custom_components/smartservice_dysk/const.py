"""Smart Service Dysk constants."""

DOMAIN = "smartservice_dysk"
SERVICE_DOMAIN = "google_drive"
IMPLEMENTATION_NAME = "Smart Service"
CONF_KEY = "klucz"
DATA_STATE = f"{DOMAIN}_stan"
# Each sign-in this integration started: its state for Smart Service HA (it never reads the flow itself - a read of a
# flow through Home Assistant's REST API moves it on) and the panel address given to it (one session per flow).
DATA_FLOWS = f"{DOMAIN}_przeplywy"
FLOW_KEEP_S = 900
# The panel keeps a session 10 min; the integration asks for the result that long at most.
RESULT_WAIT_S = 600
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
