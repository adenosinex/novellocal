from flask import Flask, render_template, request, redirect, url_for, flash, abort
import sqlite3
import os
from pathlib import Path
import datetime

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
        text = file_path.read_text(encoding='utf-8', errors='ignore')
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
    return render_template('index.html')


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
    flash(f'已索引 {count} 个文件（.txt） 从 nov els/ 目录', 'success')
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
    conn = get_db()
    cur = conn.execute('SELECT * FROM novels WHERE id = ?', (novel_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        abort(404)
    path = Path(row['path'])
    if not path.exists():
        content = '文件不存在: ' + str(path)
    else:
        try:
            content = path.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            content = f'读取文件失败: {e}'
    return render_template('reader.html', title=row['filename'], content=content)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
