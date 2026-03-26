#!/usr/bin/env python3
"""
STRUCTURED LOGGER - Logs centralisés et structurés
Logs JSON avec rotation, niveaux de criticité et monitoring système
"""

import json
import logging
import logging.handlers
import time
import threading
import psutil
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass, asdict
import sys

@dataclass
class LogEntry:
    """Entrée de log structurée"""
    timestamp: str
    level: str
    message: str
    module: str
    function: Optional[str] = None
    file_path: Optional[str] = None
    line_no: Optional[int] = None
    extra: Optional[Dict] = None
    performance: Optional[Dict] = None
    system: Optional[Dict] = None

class StructuredFormatter(logging.Formatter):
    """Formateur de logs JSON structuré"""
    
    def format(self, record):
        # Base log entry
        log_entry = LogEntry(
            timestamp=datetime.fromtimestamp(record.created).isoformat(),
            level=record.levelname,
            message=record.getMessage(),
            module=record.name,
            function=getattr(record, 'funcName', None),
            file_path=getattr(record, 'pathname', None),
            line_no=getattr(record, 'lineno', None)
        )
        
        # Add extra fields if present
        if hasattr(record, '__dict__'):
            extra_fields = {}
            for key, value in record.__dict__.items():
                if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 
                              'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
                              'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
                              'thread', 'threadName', 'processName', 'process', 'getMessage']:
                    extra_fields[key] = value
            
            if extra_fields:
                log_entry.extra = extra_fields
        
        # Add performance data
        if hasattr(record, '__dict__') and 'performance' in record.__dict__:
            log_entry.performance = record.__dict__['performance']
        
        # Add system data
        if hasattr(record, '__dict__') and 'system' in record.__dict__:
            log_entry.system = record.__dict__['system']
        
        # Convert to JSON
        return json.dumps(asdict(log_entry), ensure_ascii=False, indent=2)

class PerformanceTracker:
    """Suivi des performances système"""
    
    def __init__(self):
        self.start_time = time.time()
        self.metrics = {
            'cpu_percent': 0.0,
            'memory_percent': 0.0,
            'disk_percent': 0.0,
            'network_sent': 0,
            'network_recv': 0,
            'process_count': 0
        }
        self.lock = threading.Lock()
    
    def update_metrics(self):
        """Met à jour les métriques système"""
        with self.lock:
            try:
                # CPU
                self.metrics['cpu_percent'] = psutil.cpu_percent(interval=1)
                
                # Memory
                memory = psutil.virtual_memory()
                self.metrics['memory_percent'] = memory.percent
                
                # Disk
                disk = psutil.disk_usage('/')
                self.metrics['disk_percent'] = disk.percent
                
                # Network
                network = psutil.net_io_counters()
                self.metrics['network_sent'] = network.bytes_sent
                self.metrics['network_recv'] = network.bytes_recv
                
                # Process count
                self.metrics['process_count'] = len(psutil.pids())
                
            except Exception as e:
                # Silently handle errors to avoid log loops
                pass
    
    def get_metrics(self) -> Dict:
        """Retourne les métriques actuelles"""
        with self.lock:
            return self.metrics.copy()
    
    def get_performance_data(self) -> Dict:
        """Retourne les données de performance pour le log"""
        return {
            'uptime_seconds': time.time() - self.start_time,
            'timestamp': datetime.now().isoformat(),
            'metrics': self.get_metrics()
        }

class SystemMonitor:
    """Surveillance système avancée"""
    
    def __init__(self, logger_instance):
        self.logger = logger_instance
        self.alert_thresholds = {
            'cpu_high': 80.0,
            'memory_high': 80.0,
            'disk_high': 90.0,
            'disk_low': 10.0
        }
        self.alerts_sent = set()
        self.monitoring = False
        self.monitor_thread = None
    
    def start_monitoring(self):
        """Démarre la surveillance système"""
        if not self.monitoring:
            self.monitoring = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
            self.logger.info("System monitoring started")
    
    def stop_monitoring(self):
        """Arrête la surveillance système"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        self.logger.info("System monitoring stopped")
    
    def _monitor_loop(self):
        """Boucle de surveillance"""
        while self.monitoring:
            try:
                metrics = self.logger.performance_tracker.get_metrics()
                
                # Check thresholds
                self._check_thresholds(metrics)
                
                # Log system status every 5 minutes
                if int(time.time()) % 300 == 0:
                    self._log_system_status(metrics)
                
                time.sleep(30)  # Check every 30 seconds
                
            except Exception:
                # Avoid log loops
                time.sleep(30)
    
    def _check_thresholds(self, metrics: Dict):
        """Vérifie les seuils d'alerte"""
        current_time = time.time()
        
        # CPU
        if metrics['cpu_percent'] > self.alert_thresholds['cpu_high']:
            alert_key = f"cpu_high_{int(current_time // 300)}"
            if alert_key not in self.alerts_sent:
                self.logger.warning(
                    f"High CPU usage: {metrics['cpu_percent']:.1f}%",
                    extra={'alert_type': 'cpu_high', 'value': metrics['cpu_percent']}
                )
                self.alerts_sent.add(alert_key)
        
        # Memory
        if metrics['memory_percent'] > self.alert_thresholds['memory_high']:
            alert_key = f"memory_high_{int(current_time // 300)}"
            if alert_key not in self.alerts_sent:
                self.logger.warning(
                    f"High memory usage: {metrics['memory_percent']:.1f}%",
                    extra={'alert_type': 'memory_high', 'value': metrics['memory_percent']}
                )
                self.alerts_sent.add(alert_key)
        
        # Disk space
        if metrics['disk_percent'] > self.alert_thresholds['disk_high']:
            alert_key = f"disk_high_{int(current_time // 300)}"
            if alert_key not in self.alerts_sent:
                self.logger.error(
                    f"Critical disk usage: {metrics['disk_percent']:.1f}%",
                    extra={'alert_type': 'disk_high', 'value': metrics['disk_percent']}
                )
                self.alerts_sent.add(alert_key)
        
        elif metrics['disk_percent'] < self.alert_thresholds['disk_low']:
            alert_key = f"disk_low_{int(current_time // 300)}"
            if alert_key not in self.alerts_sent:
                self.logger.error(
                    f"Low disk space: {metrics['disk_percent']:.1f}%",
                    extra={'alert_type': 'disk_low', 'value': metrics['disk_percent']}
                )
                self.alerts_sent.add(alert_key)
    
    def _log_system_status(self, metrics: Dict):
        """Log le statut système complet"""
        self.logger.info(
            "System status",
            extra={
                'system_status': True,
                'metrics': metrics
            }
        )

