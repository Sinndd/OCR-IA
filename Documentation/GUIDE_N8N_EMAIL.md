# 📧 Guide d'Automatisation Email + n8n

Ce guide explique comment configurer une adresse mail de test et un workflow n8n pour automatiser l'extraction des BCs reçus par email.

---

## 📋 Table des Matières

1. [Configuration de l'adresse email de test](#1-configuration-de-ladresse-email-de-test)
2. [Installation de n8n](#2-installation-de-n8n)
3. [Configuration du workflow n8n](#3-configuration-du-workflow-n8n)
4. [Détection intelligente des BCs dans les pièces jointes](#4-détection-intelligente-des-bcs)
5. [Tests et validation](#5-tests-et-validation)
6. [Production et monitoring](#6-production-et-monitoring)

---

## 1. Configuration de l'adresse email de test

### Option A : Gmail (Recommandé pour le test)

#### 1.1 Créer un compte Gmail dédié

1. Aller sur https://accounts.google.com/signup
2. Créer un compte avec un nom comme : `ocr-proapro-test@gmail.com`
3. Compléter la configuration

#### 1.2 Activer IMAP

1. Se connecter à Gmail
2. Aller dans **Paramètres** (⚙️) → **Voir tous les paramètres**
3. Onglet **Transfert et POP/IMAP**
4. **Activer IMAP**
5. Sauvegarder

#### 1.3 Créer un mot de passe d'application

🔒 **Important** : Gmail nécessite un mot de passe d'application pour n8n

1. Aller sur https://myaccount.google.com/security
2. Activer la **validation en deux étapes** (obligatoire)
3. Aller dans **Mots de passe des applications**
4. Sélectionner **Autre (nom personnalisé)**
5. Nom : `n8n OCR`
6. Cliquer **Générer**
7. **⚠️ COPIER le mot de passe à 16 caractères** (ex: `abcd efgh ijkl mnop`)

📝 **Conserver précieusement** :
- Email : `ocr-proapro-test@gmail.com`
- Mot de passe app : `abcd efgh ijkl mnop`

---

### Option B : Outlook / Hotmail

#### 1.1 Créer un compte Microsoft

1. Aller sur https://outlook.live.com/owa/
2. Créer un compte : `ocr-proapro-test@outlook.com`

#### 1.2 Activer IMAP

IMAP est activé par défaut sur Outlook.

#### 1.3 Créer un mot de passe d'application

1. Aller sur https://account.microsoft.com/security
2. Section **Sécurité avancée**
3. **Mots de passe d'application** → **Créer un nouveau mot de passe**
4. Nom : `n8n OCR`
5. Copier le mot de passe

📝 **Configuration IMAP Outlook** :
- Serveur : `outlook.office365.com`
- Port : `993`
- SSL : Oui

---

## 2. Installation de n8n

### Option A : Docker (Recommandé)

```bash
# Démarrer n8n avec Docker
docker run -it --rm \
  --name n8n \
  -p 5678:5678 \
  -v ~/.n8n:/home/node/.n8n \
  n8nio/n8n
```

Accéder à : http://localhost:5678

### Option B : npm

```bash
# Installation globale
npm install -g n8n

# Démarrer n8n
n8n start
```

---

## 3. Configuration du workflow n8n

### 3.1 Créer un nouveau workflow

1. Ouvrir n8n (http://localhost:5678)
2. Cliquer sur **New Workflow**
3. Nommer : `OCR - Extraction automatique BCs`

### 3.2 Architecture du workflow

```
┌─────────────────┐
│  IMAP Trigger   │  ← Surveille les emails
└────────┬────────┘
         │
┌────────▼────────┐
│   IF - Filtre   │  ← Vérifie si pièces jointes
└────────┬────────┘
         │
┌────────▼────────┐
│  Split Emails   │  ← Traite chaque email
└────────┬────────┘
         │
┌────────▼────────┐
│ Filter - PJ BC  │  ← Ne garde que les BCs (PDF/HTML)
└────────┬────────┘
         │
┌────────▼────────┐
│  HTTP Request   │  ← Appelle /api/extract
└─────────────────┘
```

### 3.3 Configuration des nodes

#### Node 1 : IMAP Email (Trigger)

**Type** : `IMAP Email` (dans Triggers)

**Configuration** :
- **Host** : `imap.gmail.com` (ou `outlook.office365.com`)
- **Port** : `993`
- **SSL** : `True`
- **User** : `ocr-proapro-test@gmail.com`
- **Password** : `[Mot de passe d'application]`
- **Mailbox** : `INBOX`
- **Options** :
  - **Download Attachments** : `True`
  - **Mark as Read** : `True`
  - **Check for New Messages** : `Every 5 minutes`

#### Node 2 : IF (Condition)

**Type** : `IF`

**Condition** :
- **Value 1** : `{{ $json.attachments }}`
- **Operation** : `is not empty`

Cela évite de traiter les emails sans pièces jointes.

#### Node 3 : Split In Batches

**Type** : `Split In Batches`

**Configuration** :
- **Batch Size** : `1`

Traite chaque email individuellement.

#### Node 4 : Filter (Détecter les BCs)

**Type** : `Function`

**Code JavaScript** :

```javascript
// Filtrer les pièces jointes pour ne garder que les BCs
const attachments = $input.item.json.attachments || [];

// Extensions acceptées
const validExtensions = ['.pdf', '.html', '.htm', '.txt'];

// Mots-clés dans le nom de fichier
const bcKeywords = ['bon', 'commande', 'bc', 'order', 'purchase'];

const bcAttachments = attachments.filter(att => {
  const filename = (att.filename || '').toLowerCase();
  const ext = filename.substring(filename.lastIndexOf('.'));
  
  // Vérifier extension
  if (!validExtensions.includes(ext)) {
    return false;
  }
  
  // Vérifier mots-clés OU considérer tout PDF/HTML comme potentiel BC
  const hasKeyword = bcKeywords.some(kw => filename.includes(kw));
  
  // Critère : soit mot-clé présent, soit PDF/HTML (souvent des BCs)
  return hasKeyword || ['.pdf', '.html', '.htm'].includes(ext);
});

// Retourner uniquement si des BCs détectés
if (bcAttachments.length > 0) {
  return {
    json: {
      ...($input.item.json),
      bcAttachments: bcAttachments,
      emailFrom: $input.item.json.from,
      emailSubject: $input.item.json.subject
    }
  };
} else {
  // Pas de BC détecté, ne rien retourner (node sera skip)
  return null;
}
```

#### Node 5 : HTTP Request (Appel API)

**Type** : `HTTP Request`

**Configuration** :
- **Method** : `POST`
- **URL** : `http://localhost:5001/api/extract`
- **Authentication** : `None` (ou ajouter un token si sécurisé)
- **Body Content Type** : `Multipart-Form Data`

**Body Parameters** :

Pour chaque pièce jointe BC :

```javascript
// Dans "Send Body"
{
  "file": "={{ $json.bcAttachments[0].data }}",
  "metadata": {
    "source": "email",
    "email_from": "={{ $json.emailFrom }}",
    "email_subject": "={{ $json.emailSubject }}",
    "received_at": "={{ $now }}"
  }
}
```

**Options** :
- **Batch Size** : `1` (traiter 1 PJ à la fois)
- **Timeout** : `300000` (5 minutes pour le LLM)

---

### 3.4 Workflow JSON complet (à importer)

Copier ce JSON et l'importer dans n8n :

```json
{
  "name": "OCR - Extraction automatique BCs",
  "nodes": [
    {
      "parameters": {
        "authentication": "generic",
        "host": "imap.gmail.com",
        "port": 993,
        "ssl": true,
        "user": "ocr-proapro-test@gmail.com",
        "password": "VOTRE_MOT_DE_PASSE_APP",
        "options": {
          "downloadAttachments": true,
          "markAsRead": true
        }
      },
      "name": "IMAP Email",
      "type": "n8n-nodes-base.emailReadImap",
      "typeVersion": 2,
      "position": [250, 300]
    },
    {
      "parameters": {
        "conditions": {
          "boolean": [
            {
              "value1": "={{ $json.attachments }}",
              "value2": "={{ null }}"
            }
          ]
        }
      },
      "name": "IF - Has Attachments",
      "type": "n8n-nodes-base.if",
      "typeVersion": 1,
      "position": [450, 300]
    },
    {
      "parameters": {
        "functionCode": "const attachments = $input.item.json.attachments || [];\nconst validExtensions = ['.pdf', '.html', '.htm', '.txt'];\nconst bcKeywords = ['bon', 'commande', 'bc', 'order', 'purchase'];\n\nconst bcAttachments = attachments.filter(att => {\n  const filename = (att.filename || '').toLowerCase();\n  const ext = filename.substring(filename.lastIndexOf('.'));\n  if (!validExtensions.includes(ext)) return false;\n  const hasKeyword = bcKeywords.some(kw => filename.includes(kw));\n  return hasKeyword || ['.pdf', '.html', '.htm'].includes(ext);\n});\n\nif (bcAttachments.length > 0) {\n  return {\n    json: {\n      ...($input.item.json),\n      bcAttachments: bcAttachments,\n      emailFrom: $input.item.json.from,\n      emailSubject: $input.item.json.subject\n    }\n  };\n}\nreturn null;"
      },
      "name": "Filter BC Attachments",
      "type": "n8n-nodes-base.function",
      "typeVersion": 1,
      "position": [650, 300]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "http://localhost:5001/api/extract",
        "sendBody": true,
        "contentType": "multipart-form-data",
        "bodyParameters": {
          "parameters": [
            {
              "name": "file",
              "value": "={{ $json.bcAttachments[0].data }}"
            },
            {
              "name": "metadata",
              "value": "={{ { \"source\": \"email\", \"email_from\": $json.emailFrom, \"email_subject\": $json.emailSubject } }}"
            }
          ]
        },
        "options": {
          "timeout": 300000
        }
      },
      "name": "HTTP Request - Extract",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 3,
      "position": [850, 300]
    }
  ],
  "connections": {
    "IMAP Email": {
      "main": [
        [
          {
            "node": "IF - Has Attachments",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "IF - Has Attachments": {
      "main": [
        [
          {
            "node": "Filter BC Attachments",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Filter BC Attachments": {
      "main": [
        [
          {
            "node": "HTTP Request - Extract",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  }
}
```

---

## 4. Détection intelligente des BCs

### 4.1 Stratégies de détection

Le workflow utilise plusieurs critères pour identifier les BCs :

1. **Extension du fichier** : `.pdf`, `.html`, `.htm`, `.txt`
2. **Mots-clés dans le nom** : `bon`, `commande`, `bc`, `order`, `purchase`
3. **Heuristique** : Tous les PDF/HTML sont considérés comme potentiels BCs

### 4.2 Amélioration : Analyse du contenu

Pour une détection encore plus précise, ajouter un node qui :

```javascript
// Node "Content Analysis" (optionnel)
const attachment = $json.bcAttachments[0];
const content = attachment.dataString || '';

// Vérifier présence de mots-clés métier dans le contenu
const businessKeywords = [
  'commande', 'order', 'livraison', 'delivery',
  'quantité', 'quantity', 'référence', 'code article',
  'établissement', 'client', 'fournisseur'
];

const matchCount = businessKeywords.filter(kw => 
  content.toLowerCase().includes(kw)
).length;

// Si au moins 3 mots-clés, c'est probablement un BC
if (matchCount >= 3) {
  return { json: $json };
}

return null;
```

---

## 5. Tests et validation

### 5.1 Test manuel

1. **Envoyer un email de test** à `ocr-proapro-test@gmail.com`
   - Sujet : `Test BC #1`
   - Pièce jointe : Un PDF de BC

2. **Vérifier n8n**
   - Le workflow devrait se déclencher dans les 5 minutes
   - Voir les logs dans n8n

3. **Vérifier l'API**
   ```bash
   curl http://localhost:5001/api/jobs
   ```

4. **Suivre en temps réel**
   - Ouvrir : http://localhost:5001/monitoring
   - Observer l'avancement du job

### 5.2 Test avec plusieurs emails

Envoyer 3 emails simultanément avec des BCs différents pour tester le traitement parallèle.

---

## 6. Production et monitoring

### 6.1 Sécuriser l'API

Ajouter un token d'authentification :

```python
# Dans app.py
API_TOKEN = "votre-token-secret-123456"

@app.route('/api/extract', methods=['POST'])
def api_extract():
    # Vérifier le token
    token = request.headers.get('Authorization')
    if token != f"Bearer {API_TOKEN}":
        return jsonify({'error': 'Unauthorized'}), 401
    # ... reste du code
```

Dans n8n, ajouter le header :
```
Authorization: Bearer votre-token-secret-123456
```

### 6.2 Monitoring

- **Page monitoring** : http://localhost:5001/monitoring
- **Page failed jobs** : http://localhost:5001/failed-jobs
- **API stats** : http://localhost:5001/api/jobs

### 6.3 Notifications

Ajouter un node **Send Email** dans n8n pour être notifié :

```javascript
// Après HTTP Request
{
  "to": "admin@proapro.com",
  "subject": "✅ BC traité: {{ $json.filename }}",
  "body": "Job ID: {{ $json.job_id }}\nStatut: En cours\nSuivi: http://localhost:5001/monitoring"
}
```

### 6.4 Gestion des échecs

Les jobs échoués sont automatiquement envoyés dans `/failed-jobs` où vous pouvez :
- Voir l'erreur exacte
- Relancer le job en 1 clic
- Corriger les données si nécessaire

---

## 📊 Architecture complète

```
┌──────────────────┐
│  Email entrant   │
│  avec BC (PDF)   │
└────────┬─────────┘
         │
┌────────▼─────────┐
│      n8n         │
│  - Détecte BC    │
│  - Filtre PJ     │
└────────┬─────────┘
         │
         │ POST /api/extract
         │
┌────────▼─────────┐
│   Flask API      │
│  - Crée job      │
│  - Queue async   │
└────────┬─────────┘
         │
┌────────▼─────────┐
│  JobProcessor    │
│  - Thread worker │
│  - SmartExtractor│
└────────┬─────────┘
         │
┌────────▼─────────┐
│   WebSocket      │
│  - Broadcast     │
│  - Real-time UI  │
└────────┬─────────┘
         │
┌────────▼─────────┐
│  /monitoring     │
│  - Suivi live    │
│  - Progress bars │
└──────────────────┘
```

---

## 🚀 Commandes de démarrage

```bash
# 1. Activer l'environnement
cd OCR
source venv/bin/activate

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Démarrer l'API Flask
python3 app.py

# 4. Dans un autre terminal, démarrer n8n
n8n start
# Ou avec Docker:
# docker run -it --rm --name n8n -p 5678:5678 n8nio/n8n

# 5. Ouvrir les pages
# API: http://localhost:5001
# Monitoring: http://localhost:5001/monitoring
# n8n: http://localhost:5678
```

---

## ✅ Checklist de validation

- [ ] Adresse email créée et IMAP activé
- [ ] Mot de passe d'application généré
- [ ] n8n installé et accessible
- [ ] Workflow importé et configuré
- [ ] API Flask démarrée
- [ ] Test email envoyé
- [ ] Job créé dans `/monitoring`
- [ ] JSON généré dans `Données/resultats/`
- [ ] Notifications WebSocket fonctionnelles
- [ ] Failed jobs gérés dans `/failed-jobs`

---

## 🔧 Troubleshooting

### n8n ne reçoit pas les emails

- Vérifier les credentials IMAP
- Tester avec un client mail (Thunderbird, etc.)
- Vérifier le pare-feu (port 993)

### API retourne une erreur 500

- Vérifier les logs Flask dans le terminal
- Vérifier que Ollama tourne : `ollama list`
- Vérifier les fichiers de référence (`agencesPAP.txt`, `clients.txt`)

### Jobs bloqués en "processing"

- Redémarrer Flask (Ctrl+C puis `python3 app.py`)
- Vérifier la queue : `SELECT * FROM jobs WHERE status='processing';`

---

**🎉 Félicitations ! Votre système d'extraction automatique est opérationnel !**
