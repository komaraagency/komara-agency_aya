# Aya — agent commercial open source

Aya est un agent commercial local pour Komara Agency. Aucun fournisseur propriétaire n'est requis : le bot fonctionne avec ses règles déterministes et `knowledge.json`. Pour ajouter une conversation générative, Aya peut appeler un modèle local via [Ollama](https://ollama.com/) (`OLLAMA_HOST` et `OLLAMA_MODEL`).

## Installation

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python rag_bot.py
```

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

## Règles commerciales

Aya qualifie d'abord quatre champs : activité/nom, besoin, budget et délai. Chaque champ vaut 25 points et le seuil de qualification est de 75. Les demandes juridiques, médicales, de litige, de comptabilité, de site complet ou sensibles sont préparées pour un transfert humain.
