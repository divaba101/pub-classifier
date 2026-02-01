# DOCUMENT CLASSIFIER - WEB APP
## Installation & Déploiement Complet

---

## 📦 STRUCTURE DU PROJET

```
classify-app/
├── app_refactored.py          # Flask API principale
├── classifier_engine.py        # Moteur de classification
├── ocr_processor.py            # Handler OCR
├── config.json                 # Configuration
├── .env                        # Variables d'environnement
├── requirements.txt            # Dépendances Python
├── templates/
│   └── index.html             # Interface web
└── README.md                  # Cette doc
```

---

## ⚙️ INSTALLATION

### 1. Dépendances Système

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
sudo apt install -y tesseract-ocr tesseract-ocr-fra
sudo apt install -y poppler-utils  # Pour pdftoppm

# macOS
brew install python3 tesseract tesseract-lang poppler
```

### 2. Environnement Python

```bash
# Crée le projet
mkdir -p ~/classify-app
cd ~/classify-app

# Virtual env
python3 -m venv .venv
source .venv/bin/activate

# Dépendances
pip install flask flask-cors flask-socketio flasgger
pip install python-dotenv psutil
pip install ollama pypdf openpyxl xlrd python-docx
```

### 3. Fichier `.env`

```bash
cat > .env << 'EOF'
SECRET_KEY=your_secret_key_here_change_this
APP_USER=admin
APP_PASS=secure_password_change_this
EOF
```

### 4. Configuration Initiale

```bash
cat > config.json << 'EOF'
{
    "source_directory": "/mnt/marge/docs/iCloud",
    "target_directory": "/mnt/marge/docs",
    "categories": [
        "facture",
        "contrat",
        "administratif",
        "personnel",
        "medical",
        "legal",
        "CV",
        "autre"
    ],
    "confidence_threshold": 0.7,
    "model": "mistral"
}
EOF
```

### 5. Ollama (IA)

```bash
# Installation Ollama
curl https://ollama.ai/install.sh | sh

# Télécharge le modèle
ollama pull mistral

# Vérifie
ollama list
```

---

## 🚀 LANCEMENT

### Mode Manuel

```bash
cd ~/classify-app
source .venv/bin/activate
python3 app_refactored.py
```

Accède à: `http://localhost:5500`  
Auth: `admin` / `secure_password_change_this`

### Mode Service (systemd)

```bash
sudo tee /etc/systemd/system/classifier.service << 'EOF'
[Unit]
Description=Document Classifier Web App
After=network.target

[Service]
Type=simple
User=jack
WorkingDirectory=/home/jack/classify-app
Environment="PATH=/home/jack/classify-app/.venv/bin"
ExecStart=/home/jack/classify-app/.venv/bin/python3 app_refactored.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Active
sudo systemctl daemon-reload
sudo systemctl enable classifier
sudo systemctl start classifier

# Status
sudo systemctl status classifier

# Logs
journalctl -u classifier -f
```

---

## 📖 UTILISATION

### Interface Web

1. **Configuration**
   - Définir dossiers source/cible
   - Ajuster seuil de confiance
   - Ajouter/supprimer catégories
   - Sauvegarder

2. **Lancement**
   - Cocher "Dry Run" pour tester sans déplacer
   - Cocher "Verbose" pour logs détaillés
   - Cliquer "Démarrer"
   - Suivre les logs en temps réel

3. **Monitoring**
   - Stats live (total, succès, échecs)
   - Logs WebSocket temps réel
   - Statut du service

### CLI Direct

```bash
# Test rapide
python3 classifier_engine.py \
  --source /mnt/marge/docs/iCloud \
  --target /mnt/marge/docs \
  --categories facture contrat administratif autre \
  --dry-run \
  --verbose

# Production
python3 classifier_engine.py \
  --source /mnt/marge/docs/iCloud \
  --target /mnt/marge/docs \
  --categories facture contrat administratif autre \
  --threshold 0.7
```

---

## 🔧 CONFIGURATION AVANCÉE

### Ajout de Catégories Dynamiques

Les catégories sont créées automatiquement dans le dossier cible.  
Elles ne sont **jamais supprimées** automatiquement.

**Via Web:**
1. Aller dans "Catégories"
2. Taper le nom → Entrée
3. Sauvegarder la config

**Via config.json:**
```json
{
  "categories": [
    "facture",
    "nouvelle_categorie",
    "autre"
  ]
}
```

### OCR Workflow

**Fichiers concernés:**
- PDFs scannés (sans texte extractible)
- Images (PNG, JPG, etc.)

