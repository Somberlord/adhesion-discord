#!/usr/bin/env python3
"""
Script à lancer chaque lundi (via cron) : crée deux threads Discord via un
webhook, un pour le mardi et un pour le jeudi survenant 4 semaines plus tard.

IMPORTANT :
Le paramètre "thread_name" de l'API webhook Discord ne fonctionne que si le
webhook est rattaché à un salon de type FORUM (ou "media"). Sur un salon
textuel classique, un webhook ne peut pas créer de thread : il faut alors
passer par un bot (token bot + API REST /channels/{id}/messages puis
/channels/{id}/threads, ou message.create_thread côté discord.py).

Configuration :
    - Variable d'environnement DISCORD_WEBHOOK_URL (obligatoire)
    - Variable d'environnement THREAD_BODY (optionnelle, défaut "Tables jdr")

Planification (cron), tous les lundis à 9h :
    0 9 * * 1 /usr/bin/python3 /chemin/vers/create_discord_threads.py >> /var/log/discord_threads.log 2>&1
"""

import logging
import os
import sys
from datetime import datetime, timedelta
from babel.dates import format_date
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

WEBHOOK_URL = os.environ.get("JDR_WEBHOOK_URL")
BODY_TEXT = os.environ.get("JDR_THREAD_BODY", "Tables jdr")
TAG_ID = os.environ.get("JDR_TAG_ID", "")

# Numérotation Python : lundi=0, mardi=1, mercredi=2, jeudi=3, ...
MARDI = 1
JEUDI = 3


def next_weekday_date(base_date: datetime, weekday: int) -> datetime:
    """
    Renvoie la prochaine date correspondant au jour de semaine `weekday`
    strictement après `base_date` (si base_date tombe déjà sur ce jour,
    on prend l'occurrence suivante, 7 jours plus tard).
    """
    days_ahead = (weekday - base_date.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return base_date + timedelta(days=days_ahead)


def compute_target_dates(today: datetime):
    """Calcule le mardi et le jeudi de cette semaine puis y ajoute 4 semaines."""
    tuesday = next_weekday_date(today, MARDI)
    thursday = next_weekday_date(today, JEUDI)
    return tuesday + timedelta(weeks=4), thursday + timedelta(weeks=4)


def create_discord_thread(webhook_url: str, thread_name: str, content: str):
    """Crée un thread via un webhook Discord pointant vers un salon forum."""
    params = {"wait": "true"}
    payload = {
        "content": content,
        "thread_name": thread_name,
        "applied_tags": [TAG_ID] if TAG_ID else []
    }

    response = requests.post(webhook_url, params=params, json=payload, timeout=15)

    if response.status_code in (200, 204):
        logger.info("Thread créé avec succès : %s", thread_name)
        return response.json() if response.content else None

    logger.error(
        "Échec de création du thread '%s' (HTTP %s) : %s",
        thread_name,
        response.status_code,
        response.text,
    )
    response.raise_for_status()


def main():
    if not WEBHOOK_URL:
        logger.error("La variable d'environnement DISCORD_WEBHOOK_URL n'est pas définie.")
        sys.exit(1)

    today = datetime.now()
    tuesday_date, thursday_date = compute_target_dates(today)

    for date in (tuesday_date, thursday_date):
        formatted_date = format_date(date, "EEEE-d-MMMM", locale='fr_FR')
        title = f"{formatted_date}-soirée-jdr"
        create_discord_thread(WEBHOOK_URL, title, BODY_TEXT)


if __name__ == "__main__":
    main()