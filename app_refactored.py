#!/usr/bin/env python3
"""
FLASK WEB APP - Document Classifier Control Panel
Interface web pour contrôler le moteur de classification
"""
import json
import logging
import os
import psutil
import subprocess
import threading
from functools import wraps

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from flask_socketio import SocketIO
from flasgger import Swagger
from dotenv import load_dotenv

# Import du moteur de classification
from classifier_engine import DocumentClassifier

# ==================== CONFIGURATION ====================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

app = Flask(__name__)
load_dotenv()
CORS(app)

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'classifier_secret_key')
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

swagger = Swagger(app)

# ==================== CONSTANTES ====================

CONFIG_FILE = 'config.json'
PID_FILE = 'classifier.pid'

# Authentication
AUTH_USER = os.getenv('APP_USER', 'admin')
AUTH_PASS = os.getenv('APP_PASS', 'admin')

# État global du service
classifier_instance = None
classifier_thread = None
classifier_lock = threading.Lock()

# ==================== AUTHENTIFICATION ====================

def check_auth(username, password):
    return username == AUTH_USER and password == AUTH_PASS

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return jsonify({"error": "Authentification requise"}), 401, {
                'WWW-Authenticate': 'Basic realm="Login Required"'
            }
        return f(*args, **kwargs)
    return decorated

# ==================== UTILITAIRES ====================

def load_config():
    """Charge la configuration depuis config.json"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None

def save_config(config_data):
    """Sauvegarde la configuration"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        logging.error(f"Erreur sauvegarde config: {e}")
        return False

def is_classifier_running():
    """Vérifie si le classifier tourne"""
    global classifier_instance, classifier_thread
    return classifier_thread is not None and classifier_thread.is_alive()

def log_to_websocket(message):
    """Callback pour envoyer les logs au WebSocket"""
    socketio.emit('new_log_line', {'log': message})

# ==================== ROUTES WEB ====================

@app.route('/')
@login_required
def index():
    """Page principale"""
    return render_template('index.html')

@app.route('/api/config', methods=['GET'])
@login_required
def get_config():
    """
    Retourne la configuration actuelle
    ---
    tags:
      - Configuration
    responses:
      200:
        description: Configuration JSON
      404:
        description: Config non trouvée
    """
    config = load_config()
    if config:
        return jsonify(config)
    return jsonify({"error": "Configuration non trouvée"}), 404

@app.route('/api/config', methods=['POST'])
@login_required
def save_config_endpoint():
    """
    Sauvegarde la configuration
    ---
    tags:
      - Configuration
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            source_directory:
              type: string
            target_directory:
              type: string
            categories:
              type: array
              items:
                type: string
            confidence_threshold:
              type: number
            model:
              type: string
    responses:
      200:
        description: Config sauvegardée
      400:
        description: Données invalides
    """
    new_config = request.json
    if not new_config:
        return jsonify({"error": "Données manquantes"}), 400
    
    # Validation basique
    required_fields = ['source_directory', 'target_directory', 'categories']
    for field in required_fields:
        if field not in new_config:
            return jsonify({"error": f"Champ manquant: {field}"}), 400
    
    if save_config(new_config):
        return jsonify({"message": "Configuration sauvegardée"})
    
    return jsonify({"error": "Erreur de sauvegarde"}), 500

@app.route('/api/service/status', methods=['GET'])
@login_required
def service_status():
    """
    Status du classifier
    ---
    tags:
      - Service
    responses:
      200:
        description: Status actuel
    """
    running = is_classifier_running()
    
    stats = {}
    if classifier_instance:
        stats = classifier_instance.stats
    
    return jsonify({
        "status": "running" if running else "stopped",
        "stats": stats
    })

