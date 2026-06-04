FROM python:3.11-slim

# 작업 디렉터리
WORKDIR /app

# 의존성 먼저 설치 (캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY . .

# 로그 디렉터리
RUN mkdir -p logs

# 포트
EXPOSE 10000

# gunicorn 실행 (worker 2개, timeout 120초)
CMD ["gunicorn", "app:app", \
     "--workers", "2", \
     "--timeout", "120", \
     "--bind", "0.0.0.0:10000", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
