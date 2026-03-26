#!/usr/bin/env python3
"""
Test direct du parsing dans un contexte similaire à l'endpoint Flask
"""

import json
from pathlib import Path

def test_endpoint_parsing():
    """Teste le parsing comme dans l'endpoint Flask"""
    filename = "documentclassifier.json"
    log_dir = Path("/tmp/classifier_logs")
    log_file = log_dir / filename
    
    print(f"🔍 Testing endpoint parsing for: {log_file}")
    
    if not log_file.exists():
        print("❌ File not found")
        return
    
    print("✅ File exists")
    
    logs = []
    with open(log_file, 'r') as f:
        content = f.read().strip()
        
    print(f"📄 Content length: {len(content)} characters")
    
    if not content:
        print("❌ File is empty")
        return
    
    # Parser selon le format (copie exacte de l'endpoint)
    if content.startswith('[') and content.endswith(']'):
        print("✅ Format tableau JSON détecté")
        # Format tableau JSON
        logs_data = json.loads(content)
        if isinstance(logs_data, list):
            logs = logs_data
        else:
            logs = [logs_data] if logs_data else []
    else:
        print("✅ Format objet JSON par ligne détecté")
        # Format un objet JSON par ligne avec indentation
        lines = content.split('\n')
        print(f"📄 Total lines: {len(lines)}")
        
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
                        print(f"✅ Parsed log entry {len(logs)}: {log_entry.get('message', 'No message')[:50]}")
                except json.JSONDecodeError as e:
                    print(f"❌ JSON decode error at line {i}: {e}")
                    print(f"   Content: {repr(line[:100])}")
                    # Continuer à accumuler les lignes
                    pass
        
        # Traiter le dernier objet accumulé
        if current_object_lines:
            try:
                log_entry = json.loads('\n'.join(current_object_lines))
                logs.append(log_entry)
                print(f"✅ Parsed final log entry: {log_entry.get('message', 'No message')[:50]}")
            except json.JSONDecodeError as e:
                print(f"❌ JSON decode error for final object: {e}")
    
    print(f"✅ Successfully parsed {len(logs)} log entries")
    
    if logs:
        print(f"📄 First entry: {logs[0]}")
        print(f"📄 Last entry: {logs[-1]}")

if __name__ == '__main__':
    test_endpoint_parsing()