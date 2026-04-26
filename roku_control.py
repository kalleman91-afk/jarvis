"""
JARVIS Roku Control — Roku TV integration via External Control Protocol (ECP).

Controls a Roku device on the local network using HTTP requests to the ECP API.
All functions are async (httpx) to match the JARVIS codebase style.

ECP Base URL: http://{ROKU_IP}:8060
Each function returns {"success": bool, "confirmation": str} for action-system
compatibility, plus optional data fields for query operations.

Environment:
    ROKU_IP  — IP address of the Roku device (default: 192.168.0.75)
"""

import logging
import os
from typing import Optional
from xml.etree import ElementTree

import httpx

log = logging.getLogger("jarvis.roku")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROKU_IP: str = os.getenv("ROKU_IP", "192.168.0.75")
ROKU_PORT: int = 8060
ROKU_TIMEOUT: float = 5.0  # seconds — Roku ECP is fast on LAN

# ---------------------------------------------------------------------------
# Known App ID Mapping
# Common Roku channel IDs for easy launching by name.
# Full list: https://developer.roku.com/docs/developer-program/discovery/external-control-api.md
# ---------------------------------------------------------------------------

APP_IDS: dict[str, str] = {
    # Streaming services
    "netflix":          "12",
    "youtube":          "tvinput.hdmi1",   # fallback; real ID varies by region
    "youtube tv":       "195316",
    "hulu":             "2285",
    "disney+":          "291097",
    "disney plus":      "291097",
    "amazon":           "13",
    "amazon prime":     "13",
    "prime video":      "13",
    "hbo max":          "61322",
    "max":              "61322",
    "apple tv":         "551012",
    "apple tv+":        "551012",
    "peacock":          "593099",
    "paramount+":       "31440",
    "paramount plus":   "31440",
    "espn":             "3508",
    "espn+":            "3508",
    "discovery+":       "613247",
    "discovery plus":   "613247",
    "fubo":             "199330",
    "fubo tv":          "199330",
    "fubotv":           "199330",
    "sling":            "46041",
    "sling tv":         "46041",
    "tubi":             "41468",
    "pluto":            "74519",
    "pluto tv":         "74519",
    "crunchyroll":      "34399",
    "showtime":         "3201",
    "starz":            "5907",
    "amc+":             "526455",
    "amc plus":         "526455",
    "plex":             "13535",
    "vudu":             "13535",
    "fandango":         "13535",
    # Live TV / News
    "cnn":              "50025",
    "fox news":         "2440",
    "msnbc":            "50025",
    "nbc news":         "50025",
    "abc news":         "50025",
    "cbsn":             "50025",
    "the roku channel": "151908",
    "roku channel":     "151908",
    # Music / Podcasts
    "spotify":          "22297",
    "pandora":          "28",
    "iheartradio":      "2425",
    # Fitness / Other
    "youtube kids":     "2285",
    "twitch":           "56594",
    "vimeo":            "2285",
}

# ---------------------------------------------------------------------------
# ECP Key Names
# Documented at: https://developer.roku.com/docs/developer-program/discovery/external-control-api.md
# ---------------------------------------------------------------------------

# Navigation
KEY_HOME        = "Home"
KEY_BACK        = "Back"
KEY_SELECT      = "Select"
KEY_UP          = "Up"
KEY_DOWN        = "Down"
KEY_LEFT        = "Left"
KEY_RIGHT       = "Right"
KEY_INFO        = "Info"
KEY_INSTANT_REPLAY = "InstantReplay"

# Playback
KEY_PLAY        = "Play"
KEY_PAUSE       = "Play"          # Roku uses Play as a toggle
KEY_PLAY_PAUSE  = "Play"
KEY_REV         = "Rev"           # Rewind
KEY_FWD         = "Fwd"           # Fast-forward

# Volume
KEY_VOL_UP      = "VolumeUp"
KEY_VOL_DOWN    = "VolumeDown"
KEY_MUTE        = "VolumeMute"

# Power
KEY_POWER_OFF   = "PowerOff"
KEY_POWER_ON    = "PowerOn"
KEY_POWER       = "Power"         # Toggle (some devices)

# Text input
KEY_BACKSPACE   = "Backspace"
KEY_SEARCH      = "Search"
KEY_ENTER       = "Enter"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _base_url() -> str:
    """Return the ECP base URL for the configured Roku device."""
    return f"http://{ROKU_IP}:{ROKU_PORT}"


