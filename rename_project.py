import os
import re

def replace_in_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return
    
    new_content = content
    # Replace in code identifiers (no spaces)
    new_content = re.sub(r'Analise CertiDigital([A-Za-z0-9_])', r'AnaliseCertiDigital\1', new_content)
    # Replace the remaining standalone Analise CertiDigital with Analise CertiDigital
    new_content = re.sub(r'Analise CertiDigital\b', r'Analise CertiDigital', new_content)
    
    # Lowercase replacements
    new_content = new_content.replace('analise_certidigital', 'analise_certidigital')
    new_content = new_content.replace('ANALISE_CERTIDIGITAL', 'ANALISE_CERTIDIGITAL')
    
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated content of {filepath}")

for root, dirs, files in os.walk('.', topdown=False):
    if '.git' in root or 'node_modules' in root or '__pycache__' in root or 'venv' in root or '.pytest_cache' in root or 'dist' in root or 'build' in root:
        continue
    for file in files:
        if file.endswith(('.py', '.html', '.js', '.css', '.md', '.sql', '.ps1', '.spec', '.iss', '.yaml', '.txt', '.env.example')):
            replace_in_file(os.path.join(root, file))

# Now rename files and directories
for root, dirs, files in os.walk('.', topdown=False):
    if '.git' in root or 'node_modules' in root or '__pycache__' in root or 'venv' in root or '.pytest_cache' in root or 'dist' in root or 'build' in root:
        continue
    for name in files + dirs:
        if 'Analise CertiDigital' in name or 'analise_certidigital' in name:
            old_path = os.path.join(root, name)
            new_name = name.replace('Analise CertiDigital', 'AnaliseCertiDigital').replace('analise_certidigital', 'analise_certidigital')
            new_path = os.path.join(root, new_name)
            os.rename(old_path, new_path)
            print(f"Renamed {old_path} to {new_path}")
