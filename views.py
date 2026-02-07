from flask import send_file, Response
import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
import services
import os
import utils
from pathlib import Path

bp = Blueprint('main', __name__)
import re
import urllib.parse
from flask import Response

def text_attachment_response(full_text: str, title: str):
    # 清理标题（防止极端情况）
    clean_title = re.sub(r'[/\\:*?"<>|\r\n\t]', '_', title)[:150]
    if not clean_title.strip(' _'):
        clean_title = "novel"

    # ASCII fallback
    ascii_name = re.sub(r'[^a-zA-Z0-9_.\-]', '_', clean_title).strip('_') or "document"
    ascii_filename = f"{ascii_name}_full.txt"

    # UTF-8 version for modern browsers
    utf8_filename = f"{clean_title}_full.txt"
    encoded = urllib.parse.quote(utf8_filename, safe='')

    disposition = f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded}'

    return Response(
        full_text,
        mimetype='text/plain; charset=utf-8',
        headers={'Content-Disposition': disposition}
    )
# 全文下载路由
@bp.route('/download_full/<int:novel_id>')
def download_full(novel_id):
    title, page_text, chapters, current_chapter, page, total_pages, node = services.get_novel_page(novel_id, None, None, user='default')
    if title is None or not chapters:
        abort(404)
    # 获取全文内容
    from utils import read_chapter_text
    full_text = ''
    for idx, chap in enumerate(chapters):
        full_text += chap['title'] + '\n'
        if idx == 0:
            full_text += (page_text or '') + '\n'
        else:
            full_text += read_chapter_text(novel_id, chap['start'], chap['end']) + '\n'
    # 文件名安全处理
    return text_attachment_response(full_text, title)










@bp.route('/download/<int:novel_id>/<int:chapter_idx>')
def download_chapter(novel_id, chapter_idx):
    import re
    title, page_text, chapters, current_chapter, page, total_pages, node = services.get_novel_page(novel_id, chapter_idx, None, user='default')
    if title is None or not chapters or chapter_idx >= len(chapters):
        abort(404)
    # 只保留英文、数字、下划线
    safe_title = re.sub(r'[^a-zA-Z0-9_]', '_', title)
    filename = f"{safe_title}_chapter_{chapter_idx+1}.txt"
    return Response(page_text, mimetype='text/plain; charset=utf-8', headers={
        'Content-Disposition': f'attachment; filename={filename}'
    })



@bp.route('/')
def home():
    page = request.args.get('page', 1, type=int)
    page_size = 20
    novels, total = services.list_novels(page=page, page_size=page_size, with_total=True)
    # 尝试读取书源定义 JSON 文件并传入模板供前端编辑
    frontend_json = '[]'
    try:
        json_path = os.path.join(os.path.dirname(__file__), 'ss_顶点 me.json')
        with open(json_path, 'r', encoding='utf-8') as f:
            frontend_json = f.read()
    except Exception:
        # 保持默认空数组字符串
        pass
    return render_template('index.html', novels=novels, total=total, page=page, page_size=page_size, frontend_json=frontend_json)

@bp.route('/mark/<int:novel_id>', methods=['POST'])
def mark_novel(novel_id):
    score = request.form.get('score', '').strip()
    tag = request.form.get('tag', '').strip()
    if not score.isdigit() or not (1 <= int(score) <= 5):
        score=3
        # flash('请选择1-5分', 'danger')
        # return redirect(url_for('main.reader', novel_id=novel_id, chapter=0))
    ok = services.mark_novel('default', novel_id, int(score), tag)
    if ok:
        flash('评分成功', 'success')
    else:
        flash('评分失败', 'danger')
    return redirect(url_for('main.reader', novel_id=novel_id, chapter=0))

@bp.route('/index', methods=['POST'])
def index_route():
    filename = request.form.get('filename', '').strip()
    if filename:
        ok, msg = services.index_path(filename)
        flash(msg, 'success' if ok else 'danger')
        return redirect(url_for('main.home'))
    ok, msg = services.index_path('')
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('main.home'))


@bp.route('/search')
def search():
    q = request.args.get('q', '').strip()
    mode = request.args.get('mode', 'all')
    # 默认全部搜索
    if mode == 'filename':
        rows = services.search_novels(q, '')
    elif mode == 'text':
        rows = services.search_novels('', q)
    else:
        rows = services.search_novels(q, q)

    # 为每个搜索结果计算字数（字符数），使用内存缓存以减少磁盘I/O
    results = []
    for row in rows:
        d = dict(row)
        # prefer stored chars and size from DB, fallback to reading file
        try:
            if d.get('chars') is None:
                p = Path(d.get('path') or '')
                if p.exists():
                    content = utils.read_text_with_encoding(p)
                    d['chars'] = len(content)
                    try:
                        utils.memdb_set(str(p.resolve()), content, p.stat().st_mtime)
                    except Exception:
                        pass
                else:
                    d['chars'] = 0
        except Exception:
            d['chars'] = d.get('chars') or 0
        try:
            if d.get('size') is None:
                p = Path(d.get('path') or '')
                d['size'] = p.stat().st_size if p.exists() else 0
        except Exception:
            d['size'] = d.get('size') or 0
        results.append(d)

    return render_template('search.html', results=results, q=q, mode=mode)


@bp.route('/reader/<int:novel_id>')
def reader(novel_id):
    chap_idx = request.args.get('chapter', None)
    xqy = request.args.get('xqy', None)
    try:
        chap_idx = int(chap_idx) if chap_idx is not None else None
    except ValueError:
        chap_idx = None
    if chap_idx:
        chap_idx-=1
    page = None
    title, page_text, chapters, current_chapter, page, total_pages, node = services.get_novel_page(novel_id, chap_idx, page, user='default')
    page_text=page_text.replace('\n','<br/>')
    if title is None:
        abort(404)
    history_tip = None
    if node and (chap_idx is None or page is None):
        history_tip = f"已为你跳转到上次阅读位置：第{node['chapter_idx']+1}章，第{node['page_num']}页"
    mark = services.get_novel_mark('default', novel_id) if current_chapter == 0 else None
    tags = services.get_all_tags() if current_chapter == 0 else []
    return render_template('reader.html', title=title, content=page_text,
                           chapters=chapters, current_chapter=current_chapter,
                           page=page, total_pages=total_pages, novel_id=novel_id,
                           history_tip=history_tip, mark=mark, tags=tags)
