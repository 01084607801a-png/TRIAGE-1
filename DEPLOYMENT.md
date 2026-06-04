# TRIAGE-1 배포 가이드

## 1. Render (권장 — 무료/유료)

### 빠른 배포
1. [render.com](https://render.com) 가입 → **New Web Service**
2. GitHub 저장소 연결
3. 환경 변수 설정 (대시보드 → Environment):
   ```
   NEMC_HOSPITAL_API_KEY=<발급받은 키>
   NEMC_BED_API_KEY=<발급받은 키>
   CLAUDE_API_KEY=<발급받은 키>
   SECRET_KEY=<랜덤 문자열>
   FLASK_ENV=production
   ```
4. **Deploy** 클릭

`render.yaml`이 이미 구성되어 있어 자동 감지됩니다.

> ⚠️ 무료 플랜은 비활성 15분 후 슬립 — 응급 용도라면 **Starter($7/월)** 이상 권장

---

## 2. Docker (자체 서버 / Railway / GCP Cloud Run)

```bash
# 빌드
docker build -t triage-1 .

# 실행 (환경 변수 포함)
docker run -p 10000:10000 \
  -e NEMC_HOSPITAL_API_KEY=<키> \
  -e NEMC_BED_API_KEY=<키> \
  -e CLAUDE_API_KEY=<키> \
  -e SECRET_KEY=<랜덤> \
  triage-1
```

---

## 3. 로컬 개발

```bash
# 가상환경 활성화
source .venv/Scripts/activate   # Windows
# source .venv/bin/activate     # Mac/Linux

# 패키지 설치
pip install -r requirements.txt

# .env 파일 작성 (.env.example 참고)
cp .env.example .env
# .env 열어서 API 키 입력

# 실행
python run_local.py
# → http://localhost:5000
```

---

## 4. PWA 확인

배포 후 Chrome DevTools → Lighthouse → PWA 탭에서 점수 확인.

**홈 화면 추가 (iOS)**:
Safari → 공유 버튼 → "홈 화면에 추가"

**홈 화면 추가 (Android)**:
Chrome 주소창 → 설치 아이콘 또는 배너 탭

---

## 5. API 키 발급

| 키 | 발급처 |
|----|--------|
| NEMC_HOSPITAL_API_KEY | [공공데이터포털](https://www.data.go.kr) → 국립중앙의료원_전국 응급의료기관 정보 조회 |
| NEMC_BED_API_KEY | [공공데이터포털](https://www.data.go.kr) → 의료기관 실시간 병상정보 |
| CLAUDE_API_KEY | [console.anthropic.com](https://console.anthropic.com) |

---

## 6. 헬스체크

배포 후 상태 확인:
```
GET https://<your-domain>/health
```
응답 예시:
```json
{ "status": "ok", "version": "3.4.0", "checks": { ... } }
```
