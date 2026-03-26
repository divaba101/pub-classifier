#!/usr/bin/env python3
"""
WEB APP - DOCUMENT CLASSIFIER (Version Améliorée avec Progress Tracking)
Interface web améliorée avec monitoring système, widgets et suivi temps réel
"""

from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
from flask_socketio import SocketIO, emit
import threading
import time
import json
import os
import glob
from pathlib import Path
import logging
from datetime import datetime
import psutil
import shutil

# Import modules
from classifier_engine import DocumentClassifier, ValidationError, SystemError
from structured_logger import get_logger, global_logger
from performance_cache import cache_stats, cache_memory_usage, clear_cache
from ollama_pool import pool_stats, pool_health, clear_pool_cache

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuration
CONFIG_FILE = 'config.json'
STATE_FILE = 'app_state.json'

# Global state
classifier_thread = None
is_running = False
app_state = {
    'source_dir': '',
    'target_dir': '',
    'categories': [],
    'confidence_threshold': 0.7,
    'model': 'mistral',
    'dry_run': False,
    'verbose': False,
    'stats': {
        'total': 0, 'success': 0, 'failed': 0, 'ocr': 0, 'doubtful': 0
    },
    'last_run': None,
    'system_status': {}
}

# Setup logging
logger = get_logger(__name__)

# ==================== SYSTEM MONITORING ====================

class SystemMonitorThread(threading.Thread):
    """Thread de monitoring système en temps réel"""
    
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.running = False
    
    def run(self):
        self.running = True
        while self.running:
            try:
                # System metrics
                cpu_percent = psutil.cpu_percent(interval=1)
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage('/')
                
                # Cache stats
                cache_info = cache_stats()
                cache_memory = cache_memory_usage()
                
                # Pool stats
                pool_info = pool_stats()
                
                # App stats
                log_stats = global_logger.get_log_stats()
                
                # Update app state
                app_state['system_status'] = {
                    'timestamp': datetime.now().isoformat(),
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'memory_available_gb': memory.available / (1024**3),
                    'disk_percent': disk.percent,
                    'disk_free_gb': disk.free / (1024**3),
                    'cache_info': cache_info,
                    'cache_memory': cache_memory,
                    'pool_info': pool_info,
                    'log_stats': log_stats,
                    'is_running': is_running
                }
                
                # Emit to WebSocket
                socketio.emit('system_update', app_state['system_status'])
                
            except Exception as e:
                logger.error(f"System monitoring error: {e}")
            
            time.sleep(2)  # Update every 2 seconds
    
    def stop(self):
        self.running = False

# ==================== FLASK ROUTES ====================

@app.route('/')
def index():
    """Page principale avec interface améliorée"""
    load_config()
    return render_template('index_improved.html', state=app_state)

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """API pour la configuration"""
    if request.method == 'GET':
        load_config()
        return jsonify(app_state)
    
    elif request.method == 'POST':
        data = request.json
        
        # Validate required fields
        required_fields = ['source_dir', 'target_dir', 'categories']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Champ requis manquant: {field}'}), 400
        
        # Update config
        app_state.update({
            'source_dir': data['source_dir'],
            'target_dir': data['target_dir'],
            'categories': data['categories'],
            'confidence_threshold': float(data.get('confidence_threshold', 0.7)),
            'model': data.get('model', 'mistral'),
            'dry_run': bool(data.get('dry_run', False)),
            'verbose': bool(data.get('verbose', False))
        })
        
        save_config()
        return jsonify({'success': True})

