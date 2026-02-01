#!/usr/bin/env python3
"""
CLASSIFIER ENGINE - Version Web App Intégrée
Moteur de classification avec support OCR et catégories dynamiques
"""
import os
import json
import shutil
import subprocess
from pathlib import Path
import zipfile
import openpyxl
import xlrd 
import ollama
from pypdf import PdfReader
import docx2txt
import logging
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime

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
        log_callback=None
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
        """
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.categories = categories
        self.confidence_threshold = confidence_threshold
        self.model = model
        self.dry_run = dry_run
        self.verbose = verbose
        self.log_callback = log_callback
        
        # Dossiers spéciaux
        self.ocr_dir = os.path.join(target_dir, "TO_OCR")
        self.doubtful_dir = os.path.join(target_dir, "DOUBTFUL")
        self.cache_dir = "/tmp/classifier_cache"
        
        # Logging (INIT FIRST - before any _log calls)
        self.logger = logging.getLogger(__name__)
        if verbose:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)
        
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
            self.log_callback(message)
    
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
        
        self._log(f"✅ {len(self.categories)} catégories prêtes")
    
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
                wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
                return " ".join([
                    str(c.value) for r in wb.active.iter_rows(max_row=50) 
                    for c in r if c.value
                ])
                
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
        """Traite un fichier complet"""
        start_time = datetime.now()
        
        self._log(f"\n📄 {filename}")
        
        # Download
        local_path = self.get_file_from_mount(rel_path, filename)
        if not local_path:
            return ClassificationResult(
                filename=filename,
                category="",
                confidence=0,
                status='failed',
                error='Download failed'
            )
        
        # Extract text
        text = self.extract_text(local_path, ext)
        
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
            result = self.process_with_ocr(local_path, filename)
            
            if result:
                category, confidence = result
                status = 'ocr_required'
            else:
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
            # On classifie quand même mais avec faible confiance attendue
            category, confidence = self.classify_with_ai(text, filename)
            status = 'success'
        
        else:
            # Classification normale
            category, confidence = self.classify_with_ai(text, filename)
            status = 'success'
        
        # Validation confiance
        confidence_threshold_pct = int(self.confidence_threshold * 100)
        
        if confidence < confidence_threshold_pct:
            self._log(f"  ❓ Confiance faible: {category} ({confidence}%)")
            target_dir = self.doubtful_dir
            status = 'doubtful'
        else:
            self._log(f"  ✅ {category} ({confidence}%)")
            target_dir = os.path.join(self.target_dir, category)
            status = 'success'
        
        # Move file
        if not self.dry_run:
            target_path = os.path.join(target_dir, filename)
            
            # Handle duplicates
            if os.path.exists(target_path):
                base, ext_name = os.path.splitext(filename)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                target_path = os.path.join(target_dir, f"{base}_{ts}{ext_name}")
            
            try:
                shutil.move(os.path.join(self.source_dir, rel_path), target_path)
                self.processed_files.add(rel_path)
                self._save_state()
            except Exception as e:
                self._log(f"  ❌ Move error: {e}", 'error')
                status = 'failed'
        else:
            self._log(f"  🔍 [DRY-RUN] Serait déplacé vers: {target_dir}")
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return ClassificationResult(
            filename=filename,
            category=category,
            confidence=confidence,
            status=status,
            processing_time=processing_time
        )
    
    def run(self) -> Dict:
        """
        Lance le traitement complet
        
        Returns:
            Statistiques du traitement
        """
        self._log("\n" + "="*70)
        self._log(f"🚀 CLASSIFICATION - Mode: {'DRY-RUN' if self.dry_run else 'PRODUCTION'}")
        self._log(f"   Source: {self.source_dir}")
        self._log(f"   Target: {self.target_dir}")
        self._log(f"   Catégories: {len(self.categories)}")
        self._log(f"   Seuil confiance: {self.confidence_threshold*100}%")
        self._log("="*70)
        
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
        
        # Process
        for i, (rel, fn, ext) in enumerate(files_to_process, 1):
            self._log(f"\n[{i:3d}/{self.stats['total']}]")
            
            result = self.process_file(rel, fn, ext)
            
            # Update stats
            if result.status == 'success':
                self.stats['success'] += 1
            elif result.status == 'failed':
                self.stats['failed'] += 1
            elif result.status == 'ocr_required':
                self.stats['ocr'] += 1
            elif result.status == 'doubtful':
                self.stats['doubtful'] += 1
        
        # Final report
        self._log("\n" + "="*70)
        self._log("📊 RAPPORT FINAL")
        self._log(f"   Total traité:  {self.stats['total']}")
        self._log(f"   ✅ Succès:      {self.stats['success']}")
        self._log(f"   ❌ Échecs:      {self.stats['failed']}")
        self._log(f"   🔍 OCR:         {self.stats['ocr']}")
        self._log(f"   ❓ Douteux:     {self.stats['doubtful']}")
        self._log("="*70)
        
        return self.stats


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