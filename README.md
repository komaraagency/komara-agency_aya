# Aya — agent commercial open source

Aya est un agent commercial local pour Komara Agency. Aucun fournisseur propriétaire n'est requis : le bot fonctionne avec ses règles déterministes et `knowledge.json`. Pour ajouter une conversation générative, Aya peut appeler un modèle local via [Ollama](https://ollama.com/) (`OLLAMA_HOST` et `OLLAMA_MODEL`).

## Installation

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python rag_bot.py
```

## Déploiement Railway + Telegram

Le `Procfile` démarre automatiquement le worker Telegram :

```text
worker: python telegram_bot.py
```

Dans Railway, ajoute ces variables dans **Variables** — jamais dans le code :

```text
TELEGRAM_TOKEN=token_fourni_par_BotFather
AYA_ADMIN_ID=identifiant_telegram_numerique_de_l_admin
```

Le code accepte aussi les alias `telegram_token` et `admin_id`. Le bot utilise le polling Telegram, adapté au service **Worker** Railway. Il répond aux messages texte, analyse les PDF envoyés et tente de lire les QR codes envoyés en image.

Dépendances open source :

- `pypdf` pour extraire le texte des PDF ;
- `opencv-python-headless` pour décoder les QR codes ;
- Ollama est facultatif et n'est pas une dépendance Python.

## Actions disponibles

Dans le terminal :

- `/pdf chemin/vers/document.pdf` — extrait le texte localement ;
- `/qr chemin/vers/image.png` — décode le QR code localement ;
- `/devis whatsapp` — calcule un devis à partir du prix enregistré ;
- `/rdv 2026-10-01T14:00:00+01:00 Appel découverte` — crée un brouillon `.ics` importable dans un agenda.
- `/catalog` — envoie le Catalogue V2 commercial au prospect.

Les demandes courtes `catalogue`, `catalog`, `prix`, `tarifs`, `offres`, `montre` et `je veux voir` déclenchent également le Catalogue V2. Il présente les abonnements mensuels Telegram (75 €/mois), WhatsApp (150 €/mois, populaire) et Instagram (100 €/mois), avec leurs fonctionnalités.

## Parcours conversationnel d'Aya

Le moteur `conversation_step()` dans [`actions.py`](actions.py) suit l'état de chaque prospect :

1. **Accroche** — présentation et première question métier ;
2. **Qualification** — activité, besoin, budget, délai ;
3. **Douleur → solution** — identification du blocage puis recommandation ;
4. **Catalogue + boutons** — offres V2 affichées avec choix Telegram ;
5. **Lever d'objections** — budget, délai, confiance ou fonctionnement ;
6. **Closing** — proposition de démarrage sans forcer ;
7. **Handoff / suivi** — transfert humain ou préparation du suivi.

Telegram utilise des boutons inline pour faire avancer le prospect dans ces étapes.

Le Pack Omni reste toujours `sur devis uniquement`. Aya ne fabrique pas de prix.

## Administration par ID

Configurer l'identifiant administrateur dans l'environnement :

```bash
export AYA_ADMIN_ID='votre-identifiant-admin'
```

Depuis une intégration, appeler :

```python
from actions import admin_update
admin_update(admin_id, "instruction", {"text": "Nouvelle règle commerciale"})
admin_update(admin_id, "offer_price", {"offer_id": "whatsapp", "price_eur": 175})
admin_update(admin_id, "faq", {"question": "...", "answer": "..."})
admin_update(admin_id, "business_info", {"installation": "48-72h"})
```

Les modifications sont écrites dans `knowledge.json`. Toute autre valeur d'ID est refusée. Pour une conversation, `answer(message, history, admin_id=...)` accepte également `/admin instruction <nouvelle instruction>`.

Sur Telegram, l'ID admin est vérifié avec l'identifiant numérique de l'expéditeur. Sans correspondance avec `AYA_ADMIN_ID`/`admin_id`, les commandes d'administration sont refusées.

### Répondre depuis l'ID admin

Quand Aya ne trouve pas de réponse fiable, elle transfère le message original à l'ID admin et demande à l'admin de **répondre directement au message transféré**. La réponse est alors :

1. envoyée au client ;
2. ajoutée automatiquement à la FAQ de `knowledge.json` ;
3. disponible pour les prochaines recherches d'Aya.

Commandes admin :

```text
/catalog
/admin instruction Toujours demander le secteur avant le budget.
/apprend Question du client || Réponse validée par Komara
/admin faq Question du client || Réponse validée par Komara
/admin price whatsapp 175
```

Le catalogue est généré depuis les offres de `knowledge.json`, donc les prix affichés restent cohérents avec les devis. Les transferts en attente sont conservés en mémoire du worker ; après un redémarrage Railway, il faudra renvoyer la question si elle n'a pas encore reçu de réponse.

## Règles commerciales

Aya qualifie d'abord quatre champs : activité/nom, besoin, budget et délai. Chaque champ vaut 25 points et le seuil de qualification est de 75. Les demandes juridiques, médicales, de litige, de comptabilité, de site complet ou sensibles sont préparées pour un transfert humain.
