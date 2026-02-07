# 按起止位置读取章节内容
def read_chapter_text(novel_id, start, end):
    conn = get_db()
    cur = conn.execute('SELECT path FROM novels WHERE id = ?', (novel_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return ''
    path = Path(row['path'])
    if not path.exists():
        return ''
    content, _ = memdb_get(str(path.resolve()))
    if content is None:
        try:
            content = read_text_with_encoding(path)
        except Exception:
            return ''
        try:
            memdb_set(str(path.resolve()), content, path.stat().st_mtime)
        except Exception:
            pass
    return content[start:end] if end > start else ''
import sqlite3
from pathlib import Path
import datetime
import re
import chardet
import threading

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'novels.db'
NOVELS_DIR = BASE_DIR / 'novels'
NOVELS_DIR.mkdir(parents=True, exist_ok=True)


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    # Create table with new columns if not exists
    conn.execute('''
    CREATE TABLE IF NOT EXISTS novels (
        id INTEGER PRIMARY KEY,
        filename TEXT,
        path TEXT UNIQUE,
        first100 TEXT,
        added_at TEXT,
        size INTEGER,
        chars INTEGER
    )
    ''')
    # Ensure columns exist for older DBs: add if missing
    cur = conn.execute("PRAGMA table_info('novels')")
    cols = [r[1] for r in cur.fetchall()]
    if 'size' not in cols:
        try:
            conn.execute('ALTER TABLE novels ADD COLUMN size INTEGER')
        except Exception:
            pass
    if 'chars' not in cols:
        try:
            conn.execute('ALTER TABLE novels ADD COLUMN chars INTEGER')
        except Exception:
            pass
    # Create an index on filename for faster lookup
    try:
        conn.execute('CREATE INDEX IF NOT EXISTS idx_novels_filename ON novels(filename)')
    except Exception:
        pass
    conn.commit()
    conn.close()


def read_text_with_encoding(file_path: Path) -> str:
    try:
        return file_path.read_text(encoding='utf-8')
    except Exception:
        raw = file_path.read_bytes()
        info = chardet.detect(raw)
        enc = info.get('encoding') or 'utf-8'
        try:
            return raw.decode(enc, errors='ignore')
        except Exception:
            return raw.decode('utf-8', errors='ignore')


def auto_split_into_chapters(text: str, chunk_size: int = 10000):
    chapters = []
    n = len(text)
    if n == 0:
        return [{'title': '空内容', 'start': 0, 'end': 0}]
    pos = 0
    idx = 0
    while pos < n:
        end = min(pos + chunk_size, n)
        seg = text[pos:end]
        split_at = seg.rfind('\n\n')
        if split_at == -1:
            split_at = seg.rfind('\n')
        if split_at <= 0:
            split_at = len(seg)
        chapter_end = pos + split_at
        if chapter_end <= pos:
            chapter_end = end
        idx += 1
        title = f'第{idx}节'
        chapters.append({'title': title, 'start': pos, 'end': chapter_end})
        pos = chapter_end
    return chapters


def extract_chapters(text: str):
    patterns = [r'(^\s*第[^\n]{1,30}章[^\n]*)', r'(^\s*Chapter\s+\d+[^\n]*)']
    matches = []
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE | re.MULTILINE):
            matches.append((m.start(1), m.group(1).strip()))
    matches = sorted({(pos, title) for pos, title in matches}, key=lambda x: x[0])
    if not matches:
        return auto_split_into_chapters(text)
    chapters = []
    for i, (start, title) in enumerate(matches):
        end = matches[i+1][0] if i+1 < len(matches) else len(text)
        chapters.append({'title': title[:20], 'start': start, 'end': end})
    return chapters


# in-memory sqlite cache
_MEM_DB_CONN = None
_MEM_DB_LOCK = threading.Lock()


def init_mem_db():
    global _MEM_DB_CONN
    with _MEM_DB_LOCK:
        if _MEM_DB_CONN is None:
            _MEM_DB_CONN = sqlite3.connect(':memory:', check_same_thread=False)
            cur = _MEM_DB_CONN.cursor()
            cur.execute('CREATE TABLE IF NOT EXISTS mem_cache (path TEXT PRIMARY KEY, text TEXT, mtime REAL)')
            _MEM_DB_CONN.commit()


def memdb_set(path: str, text: str, mtime: float | None):
    if _MEM_DB_CONN is None:
        init_mem_db()
    try:
        cur = _MEM_DB_CONN.cursor()
        cur.execute('REPLACE INTO mem_cache (path, text, mtime) VALUES (?,?,?)', (path, text, mtime))
        _MEM_DB_CONN.commit()
    except Exception:
        pass


def memdb_get(path: str):
    if _MEM_DB_CONN is None:
        init_mem_db()
    try:
        cur = _MEM_DB_CONN.cursor()
        cur.execute('SELECT text, mtime FROM mem_cache WHERE path = ?', (path,))
        row = cur.fetchone()
        if row:
            return row[0], row[1]
    except Exception:
        pass
    return None, None


def index_file(file_path: Path):
    if not file_path.exists() or not file_path.is_file():
        return False, 'file not found'
    conn = get_db()
    cur = conn.execute('SELECT 1 FROM novels WHERE path = ?', (str(file_path.resolve()),))
    is_already_indexed = cur.fetchone() is not None
    if is_already_indexed:
        conn.close()
        return False, 'file already indexed'

    try:
        text = read_text_with_encoding(file_path)
    except Exception as e:
        return False, f'read error: {e}'
    first100 = ' '.join(text.strip().split())[:100]
    size = None
    try:
        size = file_path.stat().st_size
    except Exception:
        size = None
    chars = len(text)
    conn = get_db()
    conn.execute(
        'REPLACE INTO novels (filename, path, first100, added_at, size, chars) VALUES (?,?,?,?,?,?)',
        (file_path.name, str(file_path.resolve()), first100, datetime.datetime.utcnow().isoformat(), size, chars)
    )
    conn.commit()
    conn.close()
    # cache into mem sqlite
    try:
        memdb_set(str(file_path.resolve()), text, file_path.stat().st_mtime)
    except Exception:
        pass
    return True, None
