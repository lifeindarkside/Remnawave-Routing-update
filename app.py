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


def load_squad_configs() -> list:
    squads = []
    i = 1
    while True:
        uuid = os.environ.get(f"SQUAD_{i}_UUID", "").strip()
        url = os.environ.get(f"SQUAD_{i}_URL", "").strip()
        if not uuid or not url:
            break
        squads.append({"uuid": uuid, "url": url, "current_routing": None, "current_settings": {}})
        i += 1
    return squads


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


def get_external_squad(squad_uuid: str) -> dict:
    resp = requests.get(
        f"{REMNA_BASE_URL}/external-squads/{squad_uuid}",
        headers=REMNA_HEADERS,
        timeout=30,
        verify=SSL_VERIFY,
    )
    resp.raise_for_status()
    return resp.json()


def patch_external_squad(squad_uuid: str, routing: str, current_settings: dict) -> dict:
    merged = {**current_settings, "happRouting": routing}
    resp = requests.patch(
        f"{REMNA_BASE_URL}/external-squads",
        headers={**REMNA_HEADERS, "Content-Type": "application/json"},
        json={"uuid": squad_uuid, "subscriptionSettings": merged},
        timeout=30,
        verify=SSL_VERIFY,
    )
    resp.raise_for_status()
    return resp.json()


def get_github_deeplink(url: str) -> str:
    resp = requests.get(url, timeout=30)
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
    current_routing = (data.get("happRouting", "") or "").strip()
    log.info("Settings UUID: %s", settings_uuid)
    log.info("Current happRouting loaded (%d chars)", len(current_routing))

    squads = load_squad_configs()
    log.info("Loaded %d external squad(s)", len(squads))
    for squad in squads:
        try:
            data = get_external_squad(squad["uuid"])
            squad_data = data.get("response", data)
            squad["current_settings"] = squad_data.get("subscriptionSettings", {}) or {}
            squad["current_routing"] = (squad["current_settings"].get("happRouting", "") or "").strip()
            log.info("Squad %s current happRouting loaded (%d chars)", squad["uuid"], len(squad["current_routing"]))
        except Exception:
            log.exception("Failed to fetch initial routing for squad %s, will update on first cycle", squad["uuid"])

    while True:
        try:
            github_deeplink = get_github_deeplink(GITHUB_RAW_URL)
            log.info("Fetched GitHub deeplink (%d chars)", len(github_deeplink))

            if github_deeplink != current_routing:
                log.info("Routing changed! Updating subscription settings...")
                result = patch_remna_settings({
                    "uuid": settings_uuid,
                    "happRouting": github_deeplink,
                })
                current_routing = github_deeplink
                log.info("Successfully updated happRouting in subscription settings")
                log.debug("Patch response: %s", result)
            else:
                log.info("No changes detected in subscription settings")

        except Exception:
            log.exception("Error during subscription settings check cycle")

        for squad in squads:
            try:
                deeplink = get_github_deeplink(squad["url"])
                if deeplink != squad["current_routing"]:
                    log.info("Routing changed for squad %s! Updating...", squad["uuid"])
                    patch_external_squad(squad["uuid"], deeplink, squad["current_settings"])
                    squad["current_settings"] = {**squad["current_settings"], "happRouting": deeplink}
                    squad["current_routing"] = deeplink
                    log.info("Successfully updated happRouting for squad %s", squad["uuid"])
                else:
                    log.info("No changes detected for squad %s", squad["uuid"])
            except Exception:
                log.exception("Error updating squad %s", squad["uuid"])

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
