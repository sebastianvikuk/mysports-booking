#!/usr/bin/env python3
"""
MySports Kurs-Automatisierung
Bucht jeden Dienstag um 18:01 Uhr den Kurs fuer den naechsten Dienstag.

Cron-Eintrag (Mac):
  1 18 * * 2 cd /Users/g441227/Library/CloudStorage/OneDrive-Allianz(2)/programming/mysports-booking && .venv/bin/python3 book.py >> /tmp/mysports.log 2>&1
"""

import base64
import json
import logging
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.text import MIMEText

import requests
from dotenv import load_dotenv

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Konfiguration ──────────────────────────────────────────────────────────
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

EMAIL    = os.environ["MYSPORTS_EMAIL"]
PASSWORD = os.environ["MYSPORTS_PASSWORD"]
COURSE_NAME    = os.environ.get("COURSE_NAME", "Hyrox Training")
COURSE_WEEKDAY = int(os.environ.get("COURSE_WEEKDAY", "1"))   # 0=Mo … 6=So
COURSE_HOUR    = int(os.environ.get("COURSE_HOUR", "18"))
SMTP_APP_PASS  = os.environ.get("SMTP_APP_PASSWORD", "")
NOTIFY_EMAIL   = os.environ.get("NOTIFY_EMAIL", EMAIL)

BASE_URL   = "https://www.mysports.com"
TENANT     = "koerperschmiede"
STUDIO_ID  = "1210001450"
WEB_CTX    = "/studio/a29lcnBlcnNjaG1pZWRlOjEyMTAwMDE0NTA%253D"

HEADERS_BASE = {
    "Accept": "*/*",
    "Accept-Language": "de-DE,de;q=0.9",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "x-ms-web-context": WEB_CTX,
    "x-nox-client-type": "WEB",
    "x-nox-web-context": "utm_source=mysports.com&utm_medium=direct",
    "x-tenant": TENANT,
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/26.3.1 Safari/605.1.15"
    ),
}


# ── Hilfsfunktionen ────────────────────────────────────────────────────────

def next_weekday(weekday: int) -> datetime:
    """Gibt das Datum des nächsten <weekday> zurück (0=Mo, 1=Di, …)."""
    today = datetime.now()
    days_ahead = weekday - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def login(session: requests.Session) -> str:
    """Loggt ein und gibt das SESSION-Cookie zurück."""
    token = base64.b64encode(f"{EMAIL}:{PASSWORD}".encode()).decode()
    headers = {**HEADERS_BASE, "Authorization": f"Basic {token}"}
    resp = session.post(f"{BASE_URL}/login", headers=headers, json={})
    resp.raise_for_status()
    session_cookie = session.cookies.get("SESSION")
    if not session_cookie:
        raise RuntimeError("Login fehlgeschlagen – kein SESSION-Cookie erhalten")
    log.info("Login erfolgreich (SESSION=%s…)", session_cookie[:8])
    return session_cookie


def fetch_courses(session: requests.Session, target_date: datetime) -> list:
    """Lädt den Kursplan für <target_date> via v2 API."""
    date_str = target_date.strftime("%Y-%m-%d")
    url = (
        f"{BASE_URL}/nox/v2/bookableitems/courses/with-canceled"
        f"?startDate={date_str}&endDate={date_str}"
        f"&employeeIds=&organizationUnitIds={STUDIO_ID}"
    )
    resp = session.get(url, headers=HEADERS_BASE)
    resp.raise_for_status()
    courses = resp.json()
    log.info("Kursplan geladen: %d Einträge für %s", len(courses), date_str)
    return courses


def find_course(courses: list, name: str, hour: int) -> dict | None:
    """Sucht den Kurs anhand von Name und Uhrzeit – bookable-Flag ignoriert."""
    for c in courses:
        if name.lower() not in c.get("name", "").lower():
            continue
        for slot in c.get("slots", []):
            if f"T{hour:02d}:" in slot.get("startDateTime", ""):
                return c
    return None


def book_course(session: requests.Session, course: dict) -> bool:
    """Bucht den Kurs mit dem korrekten minimalen Payload."""
    course_id = course["id"]
    slot = course["slots"][0]
    log.info("Sende Buchung: courseAppointmentId=%s start=%s", course_id, slot["startDateTime"][:16])
    payload = {
        "courseAppointmentId": course_id,
        "expectedCustomerStatus": "BOOKED",
    }
    resp = session.post(
        f"{BASE_URL}/nox/v1/calendar/bookcourse",
        headers=HEADERS_BASE,
        json=payload,
    )
    resp.raise_for_status()
    result = resp.json()
    status = result.get("participantStatus") or result.get("calendarItemStatus")
    log.info("Buchung erfolgreich – Status: %s", status)
    return True


def send_notification(course_name: str, start: str) -> None:
    """Sendet eine Bestaetigungs-Mail via Gmail SMTP."""
    if not SMTP_APP_PASS:
        log.info("SMTP_APP_PASSWORD nicht gesetzt – keine Mail versendet.")
        return
    subject = f"MySports: '{course_name}' gebucht"
    body    = f"Der Kurs wurde erfolgreich gebucht:\n\n  {course_name}\n  {start}\n"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = EMAIL
    msg["To"]      = NOTIFY_EMAIL
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL, SMTP_APP_PASS)
            smtp.send_message(msg)
        log.info("Bestaetigungs-Mail an %s gesendet.", NOTIFY_EMAIL)
    except Exception as exc:
        log.warning("Mail-Versand fehlgeschlagen: %s", exc)


# ── Hauptprogramm ──────────────────────────────────────────────────────────

def main():
    target = next_weekday(COURSE_WEEKDAY)
    log.info(
        "Starte Buchung: '%s' am %s um %d:00 Uhr",
        COURSE_NAME,
        target.strftime("%d.%m.%Y"),
        COURSE_HOUR,
    )

    with requests.Session() as session:
        try:
            login(session)
            courses = fetch_courses(session, target)
            course = find_course(courses, COURSE_NAME, COURSE_HOUR)

            if not course:
                log.error(
                    "Kurs '%s' um %d:00 Uhr am %s nicht gefunden.",
                    COURSE_NAME,
                    COURSE_HOUR,
                    target.strftime("%d.%m.%Y"),
                )
                log.info(
                    "Verfügbare Kurse: %s",
                    [f"{c.get('name')} {c['slots'][0]['startDateTime'][11:16]}" for c in courses],
                )
                sys.exit(1)

            log.info("Kurs gefunden: %s (ID %s)", course.get("name"), course.get("id"))
            book_course(session, course)
            slot_start = course["slots"][0]["startDateTime"][:16].replace("T", " ")
            send_notification(course.get("name", COURSE_NAME), slot_start)

        except requests.HTTPError as e:
            log.error("HTTP-Fehler: %s – %s", e.response.status_code, e.response.text[:300])
            sys.exit(1)
        except Exception as e:
            log.error("Fehler: %s", e)
            sys.exit(1)


if __name__ == "__main__":
    main()
