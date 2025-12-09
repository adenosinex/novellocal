from flask import Flask
import utils
from views import bp

app = Flask(__name__)
app.secret_key = 'change-me-in-prod'

_initialized = False


@app.before_request
def _init_once():
    global _initialized
    if not _initialized:
        utils.init_db()
        try:
            utils.init_mem_db()
        except Exception:
            pass
        _initialized = True


# 注册蓝图
app.register_blueprint(bp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9000, debug=True)
