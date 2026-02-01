#!/usr/bin/env python3
"""
OCR PROCESSOR - Traitement des documents scannés
Extrait le texte des PDFs scannés et images
"""
import sys
import os
import subprocess
from pathlib import Path

def process_with_tesseract(input_file: str, output_file: str) -> bool:
    """
    Traite un fichier avec Tesseract OCR
    
    Args:
        input_file: Chemin du fichier à OCRiser (PDF ou image)
        output_file: Chemin du fichier texte de sortie
    
    Returns:
        True si succès, False sinon
    """
    try:
        ext = Path(input_file).suffix.lower()
        
        if ext == '.pdf':
            # Pour PDF: convertir en images puis OCR
            # Nécessite poppler-utils (pdftoppm)
            temp_dir = "/tmp/ocr_temp"
            os.makedirs(temp_dir, exist_ok=True)
            
            # Convert PDF to images
            subprocess.run([
                'pdftoppm',
                '-png',
                input_file,
                os.path.join(temp_dir, 'page')
            ], check=True)
            
            # OCR chaque page
            all_text = []
            for page_img in sorted(Path(temp_dir).glob('page-*.png')):
                result = subprocess.run([
                    'tesseract',
                    str(page_img),
                    'stdout',
                    '-l', 'fra+eng'  # Français + Anglais
                ], capture_output=True, text=True, check=True)
                
                all_text.append(result.stdout)
            
            # Sauvegarde
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write('\n\n'.join(all_text))
            
            # Cleanup
            import shutil
            shutil.rmtree(temp_dir)
            
        elif ext in {'.png', '.jpg', '.jpeg', '.tiff', '.bmp'}:
            # Image directe
            result = subprocess.run([
                'tesseract',
                input_file,
                output_file.replace('.txt', ''),  # Tesseract ajoute .txt automatiquement
                '-l', 'fra+eng'
            ], check=True)
        
        else:
            print(f"Format non supporté: {ext}", file=sys.stderr)
            return False
        
        return os.path.exists(output_file)
    
    except subprocess.CalledProcessError as e:
        print(f"Erreur Tesseract: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Erreur OCR: {e}", file=sys.stderr)
        return False

def main():
    if len(sys.argv) != 3:
        print("Usage: python ocr_processor.py <input_file> <output_file>", file=sys.stderr)
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    if not os.path.exists(input_file):
        print(f"Fichier introuvable: {input_file}", file=sys.stderr)
        sys.exit(1)
    
    print(f"🔍 OCR processing: {input_file}")
    
    success = process_with_tesseract(input_file, output_file)
    
    if success:
        print(f"✅ OCR terminé: {output_file}")
        sys.exit(0)
    else:
        print(f"❌ OCR échoué", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
