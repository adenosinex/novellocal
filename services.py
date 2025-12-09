from pathlib import Path
import utils

# 小说列表

def list_novels():
    conn = utils.get_db()
    cur = conn.execute('SELECT id, filename, first100, added_at FROM novels ORDER BY added_at DESC')
    novels = cur.fetchall()
    conn.close()
    return novels

# 索引文件或目录

def index_path(path_str):
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = utils.NOVELS_DIR / candidate
    if candidate.exists() and candidate.is_dir():
        count = 0
        for p in candidate.rglob('*.txt'):
            ok, _ = utils.index_file(p)
            if ok:
                count += 1
        return True, f'已索引目录 {candidate} 下 {count} 个文件（.txt）'
    ok, err = utils.index_file(candidate)
    if ok:
        return True, f'已索引: {candidate}'
    else:
        return False, f'索引失败: {err}'

# 搜索小说

def search_novels(q_filename, q_text):
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
    return rows

# 获取小说分页内容

def get_novel_page(novel_id, chapter_idx, page_num, page_size=3000):
    conn = utils.get_db()
    cur = conn.execute('SELECT * FROM novels WHERE id = ?', (novel_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None, None, None, None, None, None
    path = Path(row['path'])
    if not path.exists():
        content = ''
        chapters = [{'title': '文件不存在', 'start': 0, 'end': 0}]
    else:
        content, mtime = utils.memdb_get(str(path.resolve()))
        if content is None:
            try:
                content = utils.read_text_with_encoding(path)
            except Exception as e:
                content = f'读取文件失败: {e}'
            try:
                utils.memdb_set(str(path.resolve()), content, path.stat().st_mtime)
            except Exception:
                pass
        chapters = utils.extract_chapters(content)
    if chapter_idx is None or chapter_idx < 0 or chapter_idx >= len(chapters):
        chapter_idx = 0
    chap = chapters[chapter_idx]
    chapter_text = content[chap['start']:chap['end']] if chap['end'] > chap['start'] else ''
    total_pages = max(1, (len(chapter_text) + page_size - 1) // page_size)
    if page_num > total_pages:
        page_num = total_pages
    if page_num < 1:
        page_num = 1
    start_pos = (page_num - 1) * page_size
    end_pos = start_pos + page_size
    page_text = chapter_text[start_pos:end_pos]
    return row['filename'], page_text, chapters, chapter_idx, page_num, total_pages
