import shutil
from pathlib import Path
import utils
import datetime

DB = utils.DB_PATH
if DB.exists():
    bak = DB.with_suffix('.db.bak')
    try:
        shutil.copy2(DB, bak)
        print(f'Existing DB backed up to {bak}')
    except Exception as e:
        print(f'Backup failed: {e}')
    try:
        DB.unlink()
        print('Removed existing DB')
    except Exception as e:
        print(f'Failed to remove existing DB: {e}')

# initialize new DB
utils.init_db()
# index all .txt files under NOVELS_DIR
count = 0
for p in utils.NOVELS_DIR.rglob('*.txt'):
    ok, err = utils.index_file(p)
    if ok:
        count += 1
    else:
        print(f'Failed to index {p}: {err}')
print(f'Indexed {count} files into {utils.DB_PATH}')
