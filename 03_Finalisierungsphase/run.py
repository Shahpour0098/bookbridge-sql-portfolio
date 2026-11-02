"""Start the local application with its project-local Python dependencies."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '.runtime/python'))
from backend.app import create_app

if __name__ == '__main__':
    from waitress import serve
    app = create_app()
    print(f"BookBridge: http://127.0.0.1:{app.config['APP_PORT']}", flush=True)
    serve(app, host='127.0.0.1', port=app.config['APP_PORT'], threads=8, max_request_body_size=131072, channel_timeout=30)