@app.route('/api/service/start', methods=['POST'])
@login_required
def start_service():
    """
    Démarre le classifier
    ---
    tags:
      - Service
    parameters:
      - name: body
        in: body
        schema:
          type: object
          properties:
            dry_run:
              type: boolean
            verbose:
              type: boolean
            model:
              type: string
    responses:
      200:
        description: Service démarré
      409:
        description: Déjà en cours
      500:
        description: Erreur
    """
    global classifier_instance, classifier_thread
    
    if is_classifier_running():
        return jsonify({"error": "Service déjà en cours"}), 409
    
    # Load config
    config = load_config()
    if not config:
        return jsonify({"error": "Configuration manquante"}), 500
    
    # Parse options
    options = request.json or {}
    dry_run = options.get('dry_run', False)
    verbose = options.get('verbose', False)
    model = options.get('model', config.get('model', 'mistral'))
    
    try:
        with classifier_lock:
            # Create classifier instance
            classifier_instance = DocumentClassifier(
                source_dir=config['source_directory'],
                target_dir=config['target_directory'],
                categories=config['categories'],
                confidence_threshold=config.get('confidence_threshold', 0.7),
                model=model,
                dry_run=dry_run,
                verbose=verbose,
                log_callback=log_to_websocket
            )
            
            # Run in thread
            def run_classifier():
                try:
                    logging.info("🚀 Démarrage du classifier...")
                    classifier_instance.run()
                    logging.info("✅ Classifier terminé")
                except Exception as e:
                    logging.error(f"❌ Erreur classifier: {e}")
                finally:
                    # Cleanup
                    with classifier_lock:
                        global classifier_thread
                        classifier_thread = None
            
            classifier_thread = threading.Thread(target=run_classifier, daemon=True)
            classifier_thread.start()
        
        return jsonify({
            "status": "starting",
            "options": {
                "dry_run": dry_run,
                "verbose": verbose,
                "model": model
            }
        })
    
    except Exception as e:
        logging.error(f"Erreur démarrage: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/service/stop', methods=['POST'])
@login_required
def stop_service():
    """
    Arrête le classifier
    ---
    tags:
      - Service
    responses:
      200:
        description: Service arrêté
      404:
        description: Service non actif
    """
    global classifier_thread
    
    if not is_classifier_running():
        return jsonify({"error": "Service non actif"}), 404
    
    # Note: Thread Python ne peuvent pas être "tués" proprement
    # On peut juste attendre qu'ils se terminent
    # Pour une vraie interruption, il faudrait un système de signaux
    
    return jsonify({
        "message": "Le service se terminera à la fin du fichier en cours",
        "status": "stopping"
    })

@app.route('/api/browse_classified', methods=['GET'])
@login_required
def browse_classified():
    """
    Liste les fichiers classés
    ---
    tags:
      - Files
    responses:
      200:
        description: Arborescence
      404:
        description: Dossier invalide
    """
    config = load_config()
    if not config:
        return jsonify({"error": "Config manquante"}), 500
    
    target_dir = config.get('target_directory')
    if not target_dir or not os.path.isdir(target_dir):
        return jsonify({"error": f"Dossier invalide: {target_dir}"}), 404
    
    tree = {}
    for root, dirs, files in os.walk(target_dir):
        path = root.replace(target_dir, '').lstrip(os.sep)
        path_parts = path.split(os.sep) if path else []
        
        current_level = tree
        for part in path_parts:
            current_level = current_level.setdefault(part, {})
        
        current_level['_files'] = sorted(files)
        for d in sorted(dirs):
            if d not in current_level:
                current_level[d] = {}
    
    return jsonify(tree)

@app.route('/api/categories', methods=['GET'])
@login_required
def get_categories():
    """
    Liste des catégories avec statistiques
    ---
    tags:
      - Categories
    responses:
      200:
        description: Stats par catégorie
    """
    config = load_config()
    if not config:
        return jsonify({"error": "Config manquante"}), 500
    
    target_dir = config['target_directory']
    categories = config['categories']
    
    stats = {}
    for category in categories:
        cat_dir = os.path.join(target_dir, category)
        if os.path.isdir(cat_dir):
            files = [f for f in os.listdir(cat_dir) if os.path.isfile(os.path.join(cat_dir, f))]
            stats[category] = len(files)
        else:
            stats[category] = 0
    
    # Dossiers spéciaux
    for special in ['TO_OCR', 'DOUBTFUL']:
        special_dir = os.path.join(target_dir, special)
        if os.path.isdir(special_dir):
            files = [f for f in os.listdir(special_dir) if os.path.isfile(os.path.join(special_dir, f))]
            stats[special] = len(files)
    
    return jsonify(stats)

# ==================== WEBSOCKET ====================

@socketio.on('connect')
def handle_connect():
    """Client WebSocket connecté"""
    logging.info("Client WebSocket connecté")
    socketio.emit('connection_status', {'message': 'Connecté au serveur'})

@socketio.on('disconnect')
def handle_disconnect():
    """Client WebSocket déconnecté"""
    logging.info("Client WebSocket déconnecté")

# ==================== MAIN ====================

if __name__ == '__main__':
    logging.info("="*70)
    logging.info("🚀 DOCUMENT CLASSIFIER - Web Control Panel")
    logging.info(f"   URL: http://0.0.0.0:5500")
    logging.info(f"   Auth: {AUTH_USER} / {AUTH_PASS}")
    logging.info("="*70)
    
    socketio.run(
        app,
        host='0.0.0.0',
        port=5500,
        debug=False,
        allow_unsafe_werkzeug=True
    )
