#!/usr/bin/env python3
"""
CLASSIFIER ENGINE - Version Web App Intégrée
Moteur de classification avec support OCR et catégories dynamiques
"""
import os
import json
import shutil
import subprocess
import psutil
import time
from pathlib import Path
import zipfile
import openpyxl
import xlrd 
import ollama
from pypdf import PdfReader
import docx2txt
import logging
import tempfile
import hashlib
from typing import Optional, Dict, List, Tuple, Union
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
import signal
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
# Progress tracking
try:
    from progress_tracker import ProgressTracker, EventType, EventLevel
    PROGRESS_AVAILABLE = True
except ImportError:
    PROGRESS_AVAILABLE = False
    print("⚠️  progress_tracker non disponible - mode compatibilité")

# ==================== SYSTEM ERRORS & VALIDATION ====================

class SystemError(Exception):
    """Erreur système bloquante"""
    pass

class ValidationError(Exception):
    """Erreur de validation configuration"""
    pass

class FileProcessingError(Exception):
    """Erreur lors du traitement d'un fichier"""
    pass

class DiskSpaceError(SystemError):
    """Espace disque insuffisant"""
    pass

class PermissionError(SystemError):
    """Permissions insuffisantes"""
    pass

class DependencyError(SystemError):
    """Dépendance manquante"""
    pass

# ==================== SYSTEM VALIDATION ====================

