from flask import Flask, render_template, request, redirect, url_for, flash, abort
import sqlite3
import os
from pathlib import Path
import datetime
import re
import math

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'novels.db'
NOVELS_DIR = BASE_DIR / 'novels'
NOVELS_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = 'change-me-in-prod'


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute('''
    CREATE TABLE IF NOT EXISTS novels (
        id INTEGER PRIMARY KEY,
        filename TEXT,
        path TEXT UNIQUE,
        first100 TEXT,
        added_at TEXT
    )
    ''')
    conn.commit()
    conn.close()


def index_file(file_path: Path):
    if not file_path.exists() or not file_path.is_file():
        return False, 'file not found'
    try:
        text = read_text_with_encoding(file_path)
    except Exception as e:
        return False, f'read error: {e}'
    first100 = ' '.join(text.strip().split())[:100]
    conn = get_db()
    conn.execute(
        'REPLACE INTO novels (filename, path, first100, added_at) VALUES (?,?,?,?)',
        (file_path.name, str(file_path.resolve()), first100, datetime.datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()
    return True, None

 
def read_text_with_encoding(file_path: Path) -> str:
    """
    尝试自动检测文件编码并返回文本。优先尝试 utf-8，失败后尝试使用 chardet 检测编码。
    若 chardet 不可用或检测失败，则回退到 utf-8 with errors='ignore'.
    """
    # 优先尝试 utf-8
    try:
        return file_path.read_text(encoding='gbk')
    except Exception:
        raw = file_path.read_bytes()
       
        import chardet
       
        info = chardet.detect(raw)
        enc = info.get('encoding') or 'gbk'
        try:
            return raw.decode(enc, errors='ignore')
        except Exception:
            return raw.decode('utf-8', errors='ignore')


def auto_split_into_chapters(text: str, chunk_size: int = 10000):
    """
    当无法识别章节标题时，按近似长度或段落边界把全文拆分为若干虚拟章节。
    返回 [{'title':..., 'start':..., 'end':...}, ...]
    """
    chapters = []
    n = len(text)
    if n == 0:
        return [{'title': '空内容', 'start': 0, 'end': 0}]
    pos = 0
    idx = 0
    while pos < n:
        end = min(pos + chunk_size, n)
        seg = text[pos:end]
        # 尽量在段落边界断开（双换行），否则在单换行处断开
        split_at = seg.rfind('\n\n')
        if split_at == -1:
            split_at = seg.rfind('\n')
        if split_at <= 0:
            split_at = len(seg)
        chapter_end = pos + split_at
        # 防止无限循环
        if chapter_end <= pos:
            chapter_end = end
        idx += 1
        title = f'第{idx}节'
        chapters.append({'title': title, 'start': pos, 'end': chapter_end})
        pos = chapter_end
    return chapters


def extract_chapters(text: str):
    """
    尝试识别章节标题，返回 [{'title':..., 'start':..., 'end':...}, ...]
    支持中文“第...章”格式及英文 Chapter N 格式；若未识别到则返回全文一章。
    """
    patterns = [r'(^\s*第[^\n]{1,30}章[^\n]*)', r'(^\s*Chapter\s+\d+[^\n]*)']
    matches = []
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE | re.MULTILINE):
            matches.append((m.start(1), m.group(1).strip()))

    # 去重并按位置排序
    matches = sorted({(pos, title) for pos, title in matches}, key=lambda x: x[0])
    chapters = []
    if not matches:
        # 无法识别到章节标题，使用自动拆分为虚拟章节
        return auto_split_into_chapters(text)

    for i, (start, title) in enumerate(matches):
        end = matches[i+1][0] if i+1 < len(matches) else len(text)
        chapters.append({'title': title, 'start': start, 'end': end})
    return chapters

_initialized = False

@app.before_request
def before_first_request():
    global _initialized
    if not _initialized:
        # 执行你的初始化逻辑
        print("执行一次性初始化...")
        init_db()
        # 例如：init_db(), load_config() 等
        _initialized = True
 
    


@app.route('/')
def home():
    # 列出数据库中已索引的小说
    conn = get_db()
    cur = conn.execute('SELECT id, filename, first100, added_at FROM novels ORDER BY added_at DESC')
    novels = cur.fetchall()
    conn.close()
    return render_template('index.html', novels=novels)


@app.route('/index', methods=['POST'])
def index_route():
    # index a single file, a directory, or index all .txt in NOVELS_DIR when empty
    filename = request.form.get('filename', '').strip()
    if filename:
        candidate = Path(filename)
        # treat relative paths as relative to NOVELS_DIR
        if not candidate.is_absolute():
            candidate = NOVELS_DIR / candidate

        # if user provided a directory, index all .txt files under it recursively
        if candidate.exists() and candidate.is_dir():
            count = 0
            for p in candidate.rglob('*.txt'):
                ok, _ = index_file(p)
                if ok:
                    count += 1
            flash(f'已索引目录 {candidate} 下 {count} 个文件（.txt）', 'success')
            return redirect(url_for('home'))

        # otherwise try to index single file (absolute or relative-to-novels)
        ok, err = index_file(candidate)
        if not ok:
            flash(f'索引失败: {err}', 'danger')
        else:
            flash(f'已索引: {candidate}', 'success')
        return redirect(url_for('home'))

    # when no filename provided, index all txt files in NOVELS_DIR
    count = 0
    for p in NOVELS_DIR.rglob('*.txt'):
        ok, _ = index_file(p)
        if ok:
            count += 1
    flash(f'已索引 {count} 个文件（.txt） 从 novels/ 目录', 'success')
    return redirect(url_for('home'))


@app.route('/search')
def search():
    q_filename = request.args.get('q_filename', '').strip()
    q_text = request.args.get('q_text', '').strip()
    sql = 'SELECT id, filename, first100, added_at FROM novels'
    clauses = []
    params = []
    if q_filename:
        clauses.append('filename LIKE ?')
        params.append(f'%{q_filename}%')
    if q_text:
        clauses.append('first100 LIKE ?')
        params.append(f'%{q_text}%')
    if clauses:
        sql += ' WHERE ' + ' AND '.join(clauses)
    sql += ' ORDER BY added_at DESC LIMIT 200'
    conn = get_db()
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return render_template('search.html', results=rows, q_filename=q_filename, q_text=q_text)


@app.route('/reader/<int:novel_id>')
def reader(novel_id):
    # 支持查询参数: chapter (索引), page (从1开始)
    chap_idx = request.args.get('chapter', None)
    try:
        chap_idx = int(chap_idx) if chap_idx is not None else None
    except ValueError:
        chap_idx = None
    page = request.args.get('page', 1)
    try:
        page = int(page)
        if page < 1:
            page = 1
    except ValueError:
        page = 1

    conn = get_db()
    cur = conn.execute('SELECT * FROM novels WHERE id = ?', (novel_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        abort(404)
    path = Path(row['path'])
    if not path.exists():
        content = ''
        chapters = [{'title': '文件不存在', 'start': 0, 'end': 0}]
    else:
        try:
            content = read_text_with_encoding(path)
        except Exception as e:
            content = f'读取文件失败: {e}'
        chapters = extract_chapters(content)

    # 选择章节内容
    if chap_idx is None or chap_idx < 0 or chap_idx >= len(chapters):
        chap_idx = 0

    chap = chapters[chap_idx]
    chapter_text = content[chap['start']:chap['end']] if chap['end'] > chap['start'] else ''

    # 分页：按字符数分页
    PAGE_SIZE = 3000
    total_pages = max(1, math.ceil(len(chapter_text) / PAGE_SIZE))
    if page > total_pages:
        page = total_pages
    start_pos = (page - 1) * PAGE_SIZE
    end_pos = start_pos + PAGE_SIZE
    page_text = chapter_text[start_pos:end_pos]

    return render_template('reader.html', title=row['filename'], content=page_text,
                           chapters=chapters, current_chapter=chap_idx,
                           page=page, total_pages=total_pages, novel_id=novel_id)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
