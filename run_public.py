import os
import socket
from pyngrok import ngrok

from app import app


def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Google Public DNS를 향한 dummy 연결으로 로컬 IP 계산
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    auth_token = os.environ.get('NGROK_AUTHTOKEN') or os.environ.get('NGROK_AUTH_TOKEN')
    if auth_token:
        ngrok.set_auth_token(auth_token)

    print("[PUBLIC RUN] ngrok 터널을 열고 있습니다...")
    tunnel = ngrok.connect(port, "http")
    public_url = tunnel.public_url
    print("[PUBLIC RUN] 공개 URL:", public_url)
    print("[PUBLIC RUN] 로컬 네트워크 URL:", f"http://{get_local_ip()}:{port}")
    print("[PUBLIC RUN] 앱을 종료하려면 Ctrl+C를 누르세요.")

    try:
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
    finally:
        print("[PUBLIC RUN] ngrok 터널 종료 중...")
        ngrok.disconnect(public_url)
        ngrok.kill()