async def _post(path: str, timeout: float = ROKU_TIMEOUT) -> tuple[bool, int]:
    """Send an HTTP POST to the Roku ECP endpoint.

    Returns (success: bool, status_code: int).
    Roku ECP returns 200 for success; no body is expected on keypress/launch.
    """
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url)
            ok = resp.status_code == 200
            if not ok:
                log.warning(f"Roku POST {path} → {resp.status_code}")
            return ok, resp.status_code
    except httpx.ConnectError:
        log.error(f"Roku unreachable at {ROKU_IP}:{ROKU_PORT} — check ROKU_IP and network")
        return False, 0
    except httpx.TimeoutException:
        log.error(f"Roku POST {path} timed out after {timeout}s")
        return False, 0
    except Exception as exc:
        log.error(f"Roku POST {path} failed: {exc}")
        return False, 0


async def _get(path: str, timeout: float = ROKU_TIMEOUT) -> tuple[bool, str]:
    """Send an HTTP GET to the Roku ECP endpoint.

    Returns (success: bool, response_body: str).
    """
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            ok = resp.status_code == 200
            if not ok:
                log.warning(f"Roku GET {path} → {resp.status_code}")
                return False, ""
            return True, resp.text
    except httpx.ConnectError:
        log.error(f"Roku unreachable at {ROKU_IP}:{ROKU_PORT} — check ROKU_IP and network")
        return False, ""
    except httpx.TimeoutException:
        log.error(f"Roku GET {path} timed out after {timeout}s")
        return False, ""
    except Exception as exc:
        log.error(f"Roku GET {path} failed: {exc}")
        return False, ""


def _parse_xml(body: str) -> Optional[ElementTree.Element]:
    """Parse an XML response body; returns None on failure."""
    try:
        return ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        log.warning(f"Roku XML parse error: {exc}")
        return None


def _resolve_app_id(name_or_id: str) -> Optional[str]:
    """Resolve a human-readable app name to its Roku channel ID.

    Accepts either a known name (case-insensitive) or a raw numeric/string ID.
    Returns None if the name is not in the mapping and is not a bare digit string.
    """
    key = name_or_id.strip().lower()
    if key in APP_IDS:
        return APP_IDS[key]
    # Accept bare numeric IDs directly
    if name_or_id.strip().isdigit():
        return name_or_id.strip()
    return None


# ---------------------------------------------------------------------------
# 1. Discovery — list installed apps
# ---------------------------------------------------------------------------

async def list_apps() -> dict:
    """Query all installed apps (channels) on the Roku device.

    Returns:
        {
            "success": bool,
            "confirmation": str,
            "apps": [{"id": str, "name": str, "version": str}, ...]
        }
    """
    ok, body = await _get("/query/apps")
    if not ok:
        return {
            "success": False,
            "confirmation": "Unable to reach the Roku device, sir.",
            "apps": [],
        }

    root = _parse_xml(body)
    if root is None:
        return {
            "success": False,
            "confirmation": "Roku returned an unreadable app list, sir.",
            "apps": [],
        }

    apps = []
    for app in root.findall("app"):
        apps.append({
            "id":      app.get("id", ""),
            "name":    app.text or "",
            "version": app.get("version", ""),
        })

    apps.sort(key=lambda a: a["name"].lower())
    count = len(apps)
    log.info(f"Roku: found {count} installed apps")

    return {
        "success": True,
        "confirmation": f"Found {count} apps installed on the Roku, sir.",
        "apps": apps,
    }


def format_apps_for_voice(apps: list[dict], max_items: int = 8) -> str:
    """Format an app list as a brief voice-friendly summary."""
    if not apps:
        return "No apps found on the Roku, sir."
    names = [a["name"] for a in apps[:max_items]]
    summary = ", ".join(names)
    if len(apps) > max_items:
        summary += f", and {len(apps) - max_items} more"
    return f"Installed apps include: {summary}."


# ---------------------------------------------------------------------------
# 2. Launch apps
# ---------------------------------------------------------------------------

async def launch_app(name_or_id: str) -> dict:
    """Launch an app on the Roku by name or channel ID.

    Common names are resolved via the APP_IDS mapping (e.g. "netflix", "hulu").
    Pass a raw numeric ID to launch any channel not in the mapping.

    Args:
        name_or_id: Human-readable app name or Roku channel ID string.

    Returns:
        {"success": bool, "confirmation": str, "app_id": str | None}
    """
    app_id = _resolve_app_id(name_or_id)
    if app_id is None:
        log.warning(f"Roku: unknown app '{name_or_id}' — not in APP_IDS mapping")
        return {
            "success": False,
            "confirmation": f"Sorry, sir — '{name_or_id}' isn't in my app list. Try listing installed apps first.",
            "app_id": None,
        }

    ok, _ = await _post(f"/launch/{app_id}")
    display_name = name_or_id.title()
    return {
        "success": ok,
        "confirmation": f"Launching {display_name} on the Roku, sir." if ok
                        else f"Failed to launch {display_name}, sir.",
        "app_id": app_id,
    }


