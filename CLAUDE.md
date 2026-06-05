# TRIAGE-1 — 작업 규칙 (CLAUDE.md)

## ⭐ 항상 지킬 3단계 워크플로 (모든 변경마다)
사용자의 최종 산출물은 **발표**다. 모든 코드/프로젝트 변경은 반드시 아래 3단계를 함께 수행한다:

1. **프로젝트 수정** — 코드·소프트웨어 실제 변경 + 검증(가능하면 테스트/실행 확인)
2. **쉬운 보고** — 무엇을·왜 고쳤는지 **발표 때 사용자가 직접 설명할 수 있는 수준**으로 쉽게 풀어서 보고 (전문용어는 풀이, 비유 활용)
3. **발표 슬라이드 반영** — 변경 내용을 `presentation_v2.html`(= `TRIAGE-1_최종발표.html`, `/pitch2`)에 업데이트. 반영 후 USB 사본(`TRIAGE-1_최종발표.html`)도 갱신

> 한 단계라도 빠지면 안 됨. 특히 2번(쉬운 설명)과 3번(슬라이드 반영)을 코드 수정 후 잊지 말 것.

---

## 프로젝트 핵심 정보
- **무엇**: AI 기반 외상 환자 병원 매칭 웹앱 (구급대원이 현장 입력 → 필요 병원 등급 판단 → 실시간 병원 매칭 → 추천)
- **팀**: 261417 오로라
- **AI 핵심**: Model 1(필요 등급 예측 — RandomForest 지도 + K-means 비지도 + 안전 오버라이드 + 피드백). LLM(Gemini)은 *설명 보조*일 뿐 판단 아님
- **두 모델**: Model 1(필요 등급) → Model 2(병원 매칭, 가중 점수)

## 주요 파일
- `app.py` — 서버 본체(라우트·추천·2-API 조인·Gemini)
- `templates/index.html`, `static/script.js`, `static/style.css` — 앱 화면(의료 화이트·그린·레드)
- `data_generator_v2.py`, `train_model_v2.py`, `models/tier_model.pkl` — Model 1
- `presentation_v2.html` — 발표 자료 (라우트 `/pitch2`)
- `TRIAGE-1_구성서.md` — 쉬운 설명서
- `TRIAGE-1_기술보고서.md` — 논문 근거 + 평가기준 대응

## API / 키
- **실제 사용 API 2개**: NEMC 목록(`getEgytListInfoInqire`, 등급·좌표) + NEMC 실시간 병상(`getEmrrmRltmUsefulSckbdInfoInqire`, 병상·CT/MRI) → **둘 다 `NEMC_HOSPITAL_API_KEY` 하나로** hpid 조인
- `NEMC_BED_API_KEY`는 현재 미사용(죽은 코드)
- LLM: **Gemini** (`gemini-2.5-flash-lite`, 무료). 키는 `GEMINI_API_KEY` 또는 `CLAUDE_API_KEY` 자리 둘 다 인식. 없으면 규칙 기반 폴백
- `.env`는 절대 GitHub에 올리지 않음(.gitignore)

## 배포
- GitHub `01084607801a-png/TRIAGE-1` (master) → Render 자동 배포
- 배포 시 `NEMC_HOSPITAL_API_KEY`(필수) + `GEMINI_API_KEY`(선택) 환경변수 입력
- 한 번 배포로 앱(`/`) + 발표(`/pitch2`) 둘 다 서빙

## 평가 기준 (6개) — 항상 의식
1. 문제정의·기획 2. AI 적합성 3. 데이터·처리 4. 구현 완성도 5. 성능 검증 6. 발표·확장

## 톤/원칙
- **정직 우선**: 합성데이터 한계 인정 + 피드백 설계로 보완. "가짜 정확도 자랑" 금지
- 발표 슬라이드: 문장형(~다) 최소화, 시각 요소 중심, 밝은 배경
- 근거는 수집 논문(`papers (for AI triage)` 폴더) 기반. 핵심 근거: Kang 2022(규칙 72%), 예방가능사망 30.5%, ISS(Baker), Yi 2025(전향 AI 리뷰)
