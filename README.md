# Sync HelloAsso → Discord

Ce script récupère les adhérents (adhésions) de votre association sur
HelloAsso et poste automatiquement les **nouveaux** adhérents dans un
channel Discord.

## 1. Installation

```bash
pip install -r requirements.txt
```

## 2. Récupérer une clé API HelloAsso

1. Connectez-vous à votre back-office association sur HelloAsso.
2. Rendez-vous dans **Paramètres > API** (ou "Développeurs") pour créer un
   client API. Vous obtiendrez un `client_id` et un `client_secret`.
   Doc officielle : https://dev.helloasso.com/docs/obtenir-une-clé-api
3. Votre client doit disposer du privilège **AccessTransactions** (donné par
   défaut à un client "association").

## 3. Créer un webhook Discord

Dans Discord : paramètres du salon → **Intégrations** → **Webhooks** →
**Nouveau webhook**. Copiez l'URL du webhook (elle ressemble à
`https://discord.com/api/webhooks/123456/abcdef...`).

## 4. Configurer le script

Le plus simple et le plus sûr est de passer par des variables
d'environnement (pour ne jamais mettre vos secrets dans un fichier versionné
sur git). Créez un fichier `.env` (ou exportez-les dans votre shell) :

```bash
export HA_CLIENT_ID="xxxxxxxxxxxxxxxxxxxx"
export HA_CLIENT_SECRET="xxxxxxxxxxxxxxxxxxxx"
export HA_ORGANIZATION_SLUG="nom-de-votre-association"   # le slug dans l'URL HelloAsso
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/xxxx/xxxx"
```

Vous pouvez aussi éditer directement les valeurs en haut de
`helloasso_discord_sync.py` si vous préférez.

Pour tester d'abord sans toucher à vos vraies données, utilisez le
bac à sable HelloAsso :

```bash
export HA_API_BASE="https://api.helloasso-sandbox.com"
```

## 5. Premier lancement : initialisation

**Important** : lors du tout premier lancement, le script va voir *tous*
vos adhérents existants comme "nouveaux". Pour éviter de spammer votre
Discord avec l'historique complet, lancez d'abord le script en mode
initialisation, qui marque tout le monde comme "déjà connu" sans rien
poster :

```bash
python3 helloasso_discord_sync.py --init
```

## 6. Lancement normal

```bash
python3 helloasso_discord_sync.py
```

À chaque exécution, seuls les adhérents jamais vus lors des exécutions
précédentes sont postés sur Discord. Un fichier `helloasso_state.json` est
créé à côté du script pour se souvenir de qui a déjà été notifié — ne le
supprimez pas (sinon tout le monde sera reposté au prochain lancement).

## 7. Automatiser avec cron (Linux/Mac)

Éditez votre crontab :

```bash
crontab -e
```

Ajoutez une ligne pour lancer le script toutes les 15 minutes, par exemple
(adaptez les chemins et pensez à exporter vos variables d'environnement
dans le script, ou utilisez un fichier `.env` chargé par un petit wrapper) :

```cron
*/15 * * * * HA_CLIENT_ID="xxx" HA_CLIENT_SECRET="xxx" HA_ORGANIZATION_SLUG="xxx" DISCORD_WEBHOOK_URL="xxx" /usr/bin/python3 /chemin/vers/helloasso_discord_sync.py >> /chemin/vers/helloasso_sync.log 2>&1
```

Astuce plus propre : mettez vos variables dans un fichier `.env` et
utilisez un petit script wrapper `run.sh` :

```bash
#!/bin/bash
set -a
source /chemin/vers/.env
set +a
/usr/bin/python3 /chemin/vers/helloasso_discord_sync.py
```

Puis dans le cron :

```cron
*/15 * * * * /chemin/vers/run.sh >> /chemin/vers/helloasso_sync.log 2>&1
```

## Notes

- Le script ne considère comme adhésions que les articles de type
  `Membership`, avec un état `Processed` ou `Registered` (paiement validé).
- Une marge de sécurité de 3 jours (`LOOKBACK_BUFFER`) est appliquée à la
  date de dernière vérification pour rattraper les paiements qui se
  valident après coup (SEPA, chèque...). Les doublons sont filtrés par
  l'ID d'article, donc c'est sans risque.
- Les noms de champs exacts renvoyés par l'endpoint
  `/v5/organizations/{slug}/items` ne sont pas totalement documentés dans
  le Swagger public ; la fonction `extract_member_info` essaie plusieurs
  chemins connus. Si les noms ou emails remontent vides sur votre compte,
  lancez le script une fois, inspectez `item["raw"]` (ajoutez un
  `print(json.dumps(item, indent=2))` temporaire) et ajustez la fonction
  en conséquence.
