import glob
import re
import sys
sys.path.insert(0, '.')
from backend.database.connection import DatabaseConnection

db = DatabaseConnection()

for path in glob.glob('powerbi/CRIC_Analytics_Dashboard_v2.SemanticModel/definition/tables/*.tmdl'):
    tname = path.split('\\')[-1].replace('.tmdl', '')
    cols = {}
    with open(path, 'r', encoding='utf-8') as f:
        curr = None
        for line in f:
            c = re.match(r'^\s*column\s+(?:(?:\'([^\']+)\')|([^\s=]+))', line)
            if c:
                curr = c.group(1) or c.group(2)
            d = re.match(r'^\s*dataType:\s*(\w+)', line)
            if d and curr:
                cols[curr] = d.group(1)
                curr = None
    
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    m_schema = re.search(r'Schema="([^"]+)"', content)
    m_item = re.search(r'Item="([^"]+)"', content)
    if m_schema and m_item:
        s = m_schema.group(1)
        item = m_item.group(1)
        with db.cursor() as cur:
            cur.execute('SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = %s AND table_name = %s', (s, item))
            db_cols = {row[0]: row[1] for row in cur.fetchall()}
            for c, dt in cols.items():
                pg_t = db_cols.get(c, 'UNKNOWN')
                # check reasonable type alignment
                valid = True
                if dt == 'int64' and 'int' not in pg_t and 'bigint' not in pg_t and 'smallint' not in pg_t and pg_t != 'numeric':
                    valid = False
                elif dt == 'string' and 'char' not in pg_t and 'text' not in pg_t and pg_t != 'name':
                    valid = False
                elif dt == 'boolean' and pg_t != 'boolean':
                    valid = False
                elif dt == 'dateTime' and 'date' not in pg_t and 'time' not in pg_t:
                    valid = False
                elif dt == 'decimal' and pg_t not in ('numeric', 'double precision', 'real', 'integer', 'bigint'):
                    valid = False
                if not valid:
                    print(f'Type potential mismatch in {tname}.{c}: TMDL={dt} vs PG={pg_t}')
print('Data type compatibility scan finished.')
