# TRIAGE-1 배포 가이드

## 1. Heroku 배포 (가장 간단함)

```bash
# Heroku CLI 설치
# https://devcenter.heroku.com/articles/heroku-cli

# 로그인
heroku login

# 새 앱 생성
heroku create triage-1

# 환경변수 설정
heroku config:set NEMC_API_KEY=your_actual_key

# 배포
git push heroku master

# 로그 확인
heroku logs --tail
```

**배포 후**: `https://triage-1.herokuapp.com`

---

## 2. AWS Elastic Beanstalk 배포

```bash
# AWS CLI 설치 후
eb init -p python-3.11 triage-1

# 환경변수 설정
eb setenv NEMC_API_KEY=your_actual_key

# 배포
eb create triage-1-env
eb deploy
```

---

## 3. Google Cloud Platform (GCP) 배포

```bash
# Cloud Run으로 배포
gcloud run deploy triage-1 \
  --source . \
  --platform managed \
  --region us-central1 \
  --set-env-vars NEMC_API_KEY=your_actual_key
```

---

## 4. Docker 컨테이너 배포

### Dockerfile 생성 (프로젝트 루트)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--timeout", "120", "app:app"]
```

### 로컬 테스트
```bash
docker build -t triage-1 .
docker run -e NEMC_API_KEY=your_key -p 5000:5000 triage-1
```

---

## 5. 임시 공개 접근 (ngrok - 테스트용)

```bash
# 1. ngrok 설치
pip install pyngrok

# 2. Flask 앱 실행
python app.py

# 3. 다른 터미널에서 ngrok 실행
ngrok http 5000

# 4. 공개 URL 받기
# https://xxxx-xxxx-xxxx.ngrok.io
```

**주의**: ngrok 무료 계정은 8시간 후 만료, 재시작 시 URL 변경

---

## 환경변수 설정

모든 배포 방법에서 다음을 설정:

```
NEMC_API_KEY=your_actual_key_from_nemc
```

---

## 모니터링

### Heroku
```bash
heroku logs --tail  # 실시간 로그
heroku ps          # 프로세스 상태
```

### AWS
```bash
eb status          # 환경 상태
eb logs            # 로그 조회
```

---

## 문제 해결

### 502 Bad Gateway
- 앱이 5000 포트에서 실행 중인지 확인
- `gunicorn` 프로세스 재시작

### API 키 오류
- 환경변수 설정 확인
- API 키 유효성 확인

### 느린 응답
- NEMC API 호출 제한 확인
- 데이터 캐싱 개선
