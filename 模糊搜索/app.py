import os
import time
import sqlite3
import faiss
import numpy as np
import datetime
import re
from flask import Flask, render_template, request, jsonify
from sentence_transformers import SentenceTransformer

# --- 修复报错的关键设置 ---
# 禁用 PyTorch Dynamo 编译优化，解决退出时的 "dump_compile_times" 报错
os.environ["TORCH_COMPILE_DISABLE"] = "1"
os.environ["ANOMALY_DETECTION_NO_TRACEBACK"] = "1"
# 代理设置
os.environ['http_proxy'] = 'http://127.0.0.1:57713'
os.environ['https_proxy'] = 'http://127.0.0.1:57713'

# --- 配置 ---
CONFIG_LIST = [
    {
        "name": "Local_Novels",
        "key": "novels",
        "db_path": "db_novels.sqlite",
        "index_path": "index_novels.faiss"
    },
    {
        "name": "Nas_Novels",
        "key": "nas",
        "db_path": "db_nas_novels.sqlite",
        "index_path": "index_nas_novels.faiss"
    },
    {
        "name": "My_Videos",
        "key": "videos",
        "db_path": "db_videos.sqlite",
        "index_path": "index_videos.faiss"
    }
]

MODEL_NAME = "BAAI/bge-small-zh-v1.5"

class SearchService:
    def __init__(self):
        print(">>> 正在加载模型...")
        self.model = SentenceTransformer(MODEL_NAME)
        self.resources = {}
        self.load_resources()

    def load_resources(self):
        for config in CONFIG_LIST:
            key = config['key']
            res = {"config": config, "index": None, "available": False}
            if os.path.exists(config['index_path']) and os.path.exists(config['db_path']):
                try:
                    res["index"] = faiss.read_index(config['index_path'])
                    res["available"] = True
                except Exception as e:
                    print(f"资源加载失败 {key}: {e}")
            self.resources[key] = res

    def parse_video_meta(self, preview_text):
        """
        从描述文本中提取数值以便排序
        文本示例: "Size: 50.20MB, Resolution: 1920x1080, Duration: 5m30s"
        """
        meta = {
            "size_mb": 0.0,
            "resolution_pixels": 0,
            "duration_sec": 0
        }
        
        if not preview_text:
            return meta

        # 1. 提取大小 (MB)
        size_match = re.search(r'Size:\s*([\d\.]+)MB', preview_text)
        if size_match:
            meta['size_mb'] = float(size_match.group(1))

        # 2. 提取分辨率 (计算总像素)
        res_match = re.search(r'Resolution:\s*(\d+)x(\d+)', preview_text)
        if res_match:
            w, h = int(res_match.group(1)), int(res_match.group(2))
            meta['resolution_pixels'] = w * h

        # 3. 提取时长 (转为秒)
        dur_match = re.search(r'Duration:\s*(\d+)m(\d+)s', preview_text)
        if dur_match:
            mins, secs = int(dur_match.group(1)), int(dur_match.group(2))
            meta['duration_sec'] = mins * 60 + secs
            
        return meta

    def search(self, query, target_keys, min_score=0.4, sort_by='score', page=1, page_size=20):
        t_start = time.time()
        
        # 1. 获取向量
        q_vec = self.model.encode([query], normalize_embeddings=True)
        
        # 候选池：先拿出足够多的数据(例如1000条)，才能保证排序后的分页是准确的
        # 如果数据量巨大，这里的 top_k 可能需要调大，或者采用流式处理
        CANDIDATE_LIMIT = 1000 
        
        raw_candidates = []

        # 2. 遍历库 -> 向量搜索 -> 阈值过滤
        for key in target_keys:
            if key not in self.resources or not self.resources[key]['available']:
                continue
            
            res = self.resources[key]
            index = res['index']
            db_path = res['config']['db_path']

            # FAISS 搜索
            D, I = index.search(q_vec, CANDIDATE_LIMIT)
            
            valid_ids = []
            score_map = {}
            
            # 过滤：只保留分数 > min_score 的 ID
            for rank, idx in enumerate(I[0]):
                if idx != -1:
                    score = float(D[0][rank])
                    if score >= min_score:
                        valid_ids.append(int(idx))
                        score_map[int(idx)] = score
            
            if not valid_ids:
                continue

            # 查库
            with sqlite3.connect(db_path) as conn:
                placeholders = ','.join('?' * len(valid_ids))
                sql = f"SELECT id, filepath, filename, preview_content, mtime, file_type FROM documents WHERE id IN ({placeholders})"
                cursor = conn.execute(sql, valid_ids)
                
                for row in cursor:
                    doc_id, fpath, fname, preview, mtime, ftype = row
                    score = score_map.get(doc_id, 0)
                    
                    # 解析元数据 (如果是视频)
                    meta_vals = self.parse_video_meta(preview) if ftype == 'video' else {"size_mb": 0, "resolution_pixels": 0, "duration_sec": 0}

                    raw_candidates.append({
                        "id": f"{key}_{doc_id}",
                        "source": res['config']['name'],
                        "filename": fname,
                        "filepath": fpath,
                        "preview": preview,
                        "type": ftype,
                        "mtime": mtime,
                        "mtime_str": datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M'),
                        "score": score,
                        "score_percent": int(score * 100),
                        # 排序用的数值字段
                        "sort_size": meta_vals['size_mb'],
                        "sort_res": meta_vals['resolution_pixels'],
                        "sort_dur": meta_vals['duration_sec'],
                        "external_url": fpath # 暂时直接返回路径，前端处理跳转
                    })

        # 3. 排序 (Sort)
        # Python 的 sort 是稳定的 (Timsort)
        reverse = True # 默认降序
        
        if sort_by == 'score':
            raw_candidates.sort(key=lambda x: x['score'], reverse=True)
        elif sort_by == 'date_desc':
            raw_candidates.sort(key=lambda x: x['mtime'], reverse=True)
        elif sort_by == 'date_asc':
            raw_candidates.sort(key=lambda x: x['mtime'], reverse=False)
        elif sort_by == 'size':
            raw_candidates.sort(key=lambda x: x['sort_size'], reverse=True)
        elif sort_by == 'duration':
            raw_candidates.sort(key=lambda x: x['sort_dur'], reverse=True) # 长视频在前
        elif sort_by == 'resolution':
            raw_candidates.sort(key=lambda x: x['sort_res'], reverse=True) # 高清在前
        elif sort_by == 'name':
            raw_candidates.sort(key=lambda x: x['filename'], reverse=False) # A-Z

        # 4. 分页 (Slice)
        total = len(raw_candidates)
        start = (page - 1) * page_size
        end = start + page_size
        paged_results = raw_candidates[start:end]

        return {
            "results": paged_results,
            "total": total,
            "time": time.time() - t_start
        }

app = Flask(__name__)
engine = SearchService()

@app.route('/')
def index():
    return render_template('index.html', config_list=CONFIG_LIST)

@app.route('/api/search', methods=['POST'])
def api_search():
    try:
        data = request.json
        if not data or 'query' not in data:
            return jsonify({"error": "Missing query"}), 400
            
        result = engine.search(
            query=data['query'],
            target_keys=data.get('targets', []),
            min_score=float(data.get('min_score', 0.3)),
            sort_by=data.get('sort_by', 'score'),
            page=int(data.get('page', 1)),
            page_size=int(data.get('page_size', 20))
        )
        return jsonify({"status": "success", **result})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # threaded=True 支持并发请求
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)