**Process:**
1. Classifier détecte pas de texte → marque `[SCANNED_PDF]`
2. Appelle `ocr_processor.py` avec Tesseract
3. Lit le texte OCR généré
4. Classifie avec IA
5. Déplace le fichier **original** (pas l'OCR)

**Si OCR échoue:**
- Fichier déplacé dans `TO_OCR/` pour traitement manuel

### Seuil de Confiance

- **70-80%**: Équilibre standard
- **80-90%**: Plus strict, plus de fichiers en DOUBTFUL
- **60-70%**: Plus permissif, risque d'erreurs

### Modèles IA

**Disponibles (via Ollama):**
- `mistral` (recommandé): rapide, précis
- `llama2`: plus lent, très précis
- `codellama`: bon pour docs techniques

**Téléchargement:**
```bash
ollama pull mistral
ollama pull llama2
```

---

## 📂 DOSSIERS SPÉCIAUX

### Structure Cible

```
target_directory/
├── facture/          # Catégorie normale
├── contrat/          # Catégorie normale
├── TO_OCR/           # Fichiers nécessitant OCR
└── DOUBTFUL/         # Confiance < seuil
```

### TO_OCR

Fichiers qui nécessitent traitement OCR mais où l'OCR auto a échoué.

**Traitement manuel:**
1. Ouvrir le fichier
2. Extraire/corriger le texte
3. Relancer le classifier
4. Le fichier sera reclassifié

### DOUBTFUL

Fichiers classés avec confiance insuffisante.

**Actions possibles:**
- Réduire le seuil de confiance
- Améliorer le prompt IA
- Traiter manuellement

---

## 🔍 TROUBLESHOOTING

### Problème: "Configuration manquante"

```bash
# Vérifie config.json
cat config.json | python3 -m json.tool

# Recrée si besoin
cp config.json.example config.json
```

### Problème: "Ollama not responding"

```bash
# Vérifie Ollama
systemctl status ollama  # ou: ps aux | grep ollama

# Relance
ollama serve &

# Teste
ollama run mistral "test"
```

### Problème: "Download failed (HTML)"

**Cause**: Trust token iCloud expiré

**Solution:**
```bash
# Reconnecte
rclone config reconnect icloud:

# Remonte
fusermount -uz /mnt/marge/docs/iCloud
rclone mount icloud: /mnt/marge/docs/iCloud --daemon
```

### Problème: "OCR failed"

```bash
# Vérifie Tesseract
tesseract --version
tesseract --list-langs  # doit afficher 'fra'

# Installe langues FR si manquant
sudo apt install tesseract-ocr-fra

# macOS
brew install tesseract-lang
```

### Logs Détaillés

```bash
# Flask app
tail -f /var/log/syslog | grep classifier

# Systemd
journalctl -u classifier -f --no-pager

# Mode verbose CLI
python3 classifier_engine.py --verbose ...
```

---

## 🛡️ SÉCURITÉ

### Authentification

Défini dans `.env`:
```
APP_USER=admin
APP_PASS=your_secure_password
```

Change ces valeurs AVANT le premier lancement.

### Réseau

**Accès local uniquement:**
```python
# Dans app_refactored.py
socketio.run(app, host='127.0.0.1', port=5500)
```

**Accès réseau:**
```python
socketio.run(app, host='0.0.0.0', port=5500)
```

Ensuite configure firewall:
```bash
sudo ufw allow 5500/tcp
```

### HTTPS (Production)

Utilise nginx reverse proxy:

```nginx
server {
    listen 443 ssl;
    server_name classifier.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://127.0.0.1:5500;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## 🔄 MISES À JOUR

### Code

```bash
cd ~/classify-app
git pull  # si repo git
# ou: télécharge les nouveaux fichiers

# Relance
sudo systemctl restart classifier
```

### Modèle IA

```bash
# Met à jour Mistral
ollama pull mistral

# Change de modèle
# Dans config.json:
"model": "llama2"
```

---

## 📊 MONITORING

### Prometheus/Grafana (Optionnel)

**Exporter custom:**
```python
from prometheus_client import Counter, Histogram

files_processed = Counter('classifier_files_total', 'Total files processed')
processing_time = Histogram('classifier_processing_seconds', 'Processing time')
```

### Logs Centralisés

**rsyslog:**
```bash
# /etc/rsyslog.d/classifier.conf
:programname, isequal, "classifier" /var/log/classifier.log
```

---

## 💡 OPTIMISATIONS

### Performance

**Parallélisation:**
```python
# Dans classifier_engine.py
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(process_file, f) for f in files]
```

**Cache VFS Rclone:**
```bash
# Monte avec cache agressif
rclone mount icloud: /mnt/marge/docs/iCloud \
  --vfs-cache-mode full \
  --vfs-cache-max-size 50G \
  --daemon
```

### Coûts IA

**Utilise un modèle local** (Ollama) = gratuit  
Alternative cloud (OpenAI) = $$$

---

## 📞 SUPPORT

Issues: [GitHub repo]  
Email: [ton email]  
Docs: [wiki link]

---

## 📝 CHANGELOG

### v2.0 (2026-01)
- ✨ Interface web complète
- 🔍 Support OCR intégré
- 📊 Stats temps réel
- 🏷️ Catégories dynamiques
- 🔄 WebSocket logs

### v1.0 (2025-12)
- 🚀 Version CLI initiale
