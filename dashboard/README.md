# 제조 공정 품질 불량 예측 대시보드

`plan.md`와 `scenario.md`를 기준으로 만든 로컬 통합 MVP입니다. 확정 모델 `final_rf_part_balanced.pkl`(v1.1.0)로 CN7·RG3 공정 데이터를 추론하고, React 화면에서 실시간 재생부터 검사 결과 기록까지 시연할 수 있습니다.

## 구현된 흐름

- 원본 unlabeled 데이터에서 추출한 1,000건을 생산 순서대로 재생 (1초에 1건)
- 시연은 **560건이 재생된 상태로 시작**합니다(`settings.DEMO_SEED_RECORDS`). 위험 제품이 표본에 고르지 않게 분포해(첫 위험이 164번째, 301~500번째는 0건) 빈 화면에서 시작하면 대기열이 찰 때까지 오래 걸립니다. 560건 시점에는 검사 대기 21건이 있고, 추이 차트가 그리는 최근 60건(501~560)에 threshold를 넘는 점이 7개 있어 차트도 비어 보이지 않습니다. 남은 재생은 약 7분 20초입니다.
- 모델 지원 제품 980건(CN7LH·CN7RH·RG3LH·RG3RH 각 245건 균형 구성)과 지원 외 제품 20건 포함
- CN7·RG3 접두어와 학습된 Part 범주를 별도로 검증
- 26개 학습 피처를 동일한 순서로 구성해 실제 모델 `predict_proba` 실행
- 기록 오류 보정(`app/corrections.py`)과 센서 결측 판정을 예측 전에 수행
- Threshold 이상 제품을 검사 대기열에 등록
- `S06 · 550TON-도시바`, `S14 · 650톤-우진2호기` 호기별 현황 및 전체 화면 필터
- 반복 재생과 무관하게 누적되는 예측 이벤트 추이 및 60건 단위 과거 구간 탐색
- 검사 시작 → 실제 결과·점검 항목·조치 저장 → TP/FP/FN/TN 분류
- Threshold 변경 사유와 변경 전후 값 기록
- 모델 파이프라인, 지원 제품, 검사 물량별 Threshold 성능표 제공
- 검사 결과를 학습에 반영하는 재학습 루프 — 자동(검사 5건 누적) 및 수동 실행, 모델 버전 이력, 서버 재시작 없는 모델 교체
- 재학습 주기별 성능 근거표(07_2 walk-forward) 화면 제공
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

### 재학습 루프의 경계

- 라벨은 **검사 결과에서만** 나옵니다. 시연 표본은 unlabeled 구간이라 `PassOrFail`이 없으므로, 작업자가 검사를 완료해야 그 행이 학습 데이터가 됩니다.
- DB는 화면 표시용 공정값 8개만 저장합니다. 재학습에 필요한 26개 피처는 `predictions.record_id`를 `realtime_sample.csv`의 `_id`와 조인해 복원합니다. **실운영에서는 예측 시점에 26개 피처를 그대로 저장하도록 바꿔야 합니다.**
- 기준 학습 데이터 `data/labeled_modeling.csv`(5,230건 / 불량 60건)는 재학습이 덮어쓰지 않습니다. 검사로 확보한 라벨은 `backend/data/retrain_labels.csv`에 누적되고 학습 시점에 합쳐집니다.
- 시연 한 바퀴에서 얻을 수 있는 라벨은 최대 97건(위험 판정 건수)입니다. 기존 5,230건에 더해도 **성능이 좋아지지는 않습니다.** 이 화면은 재학습 파이프라인이 도는 것을 보이기 위한 것이고, 재학습의 효과는 07_2에서 별도로 측정한 주기별 성능표로 제시합니다.
- 재학습 모델에는 교차검증을 다시 수행하지 않았습니다. 화면의 AP와 Threshold 성능표는 초기 모델 v1.1.0 기준이며, 재학습 모델일 때 `validation_stale` 플래그로 표시합니다. **모델을 바꾸면 Threshold와 검증 성능표도 다시 확정해야 합니다.**
- `/demo/reset`은 재학습 산출물(`retrain_labels.csv`, `models/retrained/`)을 지우고 v1.1.0으로 되돌립니다.

## 시연 데이터 다시 만들기

원본 `data/unlabeled_data.csv`가 변경됐을 때만 실행합니다.

표본을 다시 만들면 **FastAPI를 재시작해야 합니다.** `app/demo_data.py`가 `@lru_cache`로 CSV를 한 번만 읽습니다.

```powershell
C:\Users\subin\miniconda3\envs\kmu_project\python.exe dashboard\backend\scripts\prepare_demo_data.py
```

## 재학습 주기 근거표 다시 만들기

`07_2_WalkForward_Validation.ipynb`를 다시 실행했을 때만 필요합니다.

```powershell
C:\Users\subin\miniconda3\envs\kmu_project\python.exe dashboard\backend\scripts\prepare_walkforward_reference.py
```
