#!/usr/bin/env python3
"""
PERFORMANCE CACHE - Gestion intelligente du cache iCloud
Cache intelligent avec TTL, gestion mémoire et compression
"""

import os
import time
import hashlib
import threading
import json
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
import psutil
import shutil

@dataclass
class CacheEntry:
    """Entrée de cache avec métadonnées"""
    local_path: str
    file_size: int
    file_hash: str
    download_time: float
    last_access: float
    access_count: int
    ttl: int  # Time To Live en secondes

class PerformanceCache:
    """Cache intelligent pour les fichiers iCloud"""
    
    def __init__(self, cache_dir: str = "/tmp/classifier_cache", max_size_gb: float = 5.0, ttl_hours: int = 24):
        """
        Initialise le cache intelligent
        
        Args:
            cache_dir: Répertoire du cache
            max_size_gb: Taille maximale du cache en Go
            ttl_hours: Durée de vie des entrées en heures
        """
        self.cache_dir = Path(cache_dir)
        self.max_size_bytes = max_size_gb * 1024**3
        self.ttl_seconds = ttl_hours * 3600
        
        # Structure de données
        self.entries: Dict[str, CacheEntry] = {}
        self.lock = threading.RLock()
        
        # Statistiques
        self.stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'downloads': 0,
            'total_size': 0
        }
        
        # Setup
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._load_cache_state()
        self._cleanup_expired()
    
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
    
    def _get_cache_key(self, mount_path: str) -> str:
        """Génère une clé de cache unique pour un chemin monté"""
        return hashlib.md5(mount_path.encode()).hexdigest()
    
    def _load_cache_state(self):
        """Charge l'état du cache depuis le disque"""
        state_file = self.cache_dir / ".cache_state.json"
        if state_file.exists():
            try:
                with open(state_file, 'r') as f:
                    data = json.load(f)
                    for key, entry_data in data.items():
                        self.entries[key] = CacheEntry(**entry_data)
            except Exception as e:
                print(f"⚠️ Erreur chargement état cache: {e}")
    
    def _save_cache_state(self):
        """Sauvegarde l'état du cache sur disque"""
        state_file = self.cache_dir / ".cache_state.json"
        try:
            with open(state_file, 'w') as f:
                data = {k: asdict(v) for k, v in self.entries.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"⚠️ Erreur sauvegarde état cache: {e}")
    
    def _get_current_size(self) -> int:
        """Calcule la taille actuelle du cache"""
        return sum(entry.file_size for entry in self.entries.values())
    
    def _evict_lru(self, target_size: int):
        """Éviction LRU pour libérer de l'espace"""
        if not self.entries:
            return
        
        # Trie par dernier accès
        sorted_entries = sorted(self.entries.items(), key=lambda x: x[1].last_access)
        
        evicted_size = 0
        to_remove = []
        
        for key, entry in sorted_entries:
            if self._get_current_size() - evicted_size <= target_size:
                break
            
            # Supprime le fichier
            if os.path.exists(entry.local_path):
                try:
                    os.remove(entry.local_path)
                    evicted_size += entry.file_size
                    to_remove.append(key)
                except Exception as e:
                    print(f"⚠️ Erreur suppression cache: {e}")
        
        # Met à jour les entrées
        for key in to_remove:
            del self.entries[key]
            self.stats['evictions'] += 1
        
        self.stats['total_size'] = self._get_current_size()
    
    def _cleanup_expired(self):
        """Nettoie les entrées expirées"""
        current_time = time.time()
        to_remove = []
        
        for key, entry in self.entries.items():
            if current_time - entry.download_time > self.ttl_seconds:
                if os.path.exists(entry.local_path):
                    try:
                        os.remove(entry.local_path)
                    except Exception:
                        pass
                to_remove.append(key)
        
        for key in to_remove:
            del self.entries[key]
    
    def get(self, mount_path: str) -> Optional[str]:
        """Récupère un fichier du cache"""
        with self.lock:
            key = self._get_cache_key(mount_path)
            
            if key in self.entries:
                entry = self.entries[key]
                
                # Vérifie expiration
                if time.time() - entry.download_time > self.ttl_seconds:
                    # Supprime l'entrée expirée
                    if os.path.exists(entry.local_path):
                        try:
                            os.remove(entry.local_path)
                        except Exception:
                            pass
                    del self.entries[key]
                    self.stats['misses'] += 1
                    return None
                
                # Vérifie existence fichier
                if not os.path.exists(entry.local_path):
                    del self.entries[key]
                    self.stats['misses'] += 1
                    return None
                
                # Met à jour statistiques d'accès
                entry.last_access = time.time()
                entry.access_count += 1
                self.stats['hits'] += 1
                
                return entry.local_path
            
            self.stats['misses'] += 1
            return None
    
    def put(self, mount_path: str, local_path: str) -> bool:
        """Ajoute un fichier au cache"""
        with self.lock:
            try:
                # Vérifie taille fichier
                file_size = os.path.getsize(local_path)
                if file_size == 0:
                    return False
                
                # Calcule hash
                file_hash = self._calculate_file_hash(local_path)
                if file_hash == "unknown":
                    return False
                
                key = self._get_cache_key(mount_path)
                
                # Vérifie si on doit évicter pour faire de la place
                current_size = self._get_current_size()
                if current_size + file_size > self.max_size_bytes:
                    # Libère 20% de la taille cible
                    target_size = int(self.max_size_bytes * 0.8)
                    self._evict_lru(target_size)
                
                # Crée l'entrée
                entry = CacheEntry(
                    local_path=str(local_path),
                    file_size=file_size,
                    file_hash=file_hash,
                    download_time=time.time(),
                    last_access=time.time(),
                    access_count=1,
                    ttl=self.ttl_seconds
                )
                
                self.entries[key] = entry
                self.stats['downloads'] += 1
                self.stats['total_size'] += file_size
                
                # Sauvegarde l'état
                self._save_cache_state()
                
                return True
                
            except Exception as e:
                print(f"❌ Erreur ajout cache: {e}")
                return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du cache"""
        with self.lock:
            current_time = time.time()
            active_entries = sum(1 for entry in self.entries.values() 
                               if current_time - entry.download_time <= self.ttl_seconds)
            
            return {
                'cache_size_mb': self.stats['total_size'] / (1024**2),
                'max_size_gb': self.max_size_bytes / (1024**3),
                'entries_count': len(self.entries),
                'active_entries': active_entries,
                'hits': self.stats['hits'],
                'misses': self.stats['misses'],
                'evictions': self.stats['evictions'],
                'downloads': self.stats['downloads'],
                'hit_rate': self.stats['hits'] / max(1, self.stats['hits'] + self.stats['misses'])
            }
    
    def clear(self):
        """Nettoie complètement le cache"""
        with self.lock:
            for entry in self.entries.values():
                if os.path.exists(entry.local_path):
                    try:
                        os.remove(entry.local_path)
                    except Exception:
                        pass
            
            self.entries.clear()
            self.stats = {'hits': 0, 'misses': 0, 'evictions': 0, 'downloads': 0, 'total_size': 0}
            
            # Supprime l'état
            state_file = self.cache_dir / ".cache_state.json"
            if state_file.exists():
                try:
                    os.remove(state_file)
                except Exception:
                    pass
    
    def get_memory_usage(self) -> Dict[str, float]:
        """Retourne l'utilisation mémoire système"""
        try:
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage(str(self.cache_dir.parent))
            
            return {
                'memory_percent': memory.percent,
                'memory_available_gb': memory.available / (1024**3),
                'disk_percent': disk.percent,
                'disk_free_gb': disk.free / (1024**3)
            }
        except Exception:
            return {'memory_percent': 0, 'memory_available_gb': 0, 'disk_percent': 0, 'disk_free_gb': 0}

# Instance globale de cache
global_cache = PerformanceCache()

def get_cached_file(mount_path: str, local_path: str) -> Optional[str]:
    """Fonction utilitaire pour obtenir un fichier avec cache"""
    # Essaye d'abord le cache
    cached = global_cache.get(mount_path)
    if cached:
        return cached
    
    # Si pas dans cache, vérifie si local existe déjà
    if os.path.exists(local_path) and os.path.getsize(local_path) > 100:
        # Ajoute au cache
        global_cache.put(mount_path, local_path)
        return local_path
    
    return None

def cache_stats() -> Dict:
    """Retourne les statistiques du cache global"""
    return global_cache.get_stats()

def cache_memory_usage() -> Dict:
    """Retourne l'utilisation mémoire"""
    return global_cache.get_memory_usage()

def clear_cache():
    """Nettoie le cache global"""
    global_cache.clear()