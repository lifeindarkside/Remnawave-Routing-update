import os
import time
import logging
import requests
import urllib3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

REMNA_BASE_URL = os.environ["REMNA_BASE_URL"].rstrip("/")
REMNA_API_URL = f"{REMNA_BASE_URL}/subscription-settings"
REMNA_TOKEN = os.environ["REMNA_TOKEN"]
GITHUB_RAW_URL = os.environ.get(
    "GITHUB_RAW_URL",
    "https://raw.githubusercontent.com/hydraponique/roscomvpn-happ-routing/refs/heads/main/HAPP/DEFAULT.DEEPLINK",
)
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "300"))  # seconds
SSL_VERIFY = REMNA_BASE_URL.startswith("https://")

REMNA_HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {REMNA_TOKEN}",
}

if not SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    REMNA_HEADERS["X-Forwarded-Proto"] = "https"
    REMNA_HEADERS["X-Forwarded-For"] = "127.0.0.1"


def get_remna_settings() -> dict:
    resp = requests.get(
        REMNA_API_URL,
        headers=REMNA_HEADERS,
        timeout=30,
        verify=SSL_VERIFY,
    )
    resp.raise_for_status()
    return resp.json()


def patch_remna_settings(payload: dict) -> dict:
    resp = requests.patch(
        REMNA_API_URL,
        headers={**REMNA_HEADERS, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
        verify=SSL_VERIFY,
    )
    resp.raise_for_status()
    return resp.json()


def get_github_deeplink() -> str:
    resp = requests.get(GITHUB_RAW_URL, timeout=30)
    resp.raise_for_status()
    return resp.text.strip()


def main():
    log.info("Starting routing update monitor")
    log.info("Remna API: %s", REMNA_API_URL)
    log.info("GitHub URL: %s", GITHUB_RAW_URL)
    log.info("Check interval: %ds", CHECK_INTERVAL)

    # Fetch current settings on startup
    settings = get_remna_settings()
    data = settings.get("response", settings)
    settings_uuid = data["uuid"]
    current_routing = data.get("happRouting", "") or ""
    log.info("Settings UUID: %s", settings_uuid)
    log.info("Current happRouting loaded (%d chars)", len(current_routing))

    while True:
        try:
            github_deeplink = get_github_deeplink()
            log.info("Fetched GitHub deeplink (%d chars)", len(github_deeplink))

            if github_deeplink != current_routing:
                log.info("Routing changed! Updating Remna...")
                result = patch_remna_settings({
                    "uuid": settings_uuid,
                    "happRouting": github_deeplink,
                })
                current_routing = github_deeplink
                log.info("Successfully updated happRouting in Remna")
                log.debug("Patch response: %s", result)
            else:
                log.info("No changes detected")

        except Exception:
            log.exception("Error during check cycle")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
