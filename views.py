from flask import render_template, request, redirect, url_for, flash, abort
from pathlib import Path
from app import app
import utils


@app.route('/')
def home():
    conn = utils.get_db()
    cur = conn.execute('SELECT id, filename, first100, added_at FROM novels ORDER BY added_at DESC')
    novels = cur.fetchall()
    conn.close()
    return render_template('index.html', novels=novels)


@app.route('/index', methods=['POST'])
def index_route():
    filename = request.form.get('filename', '').strip()
    if filename:
        candidate = Path(filename)
        if not candidate.is_absolute():
            candidate = utils.NOVELS_DIR / candidate

        if candidate.exists() and candidate.is_dir():
            count = 0
            for p in candidate.rglob('*.txt'):
                ok, _ = utils.index_file(p)
                if ok:
                    count += 1
            flash(f'已索引目录 {candidate} 下 {count} 个文件（.txt）', 'success')
            return redirect(url_for('home'))

        ok, err = utils.index_file(candidate)
        if not ok:
            flash(f'索引失败: {err}', 'danger')
        else:
            flash(f'已索引: {candidate}', 'success')
        return redirect(url_for('home'))

    count = 0
    for p in utils.NOVELS_DIR.rglob('*.txt'):
        ok, _ = utils.index_file(p)
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
    conn = utils.get_db()
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return render_template('search.html', results=rows, q_filename=q_filename, q_text=q_text)


@app.route('/reader/<int:novel_id>')
def reader(novel_id):
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

    conn = utils.get_db()
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
        # try memdb cache first
        content, mtime = utils.memdb_get(str(path.resolve()))
        if content is None:
            try:
                content = utils.read_text_with_encoding(path)
            except Exception as e:
                content = f'读取文件失败: {e}'
            # write into memdb
            try:
                utils.memdb_set(str(path.resolve()), content, path.stat().st_mtime)
            except Exception:
                pass
        chapters = utils.extract_chapters(content)

    if chap_idx is None or chap_idx < 0 or chap_idx >= len(chapters):
        chap_idx = 0
    chap = chapters[chap_idx]
    chapter_text = content[chap['start']:chap['end']] if chap['end'] > chap['start'] else ''
    PAGE_SIZE = 3000
    total_pages = max(1, (len(chapter_text) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > total_pages:
        page = total_pages
    start_pos = (page - 1) * PAGE_SIZE
    end_pos = start_pos + PAGE_SIZE
    page_text = chapter_text[start_pos:end_pos]
    return render_template('reader.html', title=row['filename'], content=page_text,
                           chapters=chapters, current_chapter=chap_idx,
                           page=page, total_pages=total_pages, novel_id=novel_id)
