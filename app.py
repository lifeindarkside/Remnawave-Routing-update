import os
import time
import logging
import requests
import urllib3
from datetime import datetime

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
CRON_SCHEDULE = os.environ.get("CRON_SCHEDULE", "").strip()
SSL_VERIFY = REMNA_BASE_URL.startswith("https://")

REMNA_HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {REMNA_TOKEN}",
}
ROUTING_HEADER = "routing"

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
        squads.append(
            {
                "uuid": uuid,
                "url": url,
                "current_routing": None,
                "response_headers_add": {},
                "response_headers_remove": [],
            }
        )
        i += 1
    return squads


def get_routing_header(headers: dict | None) -> str:
    for key, value in (headers or {}).items():
        if key.lower() == ROUTING_HEADER:
            return (value or "").strip()
    return ""


def with_routing_header(headers: dict | None, routing: str) -> dict:
    merged = {key: value for key, value in (headers or {}).items() if key.lower() != ROUTING_HEADER}
    merged[ROUTING_HEADER] = routing
    return merged


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


def patch_external_squad(
    squad_uuid: str,
    response_headers_add: dict,
    response_headers_remove: list,
) -> dict:
    payload = {
        "uuid": squad_uuid,
        "responseHeadersAdd": response_headers_add,
    }
    # Если routing был явно удалён в настройках сквада, убираем конфликт.
    filtered_remove = [header for header in response_headers_remove if header.lower() != ROUTING_HEADER]
    if filtered_remove != response_headers_remove:
        payload["responseHeadersRemove"] = filtered_remove

    resp = requests.patch(
        f"{REMNA_BASE_URL}/external-squads",
        headers={**REMNA_HEADERS, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
        verify=SSL_VERIFY,
    )
    resp.raise_for_status()
    return resp.json()


def get_github_deeplink(url: str) -> str:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text.strip()


def run_cycle(settings_uuid: str, state: dict, squads: list) -> None:
    """Одна итерация проверки: сравнить роутинг на GitHub с текущим и обновить при изменении."""
    try:
        github_deeplink = get_github_deeplink(GITHUB_RAW_URL)
        log.info("Fetched GitHub deeplink (%d chars)", len(github_deeplink))

        if github_deeplink != state["current_routing"]:
            log.info("Routing changed! Updating subscription settings...")
            updated_headers = with_routing_header(
                state["custom_response_headers"],
                github_deeplink,
            )
            result = patch_remna_settings(
                {
                    "uuid": settings_uuid,
                    "customResponseHeaders": updated_headers,
                }
            )
            state["custom_response_headers"] = updated_headers
            state["current_routing"] = github_deeplink
            log.info("Successfully updated routing response header in subscription settings")
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
                updated_headers = with_routing_header(
                    squad["response_headers_add"],
                    deeplink,
                )
                patch_external_squad(
                    squad["uuid"],
                    updated_headers,
                    squad["response_headers_remove"],
                )
                squad["response_headers_add"] = updated_headers
                squad["response_headers_remove"] = [header for header in squad["response_headers_remove"] if header.lower() != ROUTING_HEADER]
                squad["current_routing"] = deeplink
                log.info("Successfully updated routing response header for squad %s", squad["uuid"])
            else:
                log.info("No changes detected for squad %s", squad["uuid"])
        except Exception:
            log.exception("Error updating squad %s", squad["uuid"])


def main():
    log.info("Starting routing update monitor")
    log.info("Remna API: %s", REMNA_API_URL)
    log.info("GitHub URL: %s", GITHUB_RAW_URL)
    if CRON_SCHEDULE:
        log.info("Mode: cron schedule '%s' (container local time)", CRON_SCHEDULE)
    else:
        log.info("Mode: interval polling every %ds", CHECK_INTERVAL)

    # Fetch current settings on startup
    settings = get_remna_settings()
    data = settings.get("response", settings)
    settings_uuid = data["uuid"]
    custom_response_headers = data.get("customResponseHeaders", {}) or {}
    state = {
        "custom_response_headers": custom_response_headers,
        "current_routing": get_routing_header(custom_response_headers),
    }
    log.info("Settings UUID: %s", settings_uuid)
    log.info("Current routing response header loaded (%d chars)", len(state["current_routing"]))

    squads = load_squad_configs()
    log.info("Loaded %d external squad(s)", len(squads))
    for squad in squads:
        try:
            data = get_external_squad(squad["uuid"])
            squad_data = data.get("response", data)
            squad["response_headers_add"] = squad_data.get("responseHeadersAdd", {}) or {}
            squad["response_headers_remove"] = squad_data.get("responseHeadersRemove", []) or []
            squad["current_routing"] = get_routing_header(squad["response_headers_add"])
            log.info(
                "Squad %s current routing response header loaded (%d chars)",
                squad["uuid"],
                len(squad["current_routing"]),
            )
        except Exception:
            log.exception("Failed to fetch initial routing for squad %s, will update on first cycle", squad["uuid"])

    if CRON_SCHEDULE:
        try:
            from croniter import croniter
        except ImportError:
            raise SystemExit("CRON_SCHEDULE is set, but the 'croniter' package is not installed")
        if not croniter.is_valid(CRON_SCHEDULE):
            raise SystemExit(f"Invalid CRON_SCHEDULE expression: {CRON_SCHEDULE!r}")

        # Синхронизируемся один раз при запуске, чтобы не ждать первого срабатывания
        # расписания (например, после рестарта или деплоя), затем работаем по cron.
        run_cycle(settings_uuid, state, squads)
        schedule = croniter(CRON_SCHEDULE, datetime.now())
        while True:
            next_run = schedule.get_next(datetime)
            delay = (next_run - datetime.now()).total_seconds()
            if delay > 0:
                log.info(
                    "Next scheduled run at %s (in %ds)",
                    next_run.isoformat(sep=" ", timespec="seconds"),
                    int(delay),
                )
                time.sleep(delay)
            run_cycle(settings_uuid, state, squads)
    else:
        while True:
            run_cycle(settings_uuid, state, squads)
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
