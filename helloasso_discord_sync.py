#!/usr/bin/env python3
"""
helloasso_discord_sync.py
--------------------------
Récupère la liste des adhérents (membres) d'une association HelloAsso via
l'API v5, et poste les NOUVEAUX adhérents (jamais vus lors des exécutions
précédentes) dans un channel Discord via un webhook.

Conçu pour être lancé périodiquement via cron (ex: toutes les 15 minutes).
Chaque exécution :
  1. S'authentifie auprès de l'API HelloAsso (OAuth2 client_credentials).
  2. Récupère les articles de type "Membership" (adhésions) de l'organisation,
     en ne demandant que ce qui est postérieur à la dernière exécution.
  3. Compare aux IDs déjà connus (stockés dans un fichier d'état local).
  4. Poste sur Discord uniquement les nouveaux adhérents.
  5. Met à jour le fichier d'état.

Documentation API utilisée :
  - Auth          : https://dev.helloasso.com/reference/obtenir-un-access_token
  - Liste articles: https://dev.helloasso.com/reference/get_organizations-organizationslug-items
  - Pagination    : https://dev.helloasso.com/docs/pagination
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

# --------------------------------------------------------------------------
# CONFIGURATION
# --------------------------------------------------------------------------
# Renseignez ces valeurs directement ici, OU définissez les variables
# d'environnement correspondantes (recommandé si le script est versionné
# dans un dépôt git, pour ne pas exposer vos secrets).

HA_CLIENT_ID = os.environ.get("HA_CLIENT_ID", "VOTRE_CLIENT_ID")
HA_CLIENT_SECRET = os.environ.get("HA_CLIENT_SECRET", "VOTRE_CLIENT_SECRET")
HA_ORGANIZATION_SLUG = os.environ.get("HA_ORGANIZATION_SLUG", "votre-association")
HA_FORM_SLUG = os.environ.get("HA_FORM_SLUG", "votre-formulaire")

# Utilisez api.helloasso-sandbox.com pour tester avant de passer en prod.
HA_API_BASE = os.environ.get("HA_API_BASE", "https://api.helloasso.com")

DISCORD_WEBHOOK_URL = os.environ.get(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/VOTRE_WEBHOOK_ID/VOTRE_WEBHOOK_TOKEN",
)

# Fichier utilisé pour se souvenir des adhérents déjà notifiés d'une
# exécution à l'autre. Doit rester sur le même disque entre deux runs cron.
STATE_FILE = os.environ.get(
    "HA_STATE_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "helloasso_state.json"),
)

# Marge de sécurité appliquée à la date de dernière vérification, pour
# rattraper les adhésions dont le paiement (SEPA, chèque...) se valide
# quelques jours après la commande.
LOOKBACK_BUFFER = timedelta(days=3)

# Etats d'articles considérés comme une adhésion "valide"
VALID_ITEM_STATES = ["Processed", "Registered"]

# Nombre max d'embeds Discord par message (limite Discord = 10)
DISCORD_EMBEDS_PER_MESSAGE = 10


# --------------------------------------------------------------------------
# AUTHENTIFICATION HELLOASSO
# --------------------------------------------------------------------------
def get_access_token() -> str:
    """Obtient un access_token OAuth2 (client_credentials)."""
    url = f"{HA_API_BASE}/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": HA_CLIENT_ID,
        "client_secret": HA_CLIENT_SECRET,
    }
    resp = requests.post(url, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


# --------------------------------------------------------------------------
# RÉCUPÉRATION DES ADHÉRENTS
# --------------------------------------------------------------------------
def fetch_membership_items(access_token: str, since: datetime | None) -> list[dict]:
    """
    Récupère tous les articles de type "Membership" (adhésion) de
    l'organisation, en paginant via continuationToken jusqu'à épuisement.
    """
    url = f"{HA_API_BASE}/v5/organizations/{HA_ORGANIZATION_SLUG}/forms/Membership/{HA_FORM_SLUG}/items"
    headers = {"Authorization": f"Bearer {access_token}"}

    base_params = {
        "withDetails": "true",
        "itemStates": VALID_ITEM_STATES,
        "pageSize": 100,
        "sortField": "Date",
        "sortOrder": "Asc",
    }
    if since is not None:
        base_params["from"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    all_items = []
    continuation_token = None

    while True:
        params = dict(base_params)
        if continuation_token:
            params["continuationToken"] = continuation_token

        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()

        page_data = body.get("data", [])
        if not page_data:
            break

        all_items.extend(page_data)

        continuation_token = body.get("pagination", {}).get("continuationToken")
        if not continuation_token:
            break

    return all_items

def pseudo_discord_from_custom_fields(custom_fields: dict) -> str:
    """
    Récupère le pseudo Discord depuis les customFields d'un adhérent.
    Retourne une chaîne vide si le champ n'existe pas.
    """
    for field in custom_fields:
        if field.get("name").startswith("Pseudo discord"):
            return field.get("answer", "")
    return ""

def extract_member_info(item: dict) -> dict:
    """
    Normalise un article renvoyé par l'API en un dict simple.
    L'API peut structurer les infos payeur sous des clés légèrement
    différentes selon le contexte ; on essaie plusieurs chemins connus
    pour rester robuste.
    """
    payer = item.get("payer") or {}
    user = item.get("user") or {}

    first_name = user.get("firstName", "")
    last_name = user.get("lastName", "")
    email = payer.get("email", "")

    tier_name = item.get("tierName") or item.get("name") or "Adhésion"

    pseudo_discord = pseudo_discord_from_custom_fields(item.get("customFields", {}))

    return {
        "id": item.get("id"),
        "name": f"{first_name} {last_name}".strip() or "Nom inconnu",
        "email": email or "Email inconnu",
        "tier": tier_name,
        "pseudo_discord": pseudo_discord or "Pseudo Discord non renseigné",
        "date": item.get("date", ""),
        "raw": item,  # gardé pour debug si besoin
    }


# --------------------------------------------------------------------------
# ÉTAT LOCAL (mémorisation entre deux exécutions)
# --------------------------------------------------------------------------
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"seen_ids": [], "last_check": None}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# DISCORD
# --------------------------------------------------------------------------
def build_embed(member: dict) -> dict:
    return {
        "title": "🎉 Nouvel adhérent !",
        "color": 0x57F287,  # vert Discord
        "fields": [
            {"name": "Nom", "value": member["name"], "inline": True},
            {"name": "Pseudo Discord", "value": member["pseudo_discord"], "inline": True},
            {"name": "Formule", "value": member["tier"], "inline": False},
        ],
        "footer": {"text": "HelloAsso"},
        "timestamp": member["date"] or None,
    }


def post_new_members_to_discord(members: list[dict]) -> None:
    if not members:
        return

    for i in range(0, len(members), DISCORD_EMBEDS_PER_MESSAGE):
        batch = members[i : i + DISCORD_EMBEDS_PER_MESSAGE]
        payload = {"embeds": [build_embed(m) for m in batch]}
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=30)
        if resp.status_code == 429:
            # Rate limit Discord : on attend le temps indiqué puis on retente
            retry_after = resp.json().get("retry_after", 1)
            time.sleep(float(retry_after) + 0.5)
            resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=30)
        resp.raise_for_status()
        time.sleep(1)  # petite marge entre deux messages


# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------
def main():
    initialize_only = "--init" in sys.argv

    state = load_state()
    seen_ids = set(state.get("seen_ids", []))
    last_check_str = state.get("last_check")
    last_check = (
        datetime.fromisoformat(last_check_str) - LOOKBACK_BUFFER
        if last_check_str
        else None
    )

    token = get_access_token()
    raw_items = fetch_membership_items(token, since=last_check)
    members = [extract_member_info(item) for item in raw_items]

    new_members = [m for m in members if m["id"] not in seen_ids]

    if initialize_only:
        print(
            f"[INIT] {len(new_members)} adhérent(s) existant(s) marqué(s) comme "
            "déjà connus (aucun message Discord envoyé)."
        )
    elif new_members:
        print(f"{len(new_members)} nouvel/nouveaux adhérent(s) détecté(s) :")
        for m in new_members:
            print(f"  - {m['name']} <{m['email']}> ({m['tier']})")
        post_new_members_to_discord(new_members)
        print("Postés sur Discord avec succès.")
    else:
        print("Aucun nouvel adhérent depuis la dernière vérification.")

    seen_ids.update(m["id"] for m in members if m["id"] is not None)
    state["seen_ids"] = sorted(seen_ids)
    state["last_check"] = datetime.now(timezone.utc).isoformat()
    save_state(state)


if __name__ == "__main__":
    main()
