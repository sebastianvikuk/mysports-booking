#!/usr/bin/env python3
"""
MySports Kurs-Reminder.
Schickt eine HTML-Mail mit Behalten/Stornieren-Buttons.

Umgebungsvariablen:
  MYSPORTS_EMAIL, MYSPORTS_PASSWORD
  COURSE_NAME, COURSE_WEEKDAY, COURSE_HOUR
  SMTP_APP_PASSWORD, NOTIFY_EMAIL
  GITHUB_REPO  (z.B. sebastianvikuk/mysports-booking)
  CANCEL_PAT   (Fine-grained GitHub PAT mit actions:write)
"""

import base64
import logging
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

EMAIL          = os.environ["MYSPORTS_EMAIL"]
PASSWORD       = os.environ["MYSPORTS_PASSWORD"]
COURSE_NAME    = os.environ.get("COURSE_NAME", "Hyrox Training")
COURSE_WEEKDAY = int(os.environ.get("COURSE_WEEKDAY", "1"))
COURSE_HOUR    = int(os.environ.get("COURSE_HOUR", "18"))
SMTP_APP_PASS  = os.environ.get("SMTP_APP_PASSWORD", "")
NOTIFY_EMAIL   = os.environ.get("NOTIFY_EMAIL", EMAIL)
GITHUB_REPO    = os.environ.get("GITHUB_REPO", "sebastianvikuk/mysports-booking")
CANCEL_PAT     = os.environ.get("CANCEL_PAT", "")

BASE_URL = "https://www.mysports.com"
TENANT   = "koerperschmiede"
STUDIO_ID = "1210001450"

HEADERS = {
    "Accept": "*/*",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "x-ms-web-context": "/studio/a29lcnBlcnNjaG1pZWRlOjEyMTAwMDE0NTA%253D",
    "x-nox-client-type": "WEB",
    "x-nox-web-context": "utm_source=mysports.com&utm_medium=direct",
    "x-tenant": TENANT,
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
}


def next_weekday(weekday: int) -> datetime:
    today = datetime.now()
    days_ahead = weekday - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def login(session: requests.Session) -> None:
    token = base64.b64encode(f"{EMAIL}:{PASSWORD}".encode()).decode()
    resp = session.post(
        f"{BASE_URL}/login",
        headers={**HEADERS, "Authorization": f"Basic {token}"},
        json={"tenantAlias": TENANT, "organizationUnitId": int(STUDIO_ID)},
    )
    resp.raise_for_status()


def find_booked_course(session: requests.Session, target: datetime) -> dict | None:
    date_str = target.strftime("%Y-%m-%d")
    url = (
        f"{BASE_URL}/nox/v2/bookableitems/courses/with-canceled"
        f"?startDate={date_str}&endDate={date_str}"
        f"&employeeIds=&organizationUnitIds={STUDIO_ID}"
    )
    resp = session.get(url, headers=HEADERS)
    resp.raise_for_status()
    for c in resp.json():
        if COURSE_NAME.lower() not in c.get("name", "").lower():
            continue
        for slot in c.get("slots", []):
            if f"T{COURSE_HOUR:02d}:" in slot.get("startDateTime", ""):
                if slot.get("alreadyBooked"):
                    return {"id": c["id"], "name": c["name"], "slot": slot}
    return None


def cancel_url(course_id: int) -> str:
    repo = GITHUB_REPO.replace("/", "%2F")
    return (
        f"https://sebastianvikuk.github.io/mysports-booking/"
        f"?cancel={course_id}&pat={CANCEL_PAT}&repo={GITHUB_REPO}"
    )


def send_reminder(course: dict) -> None:
    slot  = course["slot"]
    start = slot["startDateTime"][:16].replace("T", " ")
    cid   = course["id"]
    name  = course["name"]

    html = f"""
<html><body style="font-family:sans-serif;max-width:500px;margin:auto">
<h2 style="color:#333">⏰ Kurs-Erinnerung morgen</h2>
<p style="font-size:1.1em">
  <strong>{name}</strong><br>
  📅 {start} Uhr
</p>
<p>Möchtest du den Kurs behalten oder stornieren?</p>
<table><tr>
  <td style="padding:8px">
    <a style="background:#4CAF50;color:white;padding:12px 24px;text-decoration:none;
              border-radius:4px;font-weight:bold" href="https://www.mysports.com">
      ✅ Behalten
    </a>
  </td>
  <td style="padding:8px">
    <a style="background:#f44336;color:white;padding:12px 24px;text-decoration:none;
              border-radius:4px;font-weight:bold" href="{cancel_url(cid)}">
      ❌ Stornieren
    </a>
  </td>
</tr></table>
<p style="color:#999;font-size:0.85em;margin-top:24px">
  Kurs-ID: {cid} · Automatisch generiert
</p>
</body></html>
"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"⏰ Morgen: {name} um {start[11:]} Uhr"
    msg["From"]    = EMAIL
    msg["To"]      = NOTIFY_EMAIL
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(EMAIL, SMTP_APP_PASS)
        smtp.send_message(msg)
    log.info("Reminder gesendet an %s", NOTIFY_EMAIL)


def main():
    target = next_weekday(COURSE_WEEKDAY)
    log.info("Suche gebuchten Kurs '%s' am %s um %d:00",
             COURSE_NAME, target.strftime("%d.%m.%Y"), COURSE_HOUR)

    with requests.Session() as session:
        try:
            login(session)
            course = find_booked_course(session, target)
            if not course:
                log.warning("Kein gebuchter Kurs gefunden – kein Reminder nötig.")
                return
            log.info("Kurs gefunden: %s (ID %s)", course["name"], course["id"])
            send_reminder(course)
        except Exception as e:
            log.error("Fehler: %s", e)
            sys.exit(1)


if __name__ == "__main__":
    main()
