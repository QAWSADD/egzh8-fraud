"""Run the browser entry point after starting the local API."""

import webbrowser
from urllib.request import urlopen

URL = "http://127.0.0.1:8038/"

if __name__ == "__main__":
    try:
        with urlopen(URL + "health", timeout=6):
            pass
    except OSError as error:
        raise SystemExit(f"Start the API first (API_START.cmd): {error}")
    webbrowser.open(URL)
    print(URL)