class StructuredLogger:
    """Logger centralisé avec rotation et monitoring"""
    
    def __init__(self, app_name: str = "DocumentClassifier", log_dir: str = "/tmp/classifier_logs"):
        """
        Initialise le logger structuré
        
        Args:
            app_name: Nom de l'application
            log_dir: Répertoire des logs
        """
        self.app_name = app_name
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Root logger
        self.logger = logging.getLogger(app_name)
        self.logger.setLevel(logging.DEBUG)
        
        # Prevent duplicate logs
        self.logger.propagate = False
        
        # Setup
        self.performance_tracker = PerformanceTracker()
        self.system_monitor = SystemMonitor(self)
        
        # Handlers
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Configure les handlers de logs"""
        # Console handler (human readable)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # JSON file handler (structured)
        json_file = self.log_dir / f"{self.app_name.lower()}.json"
        json_handler = logging.handlers.RotatingFileHandler(
            json_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        json_handler.setLevel(logging.DEBUG)
        json_formatter = StructuredFormatter()
        json_handler.setFormatter(json_formatter)
        self.logger.addHandler(json_handler)
        
        # Error file handler (errors only)
        error_file = self.log_dir / f"{self.app_name.lower()}_errors.json"
        error_handler = logging.handlers.RotatingFileHandler(
            error_file,
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(json_formatter)
        self.logger.addHandler(error_handler)
        
        # Performance file handler
        perf_file = self.log_dir / f"{self.app_name.lower()}_performance.json"
        perf_handler = logging.handlers.TimedRotatingFileHandler(
            perf_file,
            when='H',
            interval=1,
            backupCount=24
        )
        perf_handler.setLevel(logging.INFO)
        perf_handler.setFormatter(json_formatter)
        self.logger.addHandler(perf_handler)
    
    def _add_performance_data(self, extra: Optional[Dict] = None) -> Dict:
        """Ajoute les données de performance au log"""
        if extra is None:
            extra = {}
        
        # Update metrics
        self.performance_tracker.update_metrics()
        
        # Add performance data
        extra['performance'] = self.performance_tracker.get_performance_data()
        extra['system'] = self.performance_tracker.get_metrics()
        
        return extra
    
    def debug(self, message: str, extra: Optional[Dict] = None):
        """Log debug avec données système"""
        extra = self._add_performance_data(extra)
        self.logger.debug(message, extra=extra)
    
    def info(self, message: str, extra: Optional[Dict] = None):
        """Log info avec données système"""
        extra = self._add_performance_data(extra)
        self.logger.info(message, extra=extra)
    
    def warning(self, message: str, extra: Optional[Dict] = None):
        """Log warning avec données système"""
        extra = self._add_performance_data(extra)
        self.logger.warning(message, extra=extra)
    
    def error(self, message: str, extra: Optional[Dict] = None, exc_info: bool = False):
        """Log error avec données système et exception"""
        extra = self._add_performance_data(extra)
        self.logger.error(message, extra=extra, exc_info=exc_info)
    
    def critical(self, message: str, extra: Optional[Dict] = None, exc_info: bool = False):
        """Log critical avec données système et exception"""
        extra = self._add_performance_data(extra)
        self.logger.critical(message, extra=extra, exc_info=exc_info)
    
    def start_performance_timer(self, operation: str) -> Dict:
        """Démarre un timer de performance"""
        return {
            'operation': operation,
            'start_time': time.time(),
            'start_metrics': self.performance_tracker.get_metrics().copy()
        }
    
    def end_performance_timer(self, timer_data: Dict, extra: Optional[Dict] = None) -> Dict:
        """Termine un timer de performance et retourne les stats"""
        if extra is None:
            extra = {}
        
        end_time = time.time()
        duration = end_time - timer_data['start_time']
        
        end_metrics = self.performance_tracker.get_metrics()
        start_metrics = timer_data['start_metrics']
        
        # Calculate deltas
        metric_deltas = {}
        for key in start_metrics:
            if isinstance(start_metrics[key], (int, float)):
                metric_deltas[f"{key}_delta"] = end_metrics[key] - start_metrics[key]
        
        performance_stats = {
            'operation': timer_data['operation'],
            'duration_seconds': duration,
            'start_time': datetime.fromtimestamp(timer_data['start_time']).isoformat(),
            'end_time': datetime.fromtimestamp(end_time).isoformat(),
            'start_metrics': start_metrics,
            'end_metrics': end_metrics,
            'metric_deltas': metric_deltas
        }
        
        extra['performance'] = performance_stats
        
        # Log performance summary
        self.info(
            f"Performance: {timer_data['operation']} completed in {duration:.2f}s",
            extra=extra
        )
        
        return performance_stats
    
    def log_file_operation(self, operation: str, file_path: str, file_size: Optional[int] = None, extra: Optional[Dict] = None):
        """Log une opération sur fichier"""
        if extra is None:
            extra = {}
        
        file_info = {
            'file_operation': operation,
            'file_path': file_path,
            'file_size': file_size,
            'file_extension': Path(file_path).suffix if file_path else None
        }
        
        extra.update(file_info)
        self.info(f"File operation: {operation} - {file_path}", extra=extra)
    
    def log_classification_result(self, filename: str, category: str, confidence: int, status: str, processing_time: float, extra: Optional[Dict] = None):
        """Log un résultat de classification"""
        if extra is None:
            extra = {}
        
        classification_info = {
            'classification_result': True,
            'filename': filename,
            'category': category,
            'confidence': confidence,
            'status': status,
            'processing_time': processing_time
        }
        
        extra.update(classification_info)
        level = logging.INFO if status in ['success', 'ocr_required'] else logging.WARNING
        self.logger.log(level, f"Classification: {filename} -> {category} ({confidence}%) [{status}]", extra=extra)
    
    def get_log_stats(self) -> Dict:
        """Retourne les statistiques des logs"""
        try:
            # Count log levels
            log_files = list(self.log_dir.glob("*.json"))
            stats = {
                'total_logs': 0,
                'error_logs': 0,
                'warning_logs': 0,
                'info_logs': 0,
                'debug_logs': 0,
                'log_files': len(log_files),
                'disk_usage_mb': sum(f.stat().st_size for f in log_files) / (1024*1024)
            }
            
            # Read latest log file for counts
            json_file = self.log_dir / f"{self.app_name.lower()}.json"
            if json_file.exists():
                try:
                    with open(json_file, 'r') as f:
                        for line in f:
                            if line.strip():
                                try:
                                    log_entry = json.loads(line)
                                    stats['total_logs'] += 1
                                    level = log_entry.get('level', '').upper()
                                    if level == 'ERROR':
                                        stats['error_logs'] += 1
                                    elif level == 'WARNING':
                                        stats['warning_logs'] += 1
                                    elif level == 'INFO':
                                        stats['info_logs'] += 1
                                    elif level == 'DEBUG':
                                        stats['debug_logs'] += 1
                                except json.JSONDecodeError:
                                    continue
                except Exception:
                    pass
            
            return stats
            
        except Exception as e:
            return {'error': str(e)}
    
    def cleanup_old_logs(self, days: int = 7):
        """Nettoie les logs plus vieux que X jours"""
        try:
            cutoff_time = time.time() - (days * 24 * 3600)
            cleaned = 0
            
            for log_file in self.log_dir.glob("*.json"):
                if log_file.stat().st_mtime < cutoff_time:
                    log_file.unlink()
                    cleaned += 1
            
            self.info(f"Log cleanup: {cleaned} old log files removed")
            return cleaned
            
        except Exception as e:
            self.error(f"Log cleanup failed: {e}")
            return 0
    
    def start_monitoring(self):
        """Démarre la surveillance système"""
        self.system_monitor.start_monitoring()
    
    def stop_monitoring(self):
        """Arrête la surveillance système"""
        self.system_monitor.stop_monitoring()

# Instance globale du logger
global_logger = StructuredLogger()

# Fonctions utilitaires pour l'application
def get_logger(name: str = None):
    """Retourne une instance du logger structuré"""
    if name:
        return global_logger.logger.getChild(name)
    return global_logger

def log_performance(operation: str):
    """Décorateur pour logger les performances"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            timer = global_logger.start_performance_timer(operation)
            try:
                result = func(*args, **kwargs)
                global_logger.end_performance_timer(timer)
                return result
            except Exception as e:
                global_logger.end_performance_timer(timer, {'error': str(e)})
                raise
        return wrapper
    return decorator