def validate_system_requirements() -> bool:
    """Valide les prérequis système"""
    errors = []
    
    # Vérifie Ollama
    try:
        result = subprocess.run(['ollama', 'list'], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            errors.append("Ollama non accessible")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        errors.append("Ollama non installé ou non accessible")
    
    # Vérifie Tesseract
    try:
        result = subprocess.run(['tesseract', '--version'], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            errors.append("Tesseract non accessible")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        errors.append("Tesseract non installé")
    
    # Vérifie poppler
    try:
        result = subprocess.run(['pdftoppm', '-v'], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            errors.append("Poppler (pdftoppm) non accessible")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        errors.append("Poppler non installé")
    
    if errors:
        raise SystemError(f"Prérequis système manquants: {'; '.join(errors)}")
    
    return True

def validate_directories(source_dir: str, target_dir: str) -> bool:
    """Valide les dossiers et permissions"""
    # Vérifie source
    if not os.path.exists(source_dir):
        raise ValidationError(f"Dossier source inexistant: {source_dir}")
    
    if not os.path.isdir(source_dir):
        raise ValidationError(f"Source n'est pas un dossier: {source_dir}")
    
    # Vérifie target
    try:
        os.makedirs(target_dir, exist_ok=True)
    except PermissionError:
        raise PermissionError(f"Permission refusée pour créer dossier cible: {target_dir}")
    
    # Vérifie espace disque (minimum 1GB)
    disk_usage = psutil.disk_usage(target_dir)
    if disk_usage.free < 1024 * 1024 * 1024:  # 1GB
        raise DiskSpaceError(f"Espace disque insuffisant: {disk_usage.free / (1024**3):.2f}GB disponible")
    
    # Vérifie permissions d'écriture
    test_file = os.path.join(target_dir, '.test_write')
    try:
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
    except PermissionError:
        raise PermissionError(f"Permission d'écriture refusée: {target_dir}")
    
    return True

def validate_categories(categories: List[str]) -> bool:
    """Valide les catégories"""
    if not categories:
        raise ValidationError("Aucune catégorie définie")
    
    for cat in categories:
        if not cat or not cat.strip():
            raise ValidationError("Catégorie vide invalide")
        if any(c in cat for c in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']):
            raise ValidationError(f"Nom de catégorie invalide: {cat}")
    
    return True

# ==================== TRANSACTION & ROLLBACK ====================

@dataclass
class FileTransaction:
    """Transaction de traitement d'un fichier"""
    source_path: str
    filename: str
    backup_path: str
    target_path: str
    category: str
    timestamp: datetime
    file_hash: str

class TransactionManager:
    """Gestionnaire de transactions avec rollback"""
    
    def __init__(self, classifier_instance):
        self.classifier = classifier_instance
        self.transactions = []
        self.rollback_log = []
    
    def create_transaction(self, source_path: str, filename: str, category: str) -> FileTransaction:
        """Crée une transaction pour un fichier"""
        # Crée backup
        backup_dir = os.path.join(self.classifier.target_dir, ".backup")
        os.makedirs(backup_dir, exist_ok=True)
        
        backup_path = os.path.join(backup_dir, f"{filename}.{int(time.time())}.backup")
        
        # Copie backup
        try:
            shutil.copy2(source_path, backup_path)
            file_hash = self._calculate_file_hash(source_path)
        except Exception as e:
            raise FileProcessingError(f"Impossible de créer le backup: {e}")
        
        # Cible finale
        target_dir = os.path.join(self.classifier.target_dir, category)
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, filename)
        
        # Handle duplicates
        if os.path.exists(target_path):
            base, ext = os.path.splitext(filename)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            target_path = os.path.join(target_dir, f"{base}_{ts}{ext}")
        
        transaction = FileTransaction(
            source_path=source_path,
            filename=filename,
            backup_path=backup_path,
            target_path=target_path,
            category=category,
            timestamp=datetime.now(),
            file_hash=file_hash
        )
        
        self.transactions.append(transaction)
        return transaction
    
    def commit_transaction(self, transaction: FileTransaction):
        """Valide et déplace le fichier"""
        try:
            # Vérifie l'intégrité du backup
            if not self._verify_backup_integrity(transaction):
                raise FileProcessingError("Backup corrompu")
            
            # Déplace le fichier
            shutil.move(transaction.source_path, transaction.target_path)
            
            # Supprime le backup
            if os.path.exists(transaction.backup_path):
                os.remove(transaction.backup_path)
            
            # Met à jour l'état
            rel_path = os.path.relpath(transaction.source_path, self.classifier.source_dir)
            self.classifier.processed_files.add(rel_path)
            self.classifier._save_state()
            
            self.classifier._log(f"  ✅ Transaction validée: {transaction.filename}")
            
        except Exception as e:
            self.classifier._log(f"  ❌ Échec validation: {e}", 'error')
            raise FileProcessingError(f"Validation échouée: {e}")
    
    def rollback_transaction(self, transaction: FileTransaction):
        """Restaure un fichier depuis le backup"""
        try:
            if os.path.exists(transaction.backup_path):
                # Restaure depuis backup
                shutil.move(transaction.backup_path, transaction.source_path)
                self.classifier._log(f"  🔄 Rollback: {transaction.filename}")
            else:
                self.classifier._log(f"  ❌ Rollback impossible: backup manquant", 'error')
                
        except Exception as e:
            self.classifier._log(f"  ❌ Erreur rollback: {e}", 'error')
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """Calcule le hash SHA256 d'un fichier"""
        hash_sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        except Exception:
            return "unknown"
    
    def _verify_backup_integrity(self, transaction: FileTransaction) -> bool:
        """Vérifie l'intégrité du backup"""
        if not os.path.exists(transaction.backup_path):
            return False
        
        try:
            backup_hash = self._calculate_file_hash(transaction.backup_path)
            return backup_hash == transaction.file_hash
        except Exception:
            return False

# ==================== DATA STRUCTURES ====================

@dataclass
class ClassificationResult:
    """Résultat de classification d'un fichier"""
    filename: str
    category: str
    confidence: int
    status: str  # 'success', 'ocr_required', 'failed', 'skipped'
    error: Optional[str] = None
    processing_time: float = 0.0
    retry_count: int = 0
    file_hash: Optional[str] = None

# ==================== CORE ENGINE ====================

class DocumentClassifier:
    def __init__(
        self,
        source_dir: str,
        target_dir: str,
        categories: List[str],
        confidence_threshold: float = 0.7,
        model: str = 'mistral',
        dry_run: bool = False,
        verbose: bool = False,
        log_callback=None,
        progress_callback=None
    ):
        """
        Moteur de classification avec configuration dynamique
        
        Args:
            source_dir: Dossier source à surveiller
            target_dir: Dossier cible pour les fichiers classés
            categories: Liste des catégories disponibles
            confidence_threshold: Seuil de confiance (0.0 à 1.0)
            model: Modèle Ollama à utiliser
            dry_run: Mode simulation
            verbose: Logs détaillés
            log_callback: Fonction pour envoyer les logs (WebSocket)
            progress_callback: Fonction pour envoyer les événements de progression
        """
        # Initialisation minimale
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.categories = categories
        self.confidence_threshold = confidence_threshold
        self.model = model
        self.dry_run = dry_run
        self.verbose = verbose
        self.log_callback = log_callback
        
        # Progress tracking
        if PROGRESS_AVAILABLE and progress_callback:
            self.progress = ProgressTracker(
                verbose=verbose,
                emit_callback=progress_callback
            )
        else:
            self.progress = None
        
        # Dossiers spéciaux
        self.ocr_dir = os.path.join(target_dir, "TO_OCR")
        self.doubtful_dir = os.path.join(target_dir, "DOUBTFUL")
        self.cache_dir = "/tmp/classifier_cache"
        
        # Logging avec structured_logger
        from structured_logger import get_logger
        self.logger = get_logger(self.__class__.__name__)
        
        # Validation système
        self._validate_system()
        
        # Validation configuration
        self._validate_config(source_dir, target_dir, categories, confidence_threshold)
        
        # État
        self.state_file = os.path.join(target_dir, ".classifier_state.json")
        self.processed_files = set()
        self.stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'ocr': 0,
            'doubtful': 0
        }
        
        # Extensions supportées
        self.allowed_extensions = {
            '.pdf', '.docx', '.txt', '.pages', '.numbers', 
            '.key', '.doc', '.xls', '.xlsx', '.csv'
        }
        
        # Setup
        os.makedirs(self.cache_dir, exist_ok=True)
        self._load_state()
        self._ensure_category_dirs()
        
        # Transaction manager
        self.transaction_manager = TransactionManager(self)
    
    def _validate_system(self):
        """Valide les prérequis système"""
        try:
            validate_system_requirements()
            self._log("✅ Prérequis système validés")
        except SystemError as e:
            raise SystemError(f"Prérequis système manquants: {e}")
    
    def _validate_config(self, source_dir: str, target_dir: str, categories: List[str], confidence_threshold: float):
        """Valide la configuration"""
        try:
            validate_directories(source_dir, target_dir)
            validate_categories(categories)
            
            if not 0.0 <= confidence_threshold <= 1.0:
                raise ValidationError(f"Seuil de confiance invalide: {confidence_threshold}")
            
            self._log("✅ Configuration validée")
            
        except (ValidationError, SystemError) as e:
            raise ValidationError(f"Configuration invalide: {e}")
    
    def _log(self, message: str, level: str = 'info'):
        """Log avec callback WebSocket optionnel"""
        if level == 'info':
            self.logger.info(message)
        elif level == 'error':
            self.logger.error(message)
        elif level == 'debug' and self.verbose:
            self.logger.debug(message)
        
        # Envoie au WebSocket si callback fourni
        if self.log_callback:
            try:
                # Format joli pour l'interface web
                log_data = {
                    'message': message,
                    'level': level,
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'logger': 'DocumentClassifier'
                }
                self.log_callback(log_data)
            except Exception as e:
                # Si le callback échoue, on continue quand même
                pass
    
    def _load_state(self):
        """Charge l'état des fichiers déjà traités"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self.processed_files = set(data.get('processed', []))
                self._log(f"📂 État chargé: {len(self.processed_files)} fichiers déjà traités")
            except:
                self._log("⚠️ Impossible de charger l'état", 'error')
    
    def _save_state(self):
        """Sauvegarde l'état"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump({'processed': list(self.processed_files)}, f)
        except Exception as e:
            self._log(f"⚠️ Erreur sauvegarde état: {e}", 'error')
    
    def _ensure_category_dirs(self):
        """Crée les répertoires de catégories s'ils n'existent pas"""
        for category in self.categories:
            cat_dir = os.path.join(self.target_dir, category)
            os.makedirs(cat_dir, exist_ok=True)
        
        # Dossiers spéciaux
        os.makedirs(self.ocr_dir, exist_ok=True)
        os.makedirs(self.doubtful_dir, exist_ok=True)
        
        # Dossier backup
        backup_dir = os.path.join(self.target_dir, ".backup")
        os.makedirs(backup_dir, exist_ok=True)
        
        self._log(f"✅ {len(self.categories)} catégories prêtes")
    
    def _cleanup_old_backups(self):
        """Nettoie les backups trop anciens (> 24h)"""
        try:
            backup_dir = os.path.join(self.target_dir, ".backup")
            if not os.path.exists(backup_dir):
                return
            
            current_time = time.time()
            cleaned = 0
            
            for backup_file in os.listdir(backup_dir):
                backup_path = os.path.join(backup_dir, backup_file)
                if os.path.isfile(backup_path):
                    # Supprime les backups de plus de 24h
                    if current_time - os.path.getctime(backup_path) > 24 * 3600:
                        os.remove(backup_path)
                        cleaned += 1
            
            if cleaned > 0:
                self._log(f"🧹 Nettoyage: {cleaned} backups supprimés")
                
        except Exception as e:
            self._log(f"⚠️ Erreur nettoyage backups: {e}", 'error')
    
    def get_file_from_mount(self, rel_path: str, filename: str) -> Optional[str]:
        """
        Récupère un fichier depuis le mount iCloud/rclone
        Force le téléchargement en lisant directement le fichier
        """
        local_path = os.path.join(self.cache_dir, filename)
        mount_path = os.path.join(self.source_dir, rel_path)
        
        # Cache hit
        if os.path.exists(local_path) and os.path.getsize(local_path) > 100:
            self._log(f"  📦 Cache", 'debug')
            return local_path
        
        # Download from mount (forces iCloud download)
        try:
            self._log(f"  ⬇️  Download...", 'debug')
            with open(mount_path, 'rb') as src:
                with open(local_path, 'wb') as dst:
                    while chunk := src.read(1024 * 1024):
                        dst.write(chunk)
            
            # Validate not HTML
            with open(local_path, 'rb') as f:
                header = f.read(20).lower()
                if b'<!doc' in header or b'<html' in header:
                    self._log(f"  ❌ HTML placeholder", 'error')
                    os.remove(local_path)
                    return None
            
            size = os.path.getsize(local_path)
            self._log(f"  ✅ {size} bytes", 'debug')
            return local_path
            
        except Exception as e:
            self._log(f"  ❌ Download error: {e}", 'error')
            return None
    
    def extract_text(self, path: str, ext: str) -> str:
        """Extraction texte multi-format"""
        try:
            if ext == '.pdf':
                reader = PdfReader(path)
                text = " ".join([p.extract_text() or "" for p in reader.pages[:4]])
                if not text.strip():
                    return "[SCANNED_PDF]"  # Marqueur OCR nécessaire
                return text
                
            elif ext == '.docx':
                return docx2txt.process(path)
                
            elif ext == '.xlsx':
                try:
                    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
                    if wb.active is None:
                        return "[EXCEL_ERROR_NO_SHEETS]"
                    
                    return " ".join([
                        str(c.value) for r in wb.active.iter_rows(max_row=50) 
                        for c in r if c.value
                    ])
                except Exception as e:
                    self._log(f"  ⚠️ Excel error: {e}", 'debug')
                    return "[EXCEL_ERROR]"
                
            elif ext == '.xls':
                wb = xlrd.open_workbook(path)
                s = wb.sheet_by_index(0)
                return " ".join([
                    str(s.cell_value(r, c)) 
                    for r in range(min(50, s.nrows)) 
                    for c in range(s.ncols)
                ])
                
            elif ext in {'.numbers', '.pages', '.key'}:
                # Apple bundles - extrait XML
                with zipfile.ZipFile(path) as z:
                    xml_files = [n for n in z.namelist() if n.endswith('.xml')]
                    if not xml_files:
                        # Pas de XML trouvé, probablement corrompu
                        return "[APPLE_BUNDLE_ERROR]"
                    
                    content = " ".join([
                        z.read(n).decode('utf-8', errors='ignore') 
                        for n in xml_files
                    ])
                    
                    # Vérifie qu'on a du contenu exploitable
                    if len(content.strip()) < 100:
                        return "[APPLE_BUNDLE_EMPTY]"
                    
                    return content
                    
            elif ext == '.txt':
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read(4000)
                    
        except zipfile.BadZipFile:
            # Fichier Apple corrompu
            self._log(f"  ⚠️ Bad ZIP file (Apple bundle corrompu)", 'debug')
            return "[CORRUPTED_FILE]"
        except Exception as e:
            self._log(f"  ⚠️ Extraction error: {e}", 'debug')
            return "[EXTRACTION_ERROR]"
        
        return ""
    
    def classify_with_ai(self, text: str, filename: str) -> Tuple[str, int]:
        """
        Classification IA avec prompt structuré
        Retourne (categorie, confidence_score)
        """
        categories_str = ", ".join(self.categories)
        
        prompt = f"""Analyse ce document et réponds EXACTEMENT dans ce format:
Catégorie | Confiance

Fichier: {filename}
Contenu: {text[:1500]}

Catégories possibles: {categories_str}
Confiance: un nombre entre 0 et 100

Ta réponse doit être UNE SEULE LIGNE au format: Catégorie | Confiance
Exemple: facture | 85"""
        
        try:
            resp = ollama.generate(model=self.model, prompt=prompt)['response'].strip()
            
            # Parse la dernière ligne avec pipe
            lines = [l.strip() for l in resp.split('\n') if l.strip() and '|' in l]
            if not lines:
                return "autre", 0
            
            last_line = lines[-1]
            parts = last_line.split('|')
            if len(parts) < 2:
                return "autre", 0
            
            category = parts[0].strip().lower()
            conf_str = parts[1].strip()
            
            # Extrait score
            digits = ''.join(filter(str.isdigit, conf_str))
            confidence = min(int(digits), 100) if digits else 0
            
            # Valide que la catégorie existe
            if category not in [c.lower() for c in self.categories]:
                category = "autre"
            
            return category, confidence
            
        except Exception as e:
            self._log(f"  ⚠️ IA error: {e}", 'error')
            return "autre", 0
    
    def process_with_ocr(self, file_path: str, filename: str) -> Optional[Tuple[str, int]]:
        """
        Traite un fichier avec OCR puis le classifie
        
        Returns:
            (category, confidence) ou None si échec
        """
        self._log(f"  🔍 OCR processing: {filename}")
        
        # TODO: Implémenter appel au script OCR
        # Pour l'instant, placeholder
        ocr_output = f"/tmp/ocr_{filename}.txt"
        
        try:
            # Appelle script OCR externe (à créer)
            subprocess.run([
                'python3', 'ocr_processor.py',
                file_path, ocr_output
            ], check=True, timeout=60)
            
            if os.path.exists(ocr_output):
                with open(ocr_output, 'r') as f:
                    ocr_text = f.read()
                
                # Classifie le texte OCR
                category, confidence = self.classify_with_ai(ocr_text, filename)
                os.remove(ocr_output)
                
                return category, confidence
        
        except Exception as e:
            self._log(f"  ❌ OCR failed: {e}", 'error')
            return None
        
        return None
    
    def process_file(self, rel_path: str, filename: str, ext: str) -> ClassificationResult:
        """Traite un fichier complet avec progress tracking"""
        start_time = datetime.now()
        start_time_ms = time.time()
        file_path = os.path.join(self.source_dir, rel_path)
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        
        # Progress: File discovered
        if self.progress:
            self.progress.file_discovered(file_path, file_size)
        
        self._log(f"\n📄 {filename}")
        
        # Progress: File reading
        if self.progress:
            self.progress.file_reading(file_path)
        
        # Download
        read_start = time.time()
        local_path = self.get_file_from_mount(rel_path, filename)
        if not local_path:
            if self.progress:
                self.progress.file_failed(file_path, "Download failed")
            return ClassificationResult(
                filename=filename,
                category="",
                confidence=0,
                status='failed',
                error='Download failed'
            )
        
        # Extract text
        text = self.extract_text(local_path, ext)
        read_duration_ms = int((time.time() - read_start) * 1000)
        
        # Progress: Read complete
        if self.progress:
            self.progress.file_read_complete(file_path, len(text), read_duration_ms)
        
        # Catégories spéciales d'erreurs (skip OCR pour ces cas)
        error_markers = {
            "[APPLE_BUNDLE_ERROR]": "Apple bundle corrompu",
            "[APPLE_BUNDLE_EMPTY]": "Apple bundle vide",
            "[CORRUPTED_FILE]": "Fichier corrompu",
            "[EXTRACTION_ERROR]": "Erreur extraction"
        }
        
        # Check si erreur d'extraction non-OCRable
        if text in error_markers:
            self._log(f"  ❌ {error_markers[text]}")
            
            if self.progress:
                self.progress.file_failed(file_path, error_markers[text])
            
            # Déplace vers DOUBTFUL (pas TO_OCR car OCR ne peut pas aider)
            if not self.dry_run:
                target = os.path.join(self.doubtful_dir, filename)
                if os.path.exists(target):
                    base, ext_name = os.path.splitext(filename)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    target = os.path.join(self.doubtful_dir, f"{base}_{ts}{ext_name}")
                shutil.move(os.path.join(self.source_dir, rel_path), target)
            
            return ClassificationResult(
                filename=filename,
                category="DOUBTFUL",
                confidence=0,
                status='failed',
                error=error_markers[text],
                processing_time=(datetime.now() - start_time).total_seconds()
            )
        
        # Check si OCR nécessaire (SEULEMENT pour PDFs scannés)
        if text == "[SCANNED_PDF]":
            self._log(f"  🔍 PDF scanné détecté, OCR nécessaire")
            
            if self.progress:
                self.progress.ocr_required(file_path)
                self.progress.ocr_started(file_path)
            
            ocr_start = time.time()
            result = self.process_with_ocr(local_path, filename)
            ocr_duration_ms = int((time.time() - ocr_start) * 1000)
            
            if result:
                category, confidence = result
                status = 'ocr_required'
                
                if self.progress:
                    self.progress.ocr_complete(file_path, len(str(result)), ocr_duration_ms)
            else:
                if self.progress:
                    self.progress.ocr_failed(file_path, "OCR processing failed")
                
                # OCR failed, move to TO_OCR for manual processing
                if not self.dry_run:
                    target = os.path.join(self.ocr_dir, filename)
                    shutil.move(os.path.join(self.source_dir, rel_path), target)
                
                return ClassificationResult(
                    filename=filename,
                    category="TO_OCR",
                    confidence=0,
                    status='ocr_required',
                    processing_time=(datetime.now() - start_time).total_seconds()
                )
        
        # Check si texte trop court (< 50 chars) mais pas un PDF scanné
        elif len(text.strip()) < 50:
            self._log(f"  ⚠️ Contenu très court ({len(text.strip())} chars)")
            
            if self.progress:
                self.progress.system_warning(
                    f"Very short content: {filename}",
                    content_length=len(text.strip())
                )
            
            # Progress: Analyzing
            if self.progress:
                self.progress.file_analyzing(file_path)
            
            # On classifie quand même mais avec faible confiance attendue
            ai_start = time.time()
            category, confidence = self.classify_with_ai(text, filename)
            ai_duration_ms = int((time.time() - ai_start) * 1000)
            
            if self.progress:
                self.progress.ai_response_received(file_path, category, confidence / 100, ai_duration_ms)
            
            status = 'success'
        
        else:
            # Progress: Analyzing
            if self.progress:
                self.progress.file_analyzing(file_path)
                self.progress.ai_request_processing(file_path)
            
            # Classification normale
            ai_start = time.time()
            category, confidence = self.classify_with_ai(text, filename)
            ai_duration_ms = int((time.time() - ai_start) * 1000)
            
            if self.progress:
                self.progress.ai_response_received(file_path, category, confidence / 100, ai_duration_ms)
            
            status = 'success'
        
        # Progress: Classified
        if self.progress:
            self.progress.file_classified(file_path, category, confidence / 100)
        
        # Validation confiance
        confidence_threshold_pct = int(self.confidence_threshold * 100)
        
        if confidence < confidence_threshold_pct:
            self._log(f"  ❓ Confiance faible: {category} ({confidence}%)")
            target_dir = self.doubtful_dir
            status = 'doubtful'
            
            if self.progress:
                self.progress.system_warning(
                    f"Low confidence: {filename}",
                    confidence=confidence/100,
                    threshold=self.confidence_threshold
                )
        else:
            self._log(f"  ✅ {category} ({confidence}%)")
            target_dir = os.path.join(self.target_dir, category)
            status = 'success'
        
        # Move file with transaction
        if not self.dry_run:
            try:
                # Progress: Moving
                if self.progress:
                    self.progress.file_moving(file_path, category)
                
                # Crée transaction
                source_full_path = os.path.join(self.source_dir, rel_path)
                transaction = self.transaction_manager.create_transaction(
                    source_full_path, filename, category
                )
                
                # Valide et déplace
                self.transaction_manager.commit_transaction(transaction)
                
                # Progress: Moved
                total_duration_ms = int((time.time() - start_time_ms) * 1000)
                if self.progress:
                    self.progress.file_moved(file_path, category, total_duration_ms)
                
            except FileProcessingError as e:
                self._log(f"  ❌ Transaction error: {e}", 'error')
                if self.progress:
                    self.progress.file_failed(file_path, str(e))
                return ClassificationResult(
                    filename=filename,
                    category=category,
                    confidence=confidence,
                    status='failed',
                    error=str(e),
                    processing_time=(datetime.now() - start_time).total_seconds()
                )
        else:
            self._log(f"  [DRY RUN] Would move to: {target_dir}")
            # Progress: Moved (simulated in dry run)
            total_duration_ms = int((time.time() - start_time_ms) * 1000)
            if self.progress:
                self.progress.file_moved(file_path, category, total_duration_ms)
        
        return ClassificationResult(
            filename=filename,
            category=category,
            confidence=confidence,
            status=status,
            processing_time=(datetime.now() - start_time).total_seconds()
        )
    
        def run(self, max_workers: int = None) -> Dict:
        """Traite tous les fichiers avec workers parallèles"""
        try:
            self._log("\n" + "="*70)
            self._log(f"🚀 CLASSIFICATION - Mode: {'DRY-RUN' if self.dry_run else 'PRODUCTION'}")
            self._log(f"   Source: {self.source_dir}")
            self._log(f"   Target: {self.target_dir}")
            self._log(f"   Catégories: {len(self.categories)}")
            self._log(f"   Seuil confiance: {self.confidence_threshold*100}%")
        
            # Détermine le nombre de workers
            cpu_count = psutil.cpu_count()
            if max_workers is None:
                max_workers = min(cpu_count * 2, 8) if cpu_count else 4
        
            self._log(f"   Workers: {max_workers}")
            self._log("="*70)
        
            # Nettoyage pré-traitement
            self._cleanup_old_backups()
        
            # Scan files (CODE EXISTANT - NE PAS MODIFIER)
            files_to_process = []
            for root, _, filenames in os.walk(self.source_dir):
                for fn in filenames:
                    ext = Path(fn).suffix.lower()
                    if ext in self.allowed_extensions:
                        rel = os.path.relpath(os.path.join(root, fn), self.source_dir)
                        if rel not in self.processed_files:
                            files_to_process.append((rel, fn, ext))
        
            self.stats['total'] = len(files_to_process)
            self._log(f"\n📂 {len(files_to_process)} fichiers à traiter")
        
            # ✅ AJOUTER ICI - Progress: Batch started
            if self.progress:
                self.progress.batch_started(len(files_to_process))
                batch_start_time = time.time() 
                
            if not files_to_process:
                self._log("✅ Aucun fichier à traiter")
                return self.stats            
                
            # Scan files
            files_to_process = []
            for root, _, filenames in os.walk(self.source_dir):
                for fn in filenames:
                    ext = Path(fn).suffix.lower()
                    if ext in self.allowed_extensions:
                        rel = os.path.relpath(os.path.join(root, fn), self.source_dir)
                        if rel not in self.processed_files:
                            files_to_process.append((rel, fn, ext))
            
            self.stats['total'] = len(files_to_process)
            self._log(f"\n📂 {len(files_to_process)} fichiers à traiter")
            
            if not files_to_process:
                self._log("✅ Aucun fichier à traiter")
                return self.stats
            
            # Batch processing pour petits fichiers
            small_files = []
            large_files = []
            
            for rel, fn, ext in files_to_process:
                try:
                    file_path = os.path.join(self.source_dir, rel)
                    size = os.path.getsize(file_path)
                    if size < 1024 * 1024:  # < 1MB
                        small_files.append((rel, fn, ext))
                    else:
                        large_files.append((rel, fn, ext))
                except:
                    small_files.append((rel, fn, ext))
            
            self._log(f"   📦 Petits fichiers: {len(small_files)}")
            self._log(f"   📁 Grands fichiers: {len(large_files)}")
            
            # Process en parallèle
            processed_count = 0
            
            def process_batch(file_batch, batch_name):
                """Traite un batch de fichiers"""
                nonlocal processed_count
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all tasks
                    future_to_file = {
                        executor.submit(self.process_file, rel, fn, ext): (rel, fn, ext)
                        for rel, fn, ext in file_batch
                    }
                    
                    # Process results as they complete
                    for future in as_completed(future_to_file):
                        rel, fn, ext = future_to_file[future]
                        processed_count += 1
                        
                        try:
                            result = future.result()
                            # Progress: Batch progress (tous les 5 fichiers)
                            if self.progress and (idx % 5 == 0 or idx == len(all_files)):
                                self.progress.batch_progress(
                                    current=idx,
                                    total=len(all_files),
                                    success=self.stats['success'],
                                    failed=self.stats['failed']
                                )
                                
                            # Update stats
                            if result.status == 'success':
                                self.stats['success'] += 1
                            elif result.status == 'failed':
                                self.stats['failed'] += 1
                            elif result.status == 'ocr_required':
                                self.stats['ocr'] += 1
                            elif result.status == 'doubtful':
                                self.stats['doubtful'] += 1
                            
                            # Progress log
                            self._log(f"   [{processed_count:3d}/{self.stats['total']}] {fn} - {result.status}")
                            # ✅ AJOUTER ICI - Progress update (tous les 5 fichiers)
                            if self.progress and (processed_count % 5 == 0 or processed_count == self.stats['total']):
                                self.progress.batch_progress(
                                    current=processed_count,
                                    total=self.stats['total'],
                                    success=self.stats['success'],
                                    failed=self.stats['failed']
                                )
                        except Exception as e:
                            self._log(f"   [{processed_count:3d}/{self.stats['total']}] {fn} - ERROR: {e}", 'error')
                            self.stats['failed'] += 1
            
            # Process small files first (faster)
            if small_files:
                self._log(f"\n⚡ Traitement petits fichiers...")
                process_batch(small_files, "small")

            
            # Process large files
            if large_files:
                self._log(f"\n📁 Traitement grands fichiers...")
                process_batch(large_files, "large")
            
            # Final report
            self._log("\n" + "="*70)
            self._log("📊 RAPPORT FINAL")
            self._log(f"   Total traité:  {self.stats['total']}")
            self._log(f"   ✅ Succès:      {self.stats['success']}")
            self._log(f"   ❌ Échecs:      {self.stats['failed']}")
            self._log(f"   🔍 OCR:         {self.stats['ocr']}")
            self._log(f"   ❓ Douteux:     {self.stats['doubtful']}")
            self._log("="*70)
            
            # Nettoyage post-traitement
            self._cleanup_old_backups()
            
            # ✅ AJOUTER AVANT LE RETURN FINAL
        if self.progress:
            import time
            duration_s = int(time.time() - start_time)  # Ajouter start_time = time.time() au début de run()
            self.progress.batch_complete(
                total=self.stats['total'],
                success=self.stats['success'],
                failed=self.stats['failed'],
                duration_s=duration_s
            )
        
        self._log("\n" + "="*70)
        self._log("✅ Classification terminée")
        self._log(f"   Total: {self.stats['total']}")
        self._log(f"   Succès: {self.stats['success']}")
        self._log(f"   Échoués: {self.stats['failed']}")
        self._log(f"   OCR: {self.stats['ocr']}")
        self._log(f"   Douteux: {self.stats['doubtful']}")
        self._log("="*70 + "\n")
        
        return self.stats
            
        except ValidationError as e:
            self._log(f"❌ Erreur de configuration: {e}", 'error')
            raise
        except SystemError as e:
            self._log(f"❌ Erreur système: {e}", 'error')
            raise
        except Exception as e:
            self._log(f"❌ Erreur inattendue: {e}", 'error')
            raise SystemError(f"Erreur fatale: {e}")


# ==================== CLI (pour tests) ====================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--categories', nargs='+', required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--threshold', type=float, default=0.7)
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    classifier = DocumentClassifier(
        source_dir=args.source,
        target_dir=args.target,
        categories=args.categories,
        confidence_threshold=args.threshold,
        dry_run=args.dry_run,
        verbose=args.verbose
    )
    
    stats = classifier.run()
    print(f"\n✅ Terminé: {stats}")