async def launch_app_by_id(app_id: str) -> dict:
    """Launch a Roku app directly by its numeric channel ID.

    Use this when the app is not in the APP_IDS mapping but you know its ID
    (e.g. from the result of list_apps()).

    Args:
        app_id: Roku channel ID string (e.g. "12" for Netflix).

    Returns:
        {"success": bool, "confirmation": str}
    """
    ok, _ = await _post(f"/launch/{app_id}")
    return {
        "success": ok,
        "confirmation": f"Launching channel {app_id} on the Roku, sir." if ok
                        else f"Could not launch channel {app_id}, sir.",
    }


# ---------------------------------------------------------------------------
# 3. Remote control — keypresses
# ---------------------------------------------------------------------------

async def keypress(key: str) -> dict:
    """Send a single keypress to the Roku remote.

    Args:
        key: ECP key name (e.g. "Home", "Select", "VolumeUp"). See module-level
             KEY_* constants for the full list.

    Returns:
        {"success": bool, "confirmation": str}
    """
    ok, _ = await _post(f"/keypress/{key}")
    return {
        "success": ok,
        "confirmation": f"Sent {key} to the Roku, sir." if ok
                        else f"Keypress {key} failed, sir.",
    }


# --- Navigation ---

async def nav_home() -> dict:
    """Press the Home button — returns to the Roku home screen."""
    ok, _ = await _post(f"/keypress/{KEY_HOME}")
    return {
        "success": ok,
        "confirmation": "Going home, sir." if ok else "Home button failed, sir.",
    }


async def nav_back() -> dict:
    """Press the Back button."""
    ok, _ = await _post(f"/keypress/{KEY_BACK}")
    return {
        "success": ok,
        "confirmation": "Going back, sir." if ok else "Back button failed, sir.",
    }


async def nav_select() -> dict:
    """Press the Select (OK) button."""
    ok, _ = await _post(f"/keypress/{KEY_SELECT}")
    return {
        "success": ok,
        "confirmation": "Selected, sir." if ok else "Select failed, sir.",
    }


async def nav_up() -> dict:
    """Press the Up directional button."""
    ok, _ = await _post(f"/keypress/{KEY_UP}")
    return {"success": ok, "confirmation": "Up, sir." if ok else "Up failed, sir."}


async def nav_down() -> dict:
    """Press the Down directional button."""
    ok, _ = await _post(f"/keypress/{KEY_DOWN}")
    return {"success": ok, "confirmation": "Down, sir." if ok else "Down failed, sir."}


async def nav_left() -> dict:
    """Press the Left directional button."""
    ok, _ = await _post(f"/keypress/{KEY_LEFT}")
    return {"success": ok, "confirmation": "Left, sir." if ok else "Left failed, sir."}


async def nav_right() -> dict:
    """Press the Right directional button."""
    ok, _ = await _post(f"/keypress/{KEY_RIGHT}")
    return {"success": ok, "confirmation": "Right, sir." if ok else "Right failed, sir."}


# --- Playback ---

async def play_pause() -> dict:
    """Toggle play/pause on the currently active stream."""
    ok, _ = await _post(f"/keypress/{KEY_PLAY_PAUSE}")
    return {
        "success": ok,
        "confirmation": "Play/pause toggled, sir." if ok else "Play/pause failed, sir.",
    }


async def rewind() -> dict:
    """Press the Rewind button."""
    ok, _ = await _post(f"/keypress/{KEY_REV}")
    return {
        "success": ok,
        "confirmation": "Rewinding, sir." if ok else "Rewind failed, sir.",
    }


async def fast_forward() -> dict:
    """Press the Fast-Forward button."""
    ok, _ = await _post(f"/keypress/{KEY_FWD}")
    return {
        "success": ok,
        "confirmation": "Fast-forwarding, sir." if ok else "Fast-forward failed, sir.",
    }


async def instant_replay() -> dict:
    """Press the Instant Replay button (jumps back ~10 seconds)."""
    ok, _ = await _post(f"/keypress/{KEY_INSTANT_REPLAY}")
    return {
        "success": ok,
        "confirmation": "Instant replay, sir." if ok else "Instant replay failed, sir.",
    }


