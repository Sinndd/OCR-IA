import fitz
import json

clients = {
    'CLIENT_D': 'BC_4095113_StyleD.pdf',
    'CLIENT_E': 'BC_9814754_StyleE.pdf', 
    'CLIENT_F': 'BC_3521156_StyleF.pdf',
    'CLIENT_G': 'BC_7189219_StyleG.pdf',
    'CLIENT_H': 'BC_5422424_StyleH.pdf'
}

for client, pdf_file in clients.items():
    pdf_path = f'{client}/{pdf_file}'
    try:
        doc = fitz.open(pdf_path)
        text = ''
        for page in doc:
            text += page.get_text()
        doc.close()
        
        with open(f'{client}/training_bc.txt', 'w', encoding='utf-8') as f:
            f.write(text)
        
        print(f'✓ {client}: Texte extrait ({len(text)} caractères)')
        print(f'  Fichier: {pdf_file}')
        print(f'  Preview: {text[:150]}...')
        print()
    except Exception as e:
        print(f'✗ {client}: Erreur - {e}')
        print()