@app.route('/api/start', methods=['POST'])
def api_start():
    """Démarre le traitement avec progress tracking"""
    global classifier_thread, is_running
    
    if is_running:
        return jsonify({'error': 'Le traitement est déjà en cours'}), 400
    
    try:
        # Validate config
        if not app_state['source_dir'] or not app_state['target_dir']:
            return jsonify({'error': 'Veuillez configurer les dossiers source et cible'}), 400
        
        if not app_state['categories']:
            return jsonify({'error': 'Veuillez définir des catégories'}), 400
        
        # Start classifier
        def run_classifier():
            global is_running
            try:
                def progress_callback(event_name, event_data):
                    """Forward progress events to WebSocket"""
                    try:
                        socketio.emit(event_name, event_data)
                    except Exception as e:
                        logger.error(f"Failed to emit progress: {e}")
                
                def log_callback(msg):
                    """Callback pour les logs WebSocket (legacy)"""
                    try:
                        if isinstance(msg, dict) and 'message' in msg:
                            socketio.emit('log', msg)
                        else:
                            socketio.emit('log', msg)
                    except Exception as e:
                        logger.error(f"Error sending log to WebSocket: {e}")
                
                # Emit classification start
                socketio.emit('classification_start')
                
                classifier = DocumentClassifier(
                    source_dir=app_state['source_dir'],
                    target_dir=app_state['target_dir'],
                    categories=app_state['categories'],
                    confidence_threshold=app_state['confidence_threshold'],
                    model=app_state['model'],
                    dry_run=app_state['dry_run'],
                    verbose=app_state['verbose'],
                    log_callback=log_callback,
                    progress_callback=progress_callback
                )
                
                stats = classifier.run()
                app_state['stats'] = stats
                app_state['last_run'] = datetime.now().isoformat()
                is_running = False
                
                socketio.emit('classification_complete', stats)
                logger.info("Classification completed successfully")
                
            except Exception as e:
                logger.error(f"Classification error: {e}")
                socketio.emit('classification_error', {'error': str(e)})
                is_running = False
        
        classifier_thread = threading.Thread(target=run_classifier)
        classifier_thread.daemon = True
        classifier_thread.start()
        is_running = True
        
        return jsonify({'success': True, 'message': 'Traitement démarré'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def api_stop():
    """Arrête le traitement"""
    global is_running
    
    if not is_running:
        return jsonify({'error': 'Aucun traitement en cours'}), 400
    
    # Try to stop gracefully
    is_running = False
    
    # Kill thread if possible
    if classifier_thread and classifier_thread.is_alive():
        # Note: Python threads cannot be forcibly killed safely
        # The thread will stop on its next iteration
        pass
    
    return jsonify({'success': True, 'message': 'Arrêt demandé'})

@app.route('/api/status')
def api_status():
    """Retourne le statut du système"""
    return jsonify({
        'is_running': is_running,
        'stats': app_state['stats'],
        'system_status': app_state.get('system_status', {}),
        'config': {
            'source_dir': app_state['source_dir'],
            'target_dir': app_state['target_dir'],
            'categories': app_state['categories'],
            'confidence_threshold': app_state['confidence_threshold']
        }
    })

@app.route('/api/logs')
def api_logs():
    """Retourne les logs récents"""
    try:
        log_file = Path(global_logger.log_dir) / f"{global_logger.app_name.lower()}.json"
        logs = []
        
        if log_file.exists():
            with open(log_file, 'r') as f:
                lines = f.readlines()[-100:]  # Last 100 lines
                for line in lines:
                    if line.strip():
                        try:
                            logs.append(json.loads(line))
                        except:
                            pass
        
        return jsonify({'logs': logs})
        
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/logs/files')
def api_logs_files():
    """Retourne la liste des fichiers de logs disponibles"""
    try:
        log_dir = Path("/tmp/classifier_logs")
        files = []
        
        logger.info(f"Checking log directory: {log_dir}")
        logger.info(f"Directory exists: {log_dir.exists()}")
        
        if log_dir.exists():
            logger.info(f"Directory contents: {list(log_dir.iterdir())}")
            
            for log_file in log_dir.glob("*.json"):
                logger.info(f"Found log file: {log_file}")
                try:
                    file_info = {
                        'name': log_file.name,
                        'path': str(log_file),
                        'size': log_file.stat().st_size,
                        'modified': datetime.fromtimestamp(log_file.stat().st_mtime).isoformat()
                    }
                    files.append(file_info)
                    logger.info(f"Added file info: {file_info}")
                except Exception as e:
                    logger.error(f"Error processing file {log_file}: {e}")
        
        logger.info(f"Returning {len(files)} files")
        return jsonify({'files': files})
        
    except Exception as e:
        logger.error(f"Error in api_logs_files: {e}")
        return jsonify({'error': str(e)})

@app.route('/api/logs/file/<filename>')
def api_logs_file_content(filename):
    """Retourne le contenu d'un fichier de log spécifique"""
    try:
        logger.info(f"API endpoint called for file: {filename}")
        
        log_dir = Path("/tmp/classifier_logs")
        log_file = log_dir / filename
        
        logger.info(f"Looking for log file: {log_file}")
        
        if not log_file.exists():
            logger.warning(f"File not found: {log_file}")
            return jsonify({'error': 'File not found'}), 404
        
        logger.info(f"File exists, reading content...")
        logs = []
        with open(log_file, 'r') as f:
            content = f.read().strip()
            
        logger.info(f"Content length: {len(content)} characters")
        
        if not content:
            logger.info("File is empty")
            return jsonify({'filename': filename, 'logs': []})
            
        # Parser selon le format
        if content.startswith('[') and content.endswith(']'):
            logger.info("Format tableau JSON détecté")
            # Format tableau JSON
            logs_data = json.loads(content)
            if isinstance(logs_data, list):
                logs = logs_data
            else:
                logs = [logs_data] if logs_data else []
        else:
            logger.info("Format objet JSON par ligne détecté")
            # Format un objet JSON par ligne avec indentation
            lines = content.split('\n')
            logger.info(f"Total lines: {len(lines)}")
            
            current_object_lines = []
            brace_count = 0
            
            for i, line in enumerate(lines):
                if not line.strip():
                    continue
                
                current_object_lines.append(line)
                
                # Compter les accolades pour détecter la fin d'un objet
                brace_count += line.count('{') - line.count('}')
                
                # Si on a un nombre équilibré d'accolades, on a probablement un objet complet
                if brace_count == 0 and current_object_lines:
                    try:
                        log_entry = json.loads('\n'.join(current_object_lines))
                        logs.append(log_entry)
                        current_object_lines = []
                        if len(logs) <= 3:  # Log first 3 entries
                            logger.info(f"Parsed log entry {len(logs)}: {log_entry.get('message', 'No message')[:50]}")
                    except json.JSONDecodeError as e:
                        logger.warning(f"JSON decode error at line {i}: {e}")
                        logger.warning(f"Content: {repr(line[:100])}")
                        # Continuer à accumuler les lignes
                        pass
            
            # Traiter le dernier objet accumulé
            if current_object_lines:
                try:
                    log_entry = json.loads('\n'.join(current_object_lines))
                    logs.append(log_entry)
                    logger.info(f"Parsed final log entry: {log_entry.get('message', 'No message')[:50]}")
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON decode error for final object: {e}")
        
        logger.info(f"Successfully parsed {len(logs)} log entries")
        
        # Test simple response
        if len(logs) == 0:
            logger.warning("No logs parsed, returning empty array")
            return jsonify({'filename': filename, 'logs': []})
        
        # Return the logs
        response = {'filename': filename, 'logs': logs}
        logger.info(f"Returning response with {len(logs)} logs")
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Error in api_logs_file_content: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': str(e)})

@app.route('/api/test/logs')
def api_test_logs():
    """Endpoint de test pour vérifier le parsing des logs"""
    try:
        logger.info("Test endpoint called")
        
        log_dir = Path("/tmp/classifier_logs")
        log_file = log_dir / "documentclassifier.json"
        
        if not log_file.exists():
            return jsonify({'error': 'File not found'}), 404
        
        logs = []
        with open(log_file, 'r') as f:
            content = f.read().strip()
            
        if not content:
            return jsonify({'logs': []})
            
        # Parser simple
        lines = content.split('\n')
        current_object_lines = []
        brace_count = 0
        
        for line in lines:
            if not line.strip():
                continue
            
            current_object_lines.append(line)
            brace_count += line.count('{') - line.count('}')
            
            if brace_count == 0 and current_object_lines:
                try:
                    log_entry = json.loads('\n'.join(current_object_lines))
                    logs.append(log_entry)
                    current_object_lines = []
                except json.JSONDecodeError:
                    pass
        
        return jsonify({'test': True, 'parsed_logs': len(logs), 'first_log': logs[0] if logs else None})
        
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/cache/clear', methods=['POST'])
def api_cache_clear():
    """Nettoie le cache"""
    try:
        clear_cache()
        clear_pool_cache()
        return jsonify({'success': True, 'message': 'Cache nettoyé'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/files')
def api_files():
    """Liste les fichiers dans le dossier source"""
    try:
        source_dir = app_state['source_dir']
        if not source_dir or not os.path.exists(source_dir):
            return jsonify({'files': []})
        
        files = []
        for root, _, filenames in os.walk(source_dir):
            for filename in filenames:
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, source_dir)
                size = os.path.getsize(filepath)
                mtime = os.path.getmtime(filepath)
                
                files.append({
                    'name': filename,
                    'path': rel_path,
                    'size': size,
                    'size_mb': round(size / (1024*1024), 2),
                    'modified': datetime.fromtimestamp(mtime).isoformat(),
                    'extension': Path(filename).suffix.lower()
                })
        
        # Sort by modification time
        files.sort(key=lambda x: x['modified'], reverse=True)
        
        return jsonify({'files': files})
        
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/categories/test', methods=['POST'])
def api_test_categories():
    """Teste la validité des catégories"""
    data = request.json
    categories = data.get('categories', [])
    
    errors = []
    for cat in categories:
        if not cat or not cat.strip():
            errors.append(f"Catégorie vide: {cat}")
        if any(c in cat for c in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']):
            errors.append(f"Nom invalide: {cat}")
    
    if errors:
        return jsonify({'valid': False, 'errors': errors})
    
    return jsonify({'valid': True})

# ==================== UTILITY FUNCTIONS ====================

def load_config():
    """Charge la configuration depuis le fichier"""
    global app_state
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                app_state.update(config)
        except Exception as e:
            logger.error(f"Error loading config: {e}")

def save_config():
    """Sauvegarde la configuration"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(app_state, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving config: {e}")

def load_state():
    """Charge l'état de l'application"""
    global app_state
    
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                app_state.update(state)
        except Exception as e:
            logger.error(f"Error loading state: {e}")

def save_state():
    """Sauvegarde l'état de l'application"""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(app_state, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving state: {e}")

# ==================== SOCKET.IO EVENTS ====================

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info('Client connected')
    emit('system_update', app_state.get('system_status', {}))

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info('Client disconnected')

@socketio.on('request_status')
def handle_status_request():
    """Handle status request from client"""
    emit('system_update', app_state.get('system_status', {}))

# ==================== CLI INTERFACE ====================

def run_web_server(host='0.0.0.0', port=5000, debug=False):
    """Lance le serveur web"""
    # Start system monitoring
    monitor_thread = SystemMonitorThread()
    monitor_thread.start()
    
    try:
        logger.info(f"Starting web server on {host}:{port}")
        socketio.run(app, host=host, port=port, debug=debug)
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    finally:
        monitor_thread.stop()

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--debug', action='store_true')
    
    args = parser.parse_args()
    
    run_web_server(args.host, args.port, args.debug)