# --- Volume ---

async def volume_up(steps: int = 1) -> dict:
    """Increase the volume by one or more steps.

    Args:
        steps: Number of volume-up keypresses to send (default: 1).

    Returns:
        {"success": bool, "confirmation": str}
    """
    steps = max(1, min(steps, 20))  # Guard against runaway loops
    results = []
    for _ in range(steps):
        ok, _ = await _post(f"/keypress/{KEY_VOL_UP}")
        results.append(ok)
    success = all(results)
    return {
        "success": success,
        "confirmation": f"Volume up {steps} step{'s' if steps > 1 else ''}, sir." if success
                        else "Volume up failed, sir.",
    }


async def volume_down(steps: int = 1) -> dict:
    """Decrease the volume by one or more steps.

    Args:
        steps: Number of volume-down keypresses to send (default: 1).

    Returns:
        {"success": bool, "confirmation": str}
    """
    steps = max(1, min(steps, 20))
    results = []
    for _ in range(steps):
        ok, _ = await _post(f"/keypress/{KEY_VOL_DOWN}")
        results.append(ok)
    success = all(results)
    return {
        "success": success,
        "confirmation": f"Volume down {steps} step{'s' if steps > 1 else ''}, sir." if success
                        else "Volume down failed, sir.",
    }


async def mute() -> dict:
    """Toggle mute on the Roku device."""
    ok, _ = await _post(f"/keypress/{KEY_MUTE}")
    return {
        "success": ok,
        "confirmation": "Mute toggled, sir." if ok else "Mute failed, sir.",
    }


# ---------------------------------------------------------------------------
# 4. Text input
# ---------------------------------------------------------------------------

async def send_text(text: str) -> dict:
    """Type a string into the currently focused Roku text field.

    Each character is sent as a separate Lit_{char} keypress per the ECP spec.
    Useful for search fields in apps like Netflix or YouTube.

    Args:
        text: The string to type (printable ASCII characters).

    Returns:
        {"success": bool, "confirmation": str, "chars_sent": int}
    """
    if not text:
        return {
            "success": False,
            "confirmation": "No text provided, sir.",
            "chars_sent": 0,
        }

    sent = 0
    failed = 0
    for char in text:
        # ECP encodes each character as Lit_{char}; special chars need URL encoding
        from urllib.parse import quote
        encoded = quote(char, safe="")
        ok, _ = await _post(f"/keypress/Lit_{encoded}")
        if ok:
            sent += 1
        else:
            failed += 1
            log.warning(f"Roku: failed to send character '{char}'")

    success = failed == 0
    return {
        "success": success,
        "confirmation": f"Typed '{text}' on the Roku, sir." if success
                        else f"Typed {sent} of {len(text)} characters, sir — {failed} failed.",
        "chars_sent": sent,
    }


async def search_and_type(query: str) -> dict:
    """Press the Search key then type a query string.

    Convenience wrapper that opens the search interface and enters text.

    Args:
        query: Search string to type after pressing Search.

    Returns:
        {"success": bool, "confirmation": str}
    """
    search_result = await keypress(KEY_SEARCH)
    if not search_result["success"]:
        return {
            "success": False,
            "confirmation": "Could not open search on the Roku, sir.",
        }

    type_result = await send_text(query)
    return {
        "success": type_result["success"],
        "confirmation": f"Searching for '{query}' on the Roku, sir." if type_result["success"]
                        else f"Search opened but typing failed, sir.",
    }


# ---------------------------------------------------------------------------
# 5. Power
# ---------------------------------------------------------------------------

async def power_on() -> dict:
    """Send the PowerOn command to the Roku device.

    Note: Requires the Roku to support CEC or be in a low-power standby state.
    Some Roku models wake via PowerOn; others require a physical remote press.

    Returns:
        {"success": bool, "confirmation": str}
    """
    ok, _ = await _post(f"/keypress/{KEY_POWER_ON}")
    return {
        "success": ok,
        "confirmation": "Powering on the Roku, sir." if ok else "Power on command failed, sir.",
    }


async def power_off() -> dict:
    """Send the PowerOff command to put the Roku into standby.

    Returns:
        {"success": bool, "confirmation": str}
    """
    ok, _ = await _post(f"/keypress/{KEY_POWER_OFF}")
    return {
        "success": ok,
        "confirmation": "Powering off the Roku, sir." if ok else "Power off command failed, sir.",
    }


