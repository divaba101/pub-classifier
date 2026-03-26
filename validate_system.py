#!/usr/bin/env python3
"""
VALIDATION SYSTÈME - Vérification des prérequis
Vérifie que tous les prérequis système sont installés et configurés
"""

import subprocess
import sys
import os
import shutil
import psutil

def check_command(cmd, args=None, timeout=10):
    """Vérifie si une commande est disponible et fonctionnelle"""
    try:
        if args:
            result = subprocess.run([cmd] + args, capture_output=True, text=True, timeout=timeout)
        else:
            result = subprocess.run([cmd], capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout, result.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, "", str(e)

def check_ollama():
    """Vérifie Ollama"""
    print("🔍 Vérification Ollama...")
    
    success, stdout, stderr = check_command('ollama', ['list'])
    if success:
        print("✅ Ollama disponible")
        print(f"   Modèles installés: {len(stdout.strip().splitlines()) - 1}")
        return True
    else:
        print("❌ Ollama non disponible")
        print(f"   Erreur: {stderr}")
        return False

def check_tesseract():
    """Vérifie Tesseract"""
    print("🔍 Vérification Tesseract...")
    
    success, stdout, stderr = check_command('tesseract', ['--version'])
    if success:
        print("✅ Tesseract disponible")
        version_line = stdout.split('\n')[0]
        print(f"   Version: {version_line}")
        
        # Vérifie langues
        success, stdout, stderr = check_command('tesseract', ['--list-langs'])
        if success:
            langs = stdout.strip().split('\n')[1:]  # Skip header
            if 'fra' in langs:
                print("✅ Langue française disponible")
            else:
                print("⚠️  Langue française non disponible (français)")
        return True
    else:
        print("❌ Tesseract non disponible")
        print(f"   Erreur: {stderr}")
        return False

def check_poppler():
    """Vérifie Poppler (pdftoppm)"""
    print("🔍 Vérification Poppler...")
    
    success, stdout, stderr = check_command('pdftoppm', ['-v'])
    if success:
        print("✅ Poppler disponible")
        print(f"   Version: {stdout.strip()}")
        return True
    else:
        print("❌ Poppler non disponible")
        print(f"   Erreur: {stderr}")
        return False

def check_python_packages():
    """Vérifie les packages Python"""
    print("🔍 Vérification packages Python...")
    
    required_packages = [
        'ollama', 'pypdf', 'docx2txt', 'openpyxl', 'xlrd',
        'flask', 'flask_cors', 'flask_socketio', 'psutil'
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package)
            print(f"   ✅ {package}")
        except ImportError:
            print(f"   ❌ {package}")
            missing.append(package)
    
    if missing:
        print(f"❌ Packages manquants: {', '.join(missing)}")
        return False
    else:
        print("✅ Tous les packages Python sont installés")
        return True

def check_disk_space(path="/tmp"):
    """Vérifie l'espace disque"""
    print(f"🔍 Vérification espace disque ({path})...")
    
    try:
        disk_usage = psutil.disk_usage(path)
        free_gb = disk_usage.free / (1024**3)
        
        if free_gb >= 1:
            print(f"✅ Espace disque suffisant: {free_gb:.2f} GB")
            return True
        else:
            print(f"❌ Espace disque insuffisant: {free_gb:.2f} GB (< 1GB requis)")
            return False
    except Exception as e:
        print(f"❌ Erreur vérification espace disque: {e}")
        return False

def check_permissions(path):
    """Vérifie les permissions d'écriture"""
    print(f"🔍 Vérification permissions ({path})...")
    
    try:
        # Test écriture
        test_file = os.path.join(path, '.test_write')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        
        print("✅ Permissions d'écriture OK")
        return True
    except PermissionError:
        print("❌ Permissions d'écriture refusées")
        return False
    except Exception as e:
        print(f"❌ Erreur vérification permissions: {e}")
        return False

def check_model_availability():
    """Vérifie la disponibilité du modèle IA"""
    print("🔍 Vérification modèle IA...")
    
    try:
        import ollama
        
        # Liste les modèles
        models = ollama.list()
        model_names = [m['name'] for m in models['models']]
        
        if 'mistral' in model_names:
            print("✅ Modèle 'mistral' disponible")
            return True
        else:
            print("⚠️  Modèle 'mistral' non trouvé")
            print(f"   Modèles disponibles: {', '.join(model_names)}")
            
            # Propose d'installer mistral
            print("💡 Pour installer mistral: ollama pull mistral")
            return False
            
    except Exception as e:
        print(f"❌ Erreur vérification modèle: {e}")
        return False

def run_validation():
    """Exécute toutes les validations"""
    print("🚀 VALIDATION SYSTÈME - DOCUMENT CLASSIFIER")
    print("=" * 50)
    
    checks = [
        ("Ollama", check_ollama),
        ("Tesseract", check_tesseract),
        ("Poppler", check_poppler),
        ("Packages Python", check_python_packages),
        ("Espace disque", lambda: check_disk_space("/tmp")),
        ("Permissions", lambda: check_permissions("/tmp")),
        ("Modèle IA", check_model_availability)
    ]
    
    results = []
    for name, check_func in checks:
        print(f"\n📋 {name}")
        print("-" * 30)
        try:
            result = check_func()
            results.append(result)
        except Exception as e:
            print(f"❌ Erreur lors de la vérification {name}: {e}")
            results.append(False)
    
    # Résumé
    print("\n" + "=" * 50)
    print("📊 RÉSULTATS DE LA VALIDATION")
    print("=" * 50)
    
    passed = sum(results)
    total = len(results)
    
    for i, (name, _) in enumerate(checks):
        status = "✅" if results[i] else "❌"
        print(f"{status} {name}")
    
    print(f"\nTotal: {passed}/{total} vérifications passées")
    
    if passed == total:
        print("\n🎉 Toutes les vérifications sont passées !")
        print("Le système est prêt pour le document classifier.")
        return True
    else:
        print(f"\n⚠️  {total - passed} vérifications ont échoué.")
        print("Veuillez corriger les problèmes avant d'utiliser le classifier.")
        return False

if __name__ == "__main__":
    success = run_validation()
    sys.exit(0 if success else 1)