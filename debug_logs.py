#!/usr/bin/env python3
"""
Script de débogage pour le parsing des logs
"""

import json
from pathlib import Path

def test_log_parsing():
    """Teste le parsing des logs"""
    log_file = Path("/tmp/classifier_logs/documentclassifier.json")
    
    if not log_file.exists():
        print("❌ Fichier de logs non trouvé")
        return
    
    with open(log_file, 'r') as f:
        content = f.read().strip()
    
    print(f"📄 Contenu du fichier ({len(content)} caractères):")
    print(repr(content[:200]))
    print()
    
    # Test 1: Format tableau JSON
    if content.startswith('[') and content.endswith(']'):
        print("✅ Format tableau JSON détecté")
        try:
            logs_data = json.loads(content)
            print(f"✅ Parsing réussi: {len(logs_data)} entrées")
        except json.JSONDecodeError as e:
            print(f"❌ Erreur parsing tableau: {e}")
    else:
        print("✅ Format objet JSON par ligne détecté")
        
        # Test 2: Parsing ligne par ligne avec comptage accolades
        lines = content.split('\n')
        logs = []
        current_object_lines = []
        brace_count = 0
        
        print(f"📄 {len(lines)} lignes à parser")
        
        for i, line in enumerate(lines[:50]):  # Test sur les 50 premières lignes
            if not line.strip():
                continue
            
            current_object_lines.append(line)
            brace_count += line.count('{') - line.count('}')
            
            print(f"Line {i}: brace_count={brace_count}, line={repr(line[:50])}")
            
            if brace_count == 0 and current_object_lines:
                try:
                    log_entry = json.loads('\n'.join(current_object_lines))
                    logs.append(log_entry)
                    print(f"✅ Objet JSON parsé: {log_entry.get('message', 'No message')[:50]}")
                    current_object_lines = []
                except json.JSONDecodeError as e:
                    print(f"❌ Erreur parsing objet: {e}")
                    print(f"   Contenu accumulé: {repr('\n'.join(current_object_lines)[:100])}")
        
        print(f"✅ Parsing terminé: {len(logs)} entrées parsées")
        
        if logs:
            print(f"📄 Première entrée: {logs[0]}")

if __name__ == '__main__':
    test_log_parsing()