async def power_toggle() -> dict:
    """Send the Power toggle command (supported on some Roku models).

    Returns:
        {"success": bool, "confirmation": str}
    """
    ok, _ = await _post(f"/keypress/{KEY_POWER}")
    return {
        "success": ok,
        "confirmation": "Power toggled on the Roku, sir." if ok else "Power toggle failed, sir.",
    }


# ---------------------------------------------------------------------------
# 6. Device info and active app
# ---------------------------------------------------------------------------

async def get_device_info() -> dict:
    """Query the Roku device for hardware and software information.

    Returns:
        {
            "success": bool,
            "confirmation": str,
            "info": {
                "model_name": str,
                "model_number": str,
                "software_version": str,
                "serial_number": str,
                "device_id": str,
                "friendly_name": str,
                "is_tv": bool,
                ...
            }
        }
    """
    ok, body = await _get("/query/device-info")
    if not ok:
        return {
            "success": False,
            "confirmation": "Unable to reach the Roku device, sir.",
            "info": {},
        }

    root = _parse_xml(body)
    if root is None:
        return {
            "success": False,
            "confirmation": "Roku returned unreadable device info, sir.",
            "info": {},
        }

    # Flatten all child elements into a dict
    info: dict[str, str] = {}
    for child in root:
        info[child.tag] = child.text or ""

    # Normalise a few key fields for convenience
    friendly = info.get("friendly-device-name") or info.get("user-device-name") or "Roku"
    model = info.get("model-name", "Unknown model")
    sw = info.get("software-version", "Unknown")
    is_tv = info.get("is-tv", "false").lower() == "true"

    summary = f"{friendly} ({model}), software {sw}"
    log.info(f"Roku device info: {summary}")

    return {
        "success": True,
        "confirmation": f"Device is a {summary}, sir.",
        "info": {
            "model_name":       model,
            "model_number":     info.get("model-number", ""),
            "software_version": sw,
            "serial_number":    info.get("serial-number", ""),
            "device_id":        info.get("device-id", ""),
            "friendly_name":    friendly,
            "is_tv":            is_tv,
            "raw":              info,
        },
    }


async def get_active_app() -> dict:
    """Query which app is currently running on the Roku.

    Returns:
        {
            "success": bool,
            "confirmation": str,
            "app": {"id": str, "name": str, "version": str} | None
        }
    """
    ok, body = await _get("/query/active-app")
    if not ok:
        return {
            "success": False,
            "confirmation": "Unable to reach the Roku device, sir.",
            "app": None,
        }

    root = _parse_xml(body)
    if root is None:
        return {
            "success": False,
            "confirmation": "Roku returned unreadable active-app data, sir.",
            "app": None,
        }

    app_el = root.find("app")
    if app_el is None:
        return {
            "success": True,
            "confirmation": "No app is currently active on the Roku, sir.",
            "app": None,
        }

    app = {
        "id":      app_el.get("id", ""),
        "name":    app_el.text or "Unknown",
        "version": app_el.get("version", ""),
    }

    log.info(f"Roku active app: {app['name']} (id={app['id']})")
    return {
        "success": True,
        "confirmation": f"Currently playing {app['name']} on the Roku, sir.",
        "app": app,
    }


# ---------------------------------------------------------------------------
# 7. Convenience composite actions
# ---------------------------------------------------------------------------

async def roku_status() -> dict:
    """Return a combined status snapshot: device info + active app.

    Useful for injecting Roku context into the JARVIS system prompt.

    Returns:
        {
            "success": bool,
            "confirmation": str,
            "device": dict,
            "active_app": dict | None,
        }
    """
    device_result = await get_device_info()
    app_result = await get_active_app()

    success = device_result["success"] or app_result["success"]
    device_name = device_result["info"].get("friendly_name", "Roku") if device_result["success"] else "Roku"
    active_name = app_result["app"]["name"] if (app_result["success"] and app_result["app"]) else "nothing"

    return {
        "success": success,
        "confirmation": f"{device_name} is on and running {active_name}, sir." if success
                        else "Could not reach the Roku, sir.",
        "device": device_result.get("info", {}),
        "active_app": app_result.get("app"),
    }


def format_status_for_context(status: dict) -> str:
    """Format a roku_status() result as a brief LLM context string."""
    if not status.get("success"):
        return "Roku: unreachable."

    device = status.get("device", {})
    app = status.get("active_app")

    name = device.get("friendly_name", "Roku")
    model = device.get("model_name", "")
    active = app["name"] if app else "Home screen"

    return f"Roku ({name}{', ' + model if model else ''}): currently showing {active}."
