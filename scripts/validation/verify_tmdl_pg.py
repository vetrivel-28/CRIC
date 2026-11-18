import glob
import re
from backend.database.connection import DatabaseConnection

db = DatabaseConnection()

partition_info = {}
for path in glob.glob('powerbi/CRIC_Analytics_Dashboard_v2.SemanticModel/definition/tables/*.tmdl'):
    tname = path.split('\\')[-1].replace('.tmdl', '')
    cols = []
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    for line in content.split('\n'):
        c = re.match(r'^\s*column\s+(?:(?:\'([^\']+)\')|([^\s=]+))', line)
        if c:
            cols.append(c.group(1) or c.group(2))
    
    m_schema = re.search(r'Schema="([^"]+)"', content)
    m_item = re.search(r'Item="([^"]+)"', content)
    if m_schema and m_item:
        partition_info[tname] = {'schema': m_schema.group(1), 'item': m_item.group(1), 'cols': cols}
    else:
        print(f'NOTE: {tname} has custom/different partition expression')

print(f'Verifying {len(partition_info)} tables against PostgreSQL...')
with db.cursor() as cur:
    for tname, info in partition_info.items():
        s = info['schema']
        item = info['item']
        cur.execute('SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = %s AND table_name = %s', (s, item))
        db_cols = {row[0]: row[1] for row in cur.fetchall()}
        if not db_cols:
            print(f'ERROR: Table/view {s}.{item} not found in PostgreSQL!')
            continue
        missing_in_db = [c for c in info['cols'] if c not in db_cols]
        if missing_in_db:
            print(f'ERROR: In {tname}, TMDL columns missing in DB {s}.{item}: {missing_in_db}')
        else:
            print(f'OK: {tname} -> {s}.{item} ({len(info["cols"])} cols matched)')
