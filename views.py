
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
import services

bp = Blueprint('main', __name__)


@bp.route('/')
def home():
    novels = services.list_novels()
    return render_template('index.html', novels=novels)

@bp.route('/mark/<int:novel_id>', methods=['POST'])
def mark_novel(novel_id):
    score = request.form.get('score', '').strip()
    if not score.isdigit() or not (1 <= int(score) <= 5):
        flash('请选择1-5分', 'danger')
        return redirect(url_for('main.reader', novel_id=novel_id, chapter=0))
    ok = services.mark_novel('default', novel_id, int(score))
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
        results = services.search_novels(q, '')
    elif mode == 'text':
        results = services.search_novels('', q)
    else:
        results = services.search_novels(q, q)
    return render_template('search.html', results=results, q=q, mode=mode)


@bp.route('/reader/<int:novel_id>')
def reader(novel_id):
    chap_idx = request.args.get('chapter', None)
    try:
        chap_idx = int(chap_idx) if chap_idx is not None else None
    except ValueError:
        chap_idx = None
    page = None
    title, page_text, chapters, current_chapter, page, total_pages, node = services.get_novel_page(novel_id, chap_idx, page, user='default')
    if title is None:
        abort(404)
    history_tip = None
    if node and (chap_idx is None or page is None):
        history_tip = f"已为你跳转到上次阅读位置：第{node['chapter_idx']+1}章，第{node['page_num']}页"
    mark = services.get_novel_mark('default', novel_id) if current_chapter == 0 else None
    return render_template('reader.html', title=title, content=page_text,
                           chapters=chapters, current_chapter=current_chapter,
                           page=page, total_pages=total_pages, novel_id=novel_id,
                           history_tip=history_tip, mark=mark)
