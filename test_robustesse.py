#!/usr/bin/env python3
"""
TEST DE ROBUSTESSE - Validation des améliorations
Teste les nouvelles fonctionnalités de robustesse du classifier
"""

import os
import sys
import tempfile
import shutil
import json
from pathlib import Path

# Import les modules du projet
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from classifier_engine import (
    validate_system_requirements,
    validate_directories,
    validate_categories,
    DocumentClassifier,
    SystemError,
    ValidationError,
    FileProcessingError
)

def test_validation_system():
    """Teste la validation des prérequis système"""
    print("🧪 Test validation système...")
    
    try:
        validate_system_requirements()
        print("✅ Prérequis système validés")
        return True
    except SystemError as e:
        print(f"❌ Prérequis système manquants: {e}")
        return False

def test_validation_directories():
    """Teste la validation des dossiers"""
    print("🧪 Test validation dossiers...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        source_dir = os.path.join(temp_dir, "source")
        target_dir = os.path.join(temp_dir, "target")
        
        # Crée source
        os.makedirs(source_dir)
        
        try:
            validate_directories(source_dir, target_dir)
            print("✅ Validation dossiers réussie")
            return True
        except Exception as e:
            print(f"❌ Erreur validation dossiers: {e}")
            return False

def test_validation_categories():
    """Teste la validation des catégories"""
    print("🧪 Test validation catégories...")
    
    valid_categories = ["facture", "contrat", "administratif"]
    invalid_categories = ["", "cat/égorie", "cat<>égorie"]
    
    try:
        validate_categories(valid_categories)
        print("✅ Catégories valides acceptées")
        
        try:
            validate_categories(invalid_categories)
            print("❌ Catégories invalides acceptées")
            return False
        except ValidationError:
            print("✅ Catégories invalides rejetées")
            return True
            
    except Exception as e:
        print(f"❌ Erreur validation catégories: {e}")
        return False

def test_classifier_initialization():
    """Teste l'initialisation du classifier avec validation"""
    print("🧪 Test initialisation classifier...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        source_dir = os.path.join(temp_dir, "source")
        target_dir = os.path.join(temp_dir, "target")
        categories = ["facture", "contrat", "autre"]
        
        os.makedirs(source_dir)
        
        try:
            classifier = DocumentClassifier(
                source_dir=source_dir,
                target_dir=target_dir,
                categories=categories,
                confidence_threshold=0.7,
                dry_run=True,
                verbose=True
            )
            print("✅ Classifier initialisé avec succès")
            
            # Vérifie les dossiers créés
            assert os.path.exists(target_dir)
            assert os.path.exists(classifier.ocr_dir)
            assert os.path.exists(classifier.doubtful_dir)
            assert os.path.exists(classifier.cache_dir)
            
            print("✅ Dossiers spéciaux créés")
            return True
            
        except Exception as e:
            print(f"❌ Erreur initialisation classifier: {e}")
            return False

def test_transaction_manager():
    """Teste le gestionnaire de transactions"""
    print("🧪 Test gestionnaire de transactions...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        source_dir = os.path.join(temp_dir, "source")
        target_dir = os.path.join(temp_dir, "target")
        categories = ["test"]
        
        os.makedirs(source_dir)
        
        # Crée un fichier test
        test_file = os.path.join(source_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("Contenu de test pour transaction")
        
        try:
            classifier = DocumentClassifier(
                source_dir=source_dir,
                target_dir=target_dir,
                categories=categories,
                dry_run=False,
                verbose=True
            )
            
            # Test création transaction
            transaction = classifier.transaction_manager.create_transaction(
                test_file, "test.txt", "test"
            )
            
            assert os.path.exists(transaction.backup_path)
            assert transaction.filename == "test.txt"
            assert transaction.category == "test"
            
            print("✅ Transaction créée avec backup")
            
            # Test rollback
            classifier.transaction_manager.rollback_transaction(transaction)
            assert os.path.exists(test_file)  # Fichier restauré
            
            print("✅ Rollback fonctionnel")
            return True
            
        except Exception as e:
            print(f"❌ Erreur gestionnaire transactions: {e}")
            return False

def test_error_handling():
    """Teste la gestion des erreurs"""
    print("🧪 Test gestion erreurs...")
    
    # Test dossier source inexistant
    try:
        validate_directories("/chemin/inexistant", "/tmp/test")
        print("❌ Dossier inexistant accepté")
        return False
    except ValidationError:
        print("✅ Dossier inexistant rejeté")
    
    # Test seuil invalide
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = os.path.join(temp_dir, "source")
            target_dir = os.path.join(temp_dir, "target")
            os.makedirs(source_dir)
            
            DocumentClassifier(
                source_dir=source_dir,
                target_dir=target_dir,
                categories=["test"],
                confidence_threshold=1.5,  # Invalide
                dry_run=True
            )
        print("❌ Seuil invalide accepté")
        return False
    except ValidationError:
        print("✅ Seuil invalide rejeté")
    
    return True

def test_cleanup_backups():
    """Teste le nettoyage des backups"""
    print("🧪 Test nettoyage backups...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        target_dir = os.path.join(temp_dir, "target")
        backup_dir = os.path.join(target_dir, ".backup")
        os.makedirs(backup_dir)
        
        # Crée des backups anciens et récents
        old_backup = os.path.join(backup_dir, "old.backup")
        new_backup = os.path.join(backup_dir, "new.backup")
        
        with open(old_backup, 'w') as f:
            f.write("old")
        with open(new_backup, 'w') as f:
            f.write("new")
        
        # Simule un backup ancien (24h+)
        old_time = os.path.getctime(old_backup) - (25 * 3600)
        os.utime(old_backup, (old_time, old_time))
        
        try:
            classifier = DocumentClassifier(
                source_dir="/tmp/source",
                target_dir=target_dir,
                categories=["test"],
                dry_run=True
            )
            
            classifier._cleanup_old_backups()
            
            # Vérifie que seul le backup ancien est supprimé
            assert not os.path.exists(old_backup)
            assert os.path.exists(new_backup)
            
            print("✅ Nettoyage backups fonctionnel")
            return True
            
        except Exception as e:
            print(f"❌ Erreur nettoyage backups: {e}")
            return False

def run_all_tests():
    """Exécute tous les tests"""
    print("🚀 LANCEMENT DES TESTS DE ROBUSTESSE")
    print("=" * 50)
    
    tests = [
        test_validation_system,
        test_validation_directories,
        test_validation_categories,
        test_classifier_initialization,
        test_transaction_manager,
        test_error_handling,
        test_cleanup_backups
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"❌ Test échoué avec exception: {e}")
            results.append(False)
        print()
    
    # Résumé
    passed = sum(results)
    total = len(results)
    
    print("=" * 50)
    print(f"📊 RÉSULTATS: {passed}/{total} tests passés")
    
    if passed == total:
        print("🎉 Tous les tests de robustesse sont passés !")
        return True
    else:
        print("⚠️  Certains tests ont échoué")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)