import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv('.env')
url = os.environ.get('SUPABASE_URL')
key = os.environ.get('SUPABASE_SERVICE_KEY')

if not url or not key:
    print('Erro: credenciais do Supabase ausentes no .env')
    exit(1)

supabase: Client = create_client(url, key)

response = supabase.table('cert_snapshots').select('scanned_at, machine_id, items').order('scanned_at', desc=True).limit(1).execute()

if response.data:
    row = response.data[0]
    scanned = row.get('scanned_at')
    mid = row.get('machine_id')
    items = row.get('items', [])
    print(f'Última atualização:')
    print(f'  - Data/Hora: {scanned}')
    print(f'  - Máquina: {mid}')
    print(f'  - Itens enviados: {len(items)}')
else:
    print('Nenhuma atualização encontrada na tabela cert_snapshots.')
