#!/usr/bin/env python3
"""
MySports Kurs-Stornierung.
Wird via GitHub Actions workflow_dispatch getriggert.

Umgebungsvariablen:
  MYSPORTS_EMAIL      - Login E-Mail
  MYSPORTS_PASSWORD   - Login Passwort
  COURSE_APPOINTMENT_ID - ID des zu stornierenden Kurses
"""

import base64
import logging
import os
import sys

import requests
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

EMAIL    = os.environ["MYSPORTS_EMAIL"]
PASSWORD = os.environ["MYSPORTS_PASSWORD"]
COURSE_ID = os.environ.get("COURSE_APPOINTMENT_ID", "")

BASE_URL = "https://www.mysports.com"
TENANT   = "koerperschmiede"

HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "de-DE,de;q=0.9",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "x-ms-web-context": "/studio/a29lcnBlcnNjaG1pZWRlOjEyMTAwMDE0NTA%253D",
    "x-nox-client-type": "WEB",
    "x-nox-web-context": "utm_source=mysports.com&utm_medium=direct",
    "x-tenant": TENANT,
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/26.3.1 Safari/605.1.15"
    ),
}


def login(session: requests.Session) -> None:
    token = base64.b64encode(f"{EMAIL}:{PASSWORD}".encode()).decode()
    resp = session.post(
        f"{BASE_URL}/login",
        headers={**HEADERS, "Authorization": f"Basic {token}"},
        json={"tenantAlias": TENANT, "organizationUnitId": 1210001450},
    )
    resp.raise_for_status()
    if not session.cookies.get("SESSION"):
        raise RuntimeError("Login fehlgeschlagen")
    log.info("Login erfolgreich")


def cancel_course(session: requests.Session, course_id: str) -> None:
    payload = {
        "courseAppointmentId": int(course_id),
        "expectedCustomerStatus": "CANCELLED",
    }
    log.info("Storniere Kurs ID %s ...", course_id)
    resp = session.post(
        f"{BASE_URL}/nox/v1/calendar/cancelcourse",
        headers=HEADERS,
        json=payload,
    )
    if not resp.ok:
        # Fallback: bookcourse-Endpoint mit CANCELLED Status versuchen
        log.warning("cancelcourse fehlgeschlagen (%s), versuche bookcourse ...", resp.status_code)
        resp = session.post(
            f"{BASE_URL}/nox/v1/calendar/bookcourse",
            headers=HEADERS,
            json=payload,
        )
    resp.raise_for_status()
    log.info("Stornierung erfolgreich: %s", resp.json())


def main():
    if not COURSE_ID:
        log.error("COURSE_APPOINTMENT_ID nicht gesetzt.")
        sys.exit(1)

    with requests.Session() as session:
        try:
            login(session)
            cancel_course(session, COURSE_ID)
        except requests.HTTPError as e:
            log.error("HTTP-Fehler: %s – %s", e.response.status_code, e.response.text[:300])
            sys.exit(1)
        except Exception as e:
            log.error("Fehler: %s", e)
            sys.exit(1)


if __name__ == "__main__":
    main()
