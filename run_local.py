import os
import webbrowser
from app import app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    url = f'http://127.0.0.1:{port}'

    print('[LOCAL RUN] TRIAGE-1 로컬 서버를 시작합니다...')
    print(f'[LOCAL RUN] 브라우저에서 열려면: {url}')
    print('[LOCAL RUN] 다른 기기에서 접속하려면 로컬 네트워크 IP를 확인하세요.')

    try:
        webbrowser.open(url)
    except Exception:
        pass

    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)
