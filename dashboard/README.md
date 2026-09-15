# 제조 공정 품질 불량 예측 대시보드

`plan.md`와 `scenario.md`를 기준으로 만든 로컬 통합 MVP입니다. 확정 모델 `final_rf_part_balanced.pkl`(v1.1.0)로 CN7·RG3 공정 데이터를 추론하고, React 화면에서 실시간 재생부터 검사 결과 기록까지 시연할 수 있습니다.

## 구현된 흐름

- 원본 unlabeled 데이터에서 추출한 150건을 생산 순서대로 재생
- 모델 지원 제품 145건(CN7LH·CN7RH·RG3LH·RG3RH 균형 구성)과 지원 외 제품 5건 포함
- CN7·RG3 접두어와 학습된 Part 범주를 별도로 검증
- 26개 학습 피처를 동일한 순서로 구성해 실제 모델 `predict_proba` 실행
- 기록 오류 보정(`app/corrections.py`)과 센서 결측 판정을 예측 전에 수행
- Threshold 이상 제품을 검사 대기열에 등록
- `S06 · 550TON-도시바`, `S14 · 650톤-우진2호기` 호기별 현황 및 전체 화면 필터
- 반복 재생과 무관하게 누적되는 예측 이벤트 추이 및 60건 단위 과거 구간 탐색
- 검사 시작 → 실제 결과·점검 항목·조치 저장 → TP/FP/FN/TN 분류
- Threshold 변경 사유와 변경 전후 값 기록
- 모델 파이프라인, 지원 제품, 검사 물량별 Threshold 성능표 제공
- PC·태블릿·모바일 반응형 화면

## 폴더 구조

```text
dashboard/
├── frontend/                 # React + Vite 대시보드
├── backend/
│   ├── app/                  # FastAPI, 모델 입력 계약, SQLite 저장소
│   ├── data/                 # 시연 CSV, 실행 시 생성되는 로컬 DB
│   ├── models/               # 사용 모델, 피처 목록, 모델 메타데이터
│   ├── scripts/              # 시연 데이터 재생성 도구
│   └── tests/                # API 통합 테스트
├── supabase/migrations/      # 운영 전환용 스키마/RLS 초안
├── plan.md
└── scenario.md
```

## 실행

프로젝트에서 사용하던 `kmu_project` Conda 환경을 기준으로 합니다.

### 1. FastAPI

```powershell
cd dashboard\backend
C:\Users\subin\miniconda3\envs\kmu_project\python.exe -m pip install -r requirements.txt
C:\Users\subin\miniconda3\envs\kmu_project\python.exe -m uvicorn app.main:app --reload --port 8000
```

API 문서는 `http://127.0.0.1:8000/docs`에서 확인할 수 있습니다.

### 2. React/Vite

새 PowerShell 창에서 실행합니다.

```powershell
cd dashboard\frontend
npm install
npm run dev
```

대시보드는 `http://127.0.0.1:5173`에서 열립니다.

## 검증

```powershell
cd dashboard\backend
C:\Users\subin\miniconda3\envs\kmu_project\python.exe -m pytest -q

cd ..\frontend
npm run build
```

## 현재 구현 경계

- 로그인 사용자 전환은 Supabase 연결 전 발표용 로컬 어댑터입니다. 화면 우측 상단에서 작업자·관리자·분석 담당자를 바꿀 수 있습니다.
- 실행 이력은 `backend/data/dashboard_data.db`에 저장됩니다. 운영 전환 시 `supabase/migrations/001_quality_dashboard.sql`을 적용하고 저장소 어댑터를 교체합니다.
- Threshold별 성능표는 `05_Operating_Point.ipynb`의 5-fold × 3반복 교차검증 결과입니다(검사 물량별 Recall@k · Lift). 같은 기간 교차검증 기준이므로, 생산일 단위로 분할하면 성능이 크게 낮아집니다(`ANALYSIS_RESULTS.md` 11절).
- 기본 Threshold는 **0.163**(검사 물량 10%, 불량 검출률 79%)이고 허용 범위는 0.079 ~ 0.639입니다. 운영 기준을 바꿀 때는 `backend/app/settings.py`와 `backend/models/model_info.json`을 함께 갱신합니다.
- 시연 데이터는 센서 결측이 0%인 2020-10-18 ~ 10-22 구간에서 만들었습니다(`backend/scripts/prepare_demo_data.py`).
- 배포는 포함하지 않았습니다. Python 모델 서버가 필요한 로컬 통합 MVP이며, 프론트와 FastAPI의 배포 대상을 정한 뒤 진행합니다.

## 시연 데이터 다시 만들기

원본 `data/unlabeled_data.csv`가 변경됐을 때만 실행합니다.

```powershell
C:\Users\subin\miniconda3\envs\kmu_project\python.exe dashboard\backend\scripts\prepare_demo_data.py
```
