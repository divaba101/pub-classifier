#!/usr/bin/env python3
"""
OLLAMA POOL - Pool de connexions Ollama pour performance
Pool de connexions avec gestion de la concurrence et cache des réponses
"""

import time
import threading
import queue
import json
from typing import Optional, Dict, Any, List
import hashlib
import logging

try:
    import ollama
except ImportError:
    ollama = None

class OllamaConnection:
    """Connexion Ollama avec gestion d'erreur"""
    
    def __init__(self, model: str = 'mistral'):
        self.model = model
        self.last_used = time.time()
        self.error_count = 0
        self.lock = threading.Lock()
    
    def generate(self, prompt: str, timeout: int = 60) -> Optional[Dict]:
        """Génère une réponse avec gestion d'erreur"""
        with self.lock:
            try:
                # Vérifie si Ollama est disponible
                if ollama is None:
                    raise ImportError("Ollama non installé")
                
                # Test connexion
                ollama.list()
                
                # Génération (sans timeout dans l'appel direct)
                result = ollama.generate(model=self.model, prompt=prompt)
                self.error_count = 0
                self.last_used = time.time()
                return result
                
            except Exception as e:
                self.error_count += 1
                logging.error(f"Erreur Ollama: {e}")
                return None

class OllamaPool:
    """Pool de connexions Ollama avec cache et gestion de la concurrence"""
    
    def __init__(self, model: str = 'mistral', max_connections: int = 4, cache_size: int = 1000):
        """
        Initialise le pool Ollama
        
        Args:
            model: Modèle à utiliser
            max_connections: Nombre maximum de connexions
            cache_size: Taille du cache de réponses
        """
        self.model = model
        self.max_connections = max_connections
        self.cache_size = cache_size
        
        # Pool de connexions
        self.connections = queue.Queue(maxsize=max_connections)
        self.active_connections = 0
        self.pool_lock = threading.Lock()
        
        # Cache des réponses
        self.response_cache = {}
        self.cache_access = threading.RLock()
        
        # Statistiques
        self.stats = {
            'requests': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'errors': 0,
            'avg_response_time': 0.0,
            'ollama_available': False
        }
        
        # Setup (sans blocage)
        self._setup_pool()
    
    def _setup_pool(self):
        """Setup le pool sans bloquer l'initialisation"""
        try:
            # Test rapide de disponibilité Ollama
            if ollama is not None:
                ollama.list()
                self.stats['ollama_available'] = True
                # Initialisation des connexions en arrière-plan
                threading.Thread(target=self._initialize_connections, daemon=True).start()
            else:
                logging.warning("Ollama non installé - pool désactivé")
        except Exception as e:
            logging.warning(f"Ollama non disponible: {e}")
    
    def _initialize_connections(self):
        """Initialise les connexions du pool"""
        for _ in range(self.max_connections):
            try:
                conn = OllamaConnection(self.model)
                # Test la connexion avec timeout court
                if conn.generate("test", timeout=2):
                    self.connections.put(conn)
                else:
                    logging.warning("Connexion Ollama non fonctionnelle")
            except Exception as e:
                logging.warning(f"Connexion Ollama non disponible: {e}")
    
    def _get_cache_key(self, prompt: str) -> str:
        """Génère une clé de cache pour un prompt"""
        return hashlib.md5(prompt.encode()).hexdigest()
    
    def _cleanup_cache(self):
        """Nettoie le cache si trop volumineux"""
        if len(self.response_cache) > self.cache_size:
            # Supprime les 20% les plus anciens
            sorted_items = sorted(self.response_cache.items(), key=lambda x: x[1]['timestamp'])
            to_remove = int(len(sorted_items) * 0.2)
            
            for i in range(to_remove):
                del self.response_cache[sorted_items[i][0]]
    
    def get_connection(self) -> Optional[OllamaConnection]:
        """Obtient une connexion du pool"""
        with self.pool_lock:
            try:
                conn = self.connections.get_nowait()
                self.active_connections += 1
                return conn
            except queue.Empty:
                return None
    
    def return_connection(self, conn: OllamaConnection):
        """Retourne une connexion au pool"""
        with self.pool_lock:
            if conn.error_count < 3:  # Ne pas remettre les connexions en échec
                self.connections.put(conn)
            self.active_connections -= 1
    
    def generate_with_cache(self, prompt: str, timeout: int = 60) -> Optional[str]:
        """Génère une réponse avec cache"""
        start_time = time.time()
        self.stats['requests'] += 1
        
        # Vérifie le cache
        cache_key = self._get_cache_key(prompt)
        
        with self.cache_access:
            if cache_key in self.response_cache:
                cached = self.response_cache[cache_key]
                # Vérifie TTL (1 heure)
                if time.time() - cached['timestamp'] < 3600:
                    self.stats['cache_hits'] += 1
                    self.stats['avg_response_time'] = (
                        self.stats['avg_response_time'] * 0.9 + 
                        (time.time() - start_time) * 0.1
                    )
                    return cached['response']
        
        # Cache miss
        self.stats['cache_misses'] += 1
        
        # Obtient connexion
        conn = self.get_connection()
        if not conn:
            self.stats['errors'] += 1
            return None
        
        try:
            # Génération
            result = conn.generate(prompt, timeout)
            if result and 'response' in result:
                response = result['response'].strip()
                
                # Met à jour cache
                with self.cache_access:
                    self.response_cache[cache_key] = {
                        'response': response,
                        'timestamp': time.time()
                    }
                    self._cleanup_cache()
                
                # Met à jour statistiques
                response_time = time.time() - start_time
                self.stats['avg_response_time'] = (
                    self.stats['avg_response_time'] * 0.9 + 
                    response_time * 0.1
                )
                
                return response
            else:
                self.stats['errors'] += 1
                return None
                
        finally:
            self.return_connection(conn)
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du pool"""
        with self.cache_access:
            cache_hit_rate = self.stats['cache_hits'] / max(1, self.stats['requests'])
        
        return {
            'model': self.model,
            'max_connections': self.max_connections,
            'active_connections': self.active_connections,
            'cache_size': len(self.response_cache),
            'cache_hit_rate': cache_hit_rate,
            'total_requests': self.stats['requests'],
            'cache_hits': self.stats['cache_hits'],
            'cache_misses': self.stats['cache_misses'],
            'errors': self.stats['errors'],
            'avg_response_time': self.stats['avg_response_time']
        }
    
    def clear_cache(self):
        """Nettoie le cache des réponses"""
        with self.cache_access:
            self.response_cache.clear()
    
    def health_check(self) -> Dict[str, Any]:
        """Vérifie la santé du pool"""
        stats = self.get_stats()
        
        # Test une connexion
        test_conn = self.get_connection()
        if test_conn:
            test_result = test_conn.generate("ping", timeout=5)
            self.return_connection(test_conn)
            pool_healthy = test_result is not None
        else:
            pool_healthy = False
        
        return {
            'healthy': pool_healthy,
            'stats': stats,
            'recommendations': self._get_recommendations(stats)
        }
    
    def _get_recommendations(self, stats: Dict) -> List[str]:
        """Donne des recommandations basées sur les statistiques"""
        recommendations = []
        
        if stats['cache_hit_rate'] < 0.3:
            recommendations.append("Augmenter la taille du cache ou améliorer la similarité des prompts")
        
        if stats['errors'] > stats['total_requests'] * 0.1:
            recommendations.append("Taux d'erreurs élevé, vérifier la disponibilité d'Ollama")
        
        if stats['avg_response_time'] > 30:
            recommendations.append("Temps de réponse lent, envisager d'augmenter le nombre de connexions")
        
        if stats['active_connections'] == stats['max_connections']:
            recommendations.append("Pool saturé, augmenter max_connections")
        
        return recommendations

# Instance globale du pool
global_ollama_pool = OllamaPool()

def generate_with_pool(prompt: str, model: str = 'mistral', timeout: int = 60) -> Optional[str]:
    """Fonction utilitaire pour générer avec le pool global"""
    global global_ollama_pool
    
    if global_ollama_pool.model != model:
        # Recrée le pool avec le bon modèle
        global_ollama_pool = OllamaPool(model=model)
    
    return global_ollama_pool.generate_with_cache(prompt, timeout)

def pool_stats() -> Dict:
    """Retourne les statistiques du pool global"""
    return global_ollama_pool.get_stats()

def pool_health() -> Dict:
    """Retourne la santé du pool global"""
    return global_ollama_pool.health_check()

def clear_pool_cache():
    """Nettoie le cache du pool global"""
    global_ollama_pool.clear_cache()