# 변경 이력

## 2026-09-10 — 도시바(S06)를 지원 대상에서 제외

### 문제

직전 변경에서 도시바를 "미학습 설비"로 표시하고 경고만 붙였다. 그런데 경고를 붙여도 확률은 그대로 계산해서 내보냈다. 학습 데이터가 한 건도 없는 설비에 숫자를 붙여 보여주면 사용자는 그 값을 읽게 된다. 경고 문구보다 숫자가 눈에 먼저 들어온다.

도시바는 같은 품목을 18,844건 생산했지만 라벨이 붙은 5,230건은 전부 우진2호기(S14)다. 설비가 다르면 형체력(550톤 vs 650톤)도 금형 거동도 다르므로, 이 모델의 확률은 도시바에 대해 근거가 없다.

### 변경 내용

**예측 서버**

- `settings.py`에서 화면 표시용 `KNOWN_EQUIPMENT`(S06, S14)와 실제 지원 대상 `SUPPORTED_EQUIPMENT`(S14)를 분리했다. `TRAINED_EQUIPMENT`는 `SUPPORTED_EQUIPMENT`에서 파생된다.
- `/predict`는 지원 대상이 아닌 설비 코드를 받으면 모델을 태우지 않고 바로 반환한다. `supported: false`, `predictable: false`, `prediction: "모델 지원 대상 아님"`, `defect_probability: null`, 그리고 `unsupported_reason`에 이유를 담는다.
- `/equipment/summary`는 `KNOWN_EQUIPMENT`를 순회하며 `model_supported`를 코드별로 계산한다. 도시바는 목록에 남되 `model_supported: false`다.

**화면**

- 설비 탭에서 도시바는 `disabled` 상태로 그려지고 클릭이 막힌다. 라벨은 `지원 안 함`, 보조 문구는 `학습 데이터 없음`이다.
- 탭 목록은 `KNOWN_EQUIPMENT_LABELS`(S06, S14)에 있는 설비만 그린다. 시연 표본에 한 건 섞여 있는 S12는 탭을 만들지 않는다.
- `.equipment-selector button.unsupported`에 흐림 처리(opacity .5)와 `cursor: not-allowed`를 넣었다.

### 판단 근거

경고를 띄우고 예측을 내주는 방식과, 예측 자체를 막는 방식 중 후자를 골랐다. 이 대시보드는 검사 대상을 고르는 데 쓰이므로 근거 없는 확률이 목록에 섞이면 검사 물량 계산이 오염된다. 설비를 목록에서 지우지 않고 비활성으로 남긴 이유는, 도시바가 없는 게 아니라 아직 지원하지 않는 것이라는 사실을 화면이 말해줘야 하기 때문이다.

### 검증

- `pytest tests/` 17건 통과. `test_untrained_equipment_is_flagged`를 `test_untrained_equipment_is_not_supported`로 바꿔 새 동작(차단)을 확인하고, 설비 요약 테스트는 `model_supported` 기준으로 고쳤다.
- 백엔드 재시작 후 `/equipment/summary`에서 `S06.model_supported == false`, `S14.model_supported == true` 확인.
- S06 코드로 `/predict` 호출 시 `prediction: "모델 지원 대상 아님"`, `defect_probability: null` 확인.

## 2026-09-10 — 학습 설비 구분과 빈 설비 탭 안내

### 문제

도시바(S06) 탭을 고르면 추이 그래프가 비어 보였다. 원인은 두 가지다.

- 시연 구간(2020-10-18 ~ 10-22)은 우진2호기(S14) 데이터가 100%이고 도시바는 0건이다. 도시바가 학습 품명을 만든 기간은 2020-03-17 ~ 07-21이다.
- 화면에 "왜 비었는지"가 없어 오작동처럼 보였다.

더 중요한 문제도 함께 확인했다. **모델은 우진2호기 한 대의 데이터로만 학습됐다**(labeled 5,230건 전부 S14). 그런데 도시바도 같은 품목을 18,844건 생산하며, 설정에서는 두 설비를 구분 없이 "모델 지원 설비"로 표시하고 있었다. 다른 설비 데이터로 예측하면 설비 외삽이다.

### 변경 내용

**예측 서버**

- `settings.py`에 `TRAINED_EQUIPMENT = ("S14",)`를 추가했다. 학습 설비와 지원 대상 설비를 구분한다.
- `/equipment/summary` 응답에 `trained` 필드를 추가했다.
- 학습 설비가 아닌 설비의 예측에는 `input_warnings`에 경고를 붙인다. 확률 자체는 그대로 두고 신뢰도가 낮다는 사실만 알린다.

**프런트엔드**

- 설비 탭에 `학습 설비` / `미학습 설비`를 표시하고, 수신이 0건이면 `수신 없음`으로 흐리게 처리한다.
- 추이 그래프의 빈 상태 문구가 설비 맥락을 담는다. 예: "550TON-도시바에서 수신된 데이터가 없습니다. 이 설비는 모델 학습에 사용되지 않았습니다."

### 변경 파일

- `backend/app/settings.py`
- `backend/app/main.py`
- `backend/app/prediction.py`
- `backend/tests/test_api.py`
- `frontend/src/App.jsx`
- `frontend/src/components/ProbabilityChart.jsx`
- `frontend/src/styles.css`
- `change.md`

### 검증

- FastAPI 테스트: `17 passed`. 미학습 설비 경고와 `trained` 필드 테스트를 추가했다.
- 실행 확인: S14 예측에는 설비 경고가 없고, 같은 입력을 S06으로 보내면 확률은 동일(0.0212)하면서 "학습에 사용되지 않은 설비입니다(S06)" 경고가 붙는다.
- React/Vite 프로덕션 빌드: 성공

### 남은 결정

도시바 데이터를 시연에 포함할지는 결정하지 않았다. 포함하면 미학습 설비 시나리오를 보여줄 수 있지만, 해당 기간(3 ~ 7월)은 센서 결측이 많고 학습 기간과 분포가 달라 알람률이 98 ~ 100%로 나온다(`ANALYSIS_RESULTS.md` 11절).

## 2026-09-10 — 추이 그래프 점 클릭으로 제품 상세 열기

### 배경

확률 추이 그래프에서 튀는 점을 발견해도 그 제품이 무엇인지 확인할 방법이 없었다. 최근 수신 내역 표에서 같은 제품을 다시 찾아야 했다.

### 변경 내용

- 그래프의 각 점을 클릭하면 제품 상세 창이 열린다. 키보드로도 선택할 수 있고(`Tab` + `Enter`), 마우스를 올리면 제품명과 확률이 툴팁으로 보인다.
- 추이 그래프는 `prediction_events`를 쓰는데 이 행에는 공정값과 검사 상태가 없다. 상세를 열 때 최근 수신 목록에 있으면 그 행을 쓰고, 없으면 단건 조회로 원본 예측 행을 가져온다.
- 단건 조회 `GET /predictions/{record_id}`를 추가했다. 없는 ID는 404를 반환한다.
- 경로가 `/predictions`와 `/predictions/search`를 가리지 않도록 검색 라우트 뒤에 선언했다.

### 변경 파일

- `backend/app/main.py`
- `backend/app/repository.py`
- `backend/tests/test_api.py`
- `frontend/src/services/api.js`
- `frontend/src/components/ProbabilityChart.jsx`
- `frontend/src/App.jsx`
- `frontend/src/styles.css`
- `change.md`

### 검증

- FastAPI 테스트: `15 passed`. 단건 조회가 공정값을 포함하는지, 없는 ID가 404인지, 검색·목록 경로를 가리지 않는지 확인하는 테스트를 추가했다.
- 실행 확인: 이벤트 행(필드 16개)에는 `process_values`가 없고, 단건 조회에는 공정값 8개와 `predictable`이 포함된다.
- React/Vite 프로덕션 빌드: 성공

## 2026-09-09 — 예측 이력 검색 기능 추가

### 배경

데이터는 이미 SQLite `predictions` 테이블에 쌓이지만 API가 `limit`과 `equip_cd`만 노출해 특정 제품이나 기간을 찾을 방법이 없었다.

### 변경 내용

**예측 서버**

- `GET /predictions/search`를 추가했다. 파라미터는 `keyword`, `prediction_state`, `date_from`, `date_to`, `equip_cd`, `limit`, `offset`이고 `{items, total, limit, offset}`을 반환한다.
- 키워드는 `record_id`, `part_name`, `part_no`, `part`를 부분 일치로 찾는다.
- 판정 상태는 `risk`(불량 위험), `normal`(정상), `unavailable`(데이터 결측·모델 지원 대상 아님·모델 입력 범주 미지원)로 묶었다.
- 기간은 `produced_at`이 `YYYY-MM-DD HH:MM:SS` 문자열이므로 날짜 접두사 비교로 처리한다.
- 기존 `/predictions`는 실시간 피드용으로 그대로 두고 검색은 별도 엔드포인트로 분리했다. 검색은 전체 건수가 필요해 반환 형태가 다르다.
- 검색 조건 컬럼에 인덱스를 만들었다: `produced_at`, `prediction`, `part_name`, `defect_probability`.

**프런트엔드**

- 최근 수신 내역 패널 위에 검색 바를 넣었다. 키워드 입력, 판정 상태 선택, 시작일·종료일, 초기화 버튼으로 구성했다.
- 조건이 하나라도 있으면 검색 결과를, 없으면 기존 실시간 피드를 보여준다. 패널 머리에 `검색 N건 중 M건`을 표시한다.
- 입력 후 250ms 디바운스로 요청한다. 결과가 없으면 안내 문구를 띄운다.
- 사출기 호기 필터와 재생 진행에도 검색 조건이 함께 적용된다.

### 변경 파일

- `backend/app/main.py`
- `backend/app/repository.py`
- `backend/tests/test_api.py`
- `frontend/src/services/api.js`
- `frontend/src/App.jsx`
- `frontend/src/styles.css`
- `change.md`

### 검증

- FastAPI 테스트: `13 passed`. 검색 조건별 필터링과 페이지네이션(오프셋 구간이 겹치지 않는지) 테스트를 추가했다.
- 실행 확인: 전체 150건 중 불량 위험 16건, 정상 129건, 예측 불가 5건, 키워드 `CN7` 73건, 10-21 ~ 10-22 구간 56건, 조합 검색(RG3 + 불량 위험) 13건.
- React/Vite 프로덕션 빌드: 성공

### 남은 작업

전체 건수는 반환하지만 화면에는 상위 60건만 표시한다. 그 이상 과거를 보려면 `offset` 페이지네이션을 화면에 연결해야 한다. Supabase로 옮기면 `LIKE` 대신 전문 검색(`to_tsvector`)과 유사 검색(`pg_trgm`)을 쓸 수 있다.

## 2026-09-09 — 시연 재생을 표본 끝에서 정지

### 문제

시연 데이터를 한 바퀴 재생하면 처음으로 돌아가 계속 순환했다. 같은 제품이 다시 들어오면서 재생이 언제 끝났는지 알 수 없었다.

### 변경 내용

**예측 서버**

- `advance_demo`가 표본 끝을 넘지 않도록 남은 건수만 재생한다. 완료 후 요청하면 아무것도 처리하지 않는다.
- `demo_cursor`를 `(sequence + count) % len(demo)`에서 `min(sequence + count, len(demo))`로 바꿨다. 이전에는 완료 시 0으로 되돌아가 진행률을 알 수 없었다.
- `/demo/next`와 `/demo/reset` 응답에 `played`, `total`, `remaining`, `finished`를 담았다.
- 진행 상태만 조회하는 `GET /demo/progress`를 추가했다.
- 다시 보려면 `/demo/reset`으로 초기화한다.

**프런트엔드**

- `demo_cursor >= demo_total`이면 자동 재생 타이머를 멈추고 `running`을 해제한다.
- 상태 표시가 `재생 완료`로 바뀌고 `재생`·`다음` 버튼이 비활성화된다.

### 변경 파일

- `backend/app/main.py`
- `backend/tests/test_api.py`
- `frontend/src/services/api.js`
- `frontend/src/App.jsx`
- `change.md`

### 검증

- FastAPI 테스트: `14 passed`. 표본 150건을 모두 재생한 뒤 추가 요청이 아무것도 처리하지 않고 예측 건수가 표본 크기를 넘지 않는지 확인하는 테스트를 추가했다.
- 실행 확인: 초기화 후 12건 시드 → 20건씩 요청 → 마지막 회차에 18건만 처리되고 `finished: true`, 이후 요청은 0건 처리. 예측 총 150건.
- React/Vite 프로덕션 빌드: 성공

### 함께 정리한 것

- 순환 재생을 전제로 했던 `test_prediction_trend_continues_after_replay_loop_and_supports_history`를 누적·페이지네이션 테스트로 교체했다. 순환이 없어지면서 같은 제품이 다시 들어오는 경로 자체가 사라졌다.
- `client` 픽스처를 모듈 범위로 바꿨다. 테스트마다 `TestClient`를 새로 만들면 Windows에서 `OSError: [WinError 10014]`가 간헐적으로 발생했다.
- 예측 서버 포트를 8001로 바꿨다. 8000 소켓이 프로세스 종료 후에도 해제되지 않아(고아 LISTEN) 재시작이 막혔다. `frontend/.env.local`에 `VITE_API_BASE_URL=http://127.0.0.1:8001`을 두었고, 8000이 풀리면 이 파일을 지우면 된다.

## 2026-09-09 — 하루 기준 검사 건수의 근거 표기

### 문제

검증 성능표의 `하루 검사량`이 어떤 하루를 뜻하는지 화면에 없었다. 이 값은 라벨 데이터 하루 평균 생산량 402건(5,230건 / 생산일 13일)에 검사 비율을 곱한 값인데, 시연 표본은 150건이라 시연 화면 숫자와 맞지 않아 혼동을 준다.

### 변경 내용

- `model_info.json`의 `validation`에 `daily_production_records`(402), `daily_defect_expectation`(4.62), `daily_basis_note`를 추가했다.
- `threshold_metrics.json`의 각 행에 `daily_production_baseline`(402)을 넣어 값의 기준을 데이터에 남겼다.
- Threshold 카드 표기를 `검사 물량 (하루 402건 기준)`으로 바꿨다. 기준값은 `model_info.json`에서 읽는다.
- 검증 성능표 컬럼을 `예상 검사 수 (하루)`로 바꾸고, 표 아래에 하루 기준 근거와 시연 표본(150건)이 다른 기준이라는 안내를 추가했다.

### 변경 파일

- `backend/models/model_info.json`
- `backend/models/threshold_metrics.json`
- `frontend/src/App.jsx`
- `change.md`

### 검증

- `/model/info` 응답에 기준값(402건, 4.62건)과 안내 문구가 포함되는지 확인했다.
- React/Vite 프로덕션 빌드: 성공

## 2026-09-09 — 지표 이름 표기 통일

### 문제

검증 성능표에 `Precision@k`는 영문 지표명으로, Recall@k는 `불량 검출률`로 표기돼 있어 Recall@k가 빠진 것처럼 보였다.

### 변경 내용

- 지표명을 앞에 두고 한글 설명을 괄호에 넣는 형식으로 통일했다: `Recall@k (불량 검출률)`, `Precision@k (검사 적중률)`, `Lift (무작위 대비)`, `검사 물량 (하루 기준)`.
- 모니터링 화면 Threshold 카드와 변경 모달의 지표 표기도 같은 형식으로 맞췄다.

### 변경 파일

- `frontend/src/App.jsx`
- `change.md`

### 검증

- React/Vite 프로덕션 빌드: 성공

## 2026-09-09 — 최근 수신 내역 스크롤 표시

### 문제

최근 수신 내역이 12건만 표시됐다. 조회는 60건을 받아오는데 화면에서 `slice(0, 12)`로 잘라 그 이상은 볼 수 없었다.

### 변경 내용

- 표시 제한을 없애고 받아온 목록 전체(기본 60건)를 렌더한다.
- 패널이 길어지지 않도록 목록 영역에 `max-height: 430px`와 세로 스크롤을 적용했다(`.intake-scroll`).
- 스크롤 중에도 열 이름이 보이도록 표 머리행을 `position: sticky`로 고정했다.
- 패널 머리의 `최신 N건` 표기가 실제 표시 건수를 따라간다.
- `.table-scroll`은 검사 이력·Threshold 성능표와 공유하므로 건드리지 않고 전용 클래스를 추가했다.

### 변경 파일

- `frontend/src/App.jsx`
- `frontend/src/styles.css`
- `change.md`

### 검증

- React/Vite 프로덕션 빌드: 성공

## 2026-09-09 — Threshold 되돌리기 버튼 추가

### 문제

Threshold 슬라이더를 옮긴 뒤 원래 값으로 돌아갈 방법이 없었다. 적용 전 상태로 복구하려면 현재 적용값을 기억해 슬라이더를 다시 맞춰야 했다.

### 변경 내용

- Threshold 카드에 `기본값 16%로` 버튼을 추가했다. 누르면 초안 값이 모델 권장 기본값(`model_info.json`의 `default_threshold`)으로 돌아간다.
- 버튼 문구에 기본값을 함께 표시해 어디로 돌아가는지 보이게 했다. 초안이 이미 기본값이면 버튼이 비활성화된다.
- 기본값은 `model_info.json`에서 읽고, 응답을 받기 전에는 상수 `DEFAULT_THRESHOLD`(0.163)를 쓴다. 화면에 흩어져 있던 초기값도 이 상수로 모았다.
- 되돌리기와 적용 버튼을 한 줄에 배치하는 `.threshold-actions` 스타일을 추가했다.
- Threshold 변경 모달의 `취소` 버튼을 `취소하고 되돌리기`로 바꿨다. 이전에는 모달만 닫히고 슬라이더는 옮겨진 상태로 남았다.
- 허용 범위 안내 문구가 이전 값(`20~80%`)으로 남아 있어 실제 범위(`8~64%`)로 고쳤다.

### 변경 파일

- `frontend/src/App.jsx`
- `frontend/src/styles.css`
- `change.md`

### 검증

- React/Vite 프로덕션 빌드: 성공
- Vite HMR로 실행 중 화면에 반영 확인

## 2026-09-09 — 확정 모델 v1.1.0 적용과 기록 오류 보정 연결

### 배경

분석 쪽에서 최종 모델과 운영점을 확정하고 원본 데이터의 기록 오류 두 건을 찾았다(`ANALYSIS_RESULTS.md` 11절). 예측 서버는 여전히 보정 전 데이터로 학습한 SMOTE 모델을 쓰고 있어 학습과 서빙의 전처리가 어긋난 상태였다.

### 문제

- 예측 서버 모델이 `rf_part_smote_st01_gridsearch.pkl`(보정 전, 27개 특성)이었다. 확정 모델은 `final_rf_part_balanced.pkl`(v1.1.0, 26개 특성)이다.
- 기본 Threshold가 0.5, 허용 범위가 0.2 ~ 0.8이었다. 확정 운영점은 0.163(검사 물량 10%, 검출률 79%)이고 허용 범위는 0.079 ~ 0.639다.
- `Average_Screw_RPM`이 10배로 기록된 값과 평균·최대가 뒤바뀐 배압이 보정 없이 모델에 입력됐다. unlabeled 데이터는 전 구간이 잘못된 스케일이다.
- 수집 채널이 끊겨 6개 변수가 함께 0으로 들어오는 행(unlabeled의 43.1%)을 그대로 예측했다.
- 프런트엔드 사이드바에 `RF · SMOTE 0.1 / 27 features`가 하드코딩돼 있었다.

### 변경 내용

**예측 서버**

- `app/corrections.py`를 추가했다. 학습 전처리(`utils/preprocessing.py`)와 같은 규칙으로 `Average_Screw_RPM`이 100을 넘으면 10으로 나누고, 배압 쌍을 행별 최소·최대로 재구성한다. 보정 내역은 `input_warnings`로 반환한다.
- 6개 센서 변수가 함께 0인 행은 예측하지 않고 `predictable: false`, `prediction: 데이터 결측`, `missing_features`로 반환한다.
- 모델을 `final_rf_part_balanced.pkl`(v1.1.0, 26개 특성)로 교체하고 기본 Threshold 0.163, 허용 범위 0.079 ~ 0.639로 바꿨다.
- `model_info.json`을 재생성했다. 검증 성능이 홀드아웃 AP 단일값에서 5-fold × 3반복 교차검증 평균·표준편차(0.3931 ± 0.1107)로 바뀌었고 보정 규칙도 함께 담았다.
- `threshold_metrics.json`을 검사 물량 기준으로 재생성했다. 컬럼이 `precision`·`recall`·`f2`·`tp`·`fp`·`fn`에서 `inspect_ratio`·`recall_at_k`·`precision_at_k`·`lift`·`inspection_count_per_day`로 바뀌었다.
- `predictions` 테이블에 `predictable`, `missing_features`, `input_warnings` 컬럼을 추가하고 기존 DB용 마이그레이션(`_migrate`)을 넣었다.
- 사용하지 않는 옛 모델 파일 `rf_part_smote_st01_gridsearch.pkl`, `feature_columns.pkl`(27개 특성)을 삭제했다.

**시연 데이터**

- `scripts/prepare_demo_data.py`가 확정 재생 구간 2020-10-18 ~ 10-22에서만 표본을 뽑고 센서 결측 행을 제외하도록 바꿨다. 기존 표본 150건 중 66건(44%)이 결측 행이었고 재생성 후 0건이 됐다.

**프런트엔드**

- 사이드바 모델 표기를 `modelInfo`에서 읽도록 바꿨다(`RandomForestClassifier · v1.1.0 / 26 features`).
- 모델 정보 페이지의 Average Precision 참조를 `average_precision_mean ± std`로 고쳤다. 이전 키(`average_precision`)가 사라져 페이지가 렌더되지 않는 상태였다.
- 검증 성능표 컬럼을 검사 물량 기준(Threshold · 검사 물량 · 불량 검출률 · Precision@k · Lift · 하루 검사량)으로 교체했다.
- 모니터링 화면과 Threshold 변경 모달의 지표를 검출률·무작위 대비 배수·하루 검사량으로 바꿨다.
- 슬라이더 범위를 0.079 ~ 0.639(step 0.001)로, 초기 Threshold를 0.163으로 맞췄다.
- 성능 안내 문구를 "홀드아웃 불량 12건 기준 참고값"에서 "같은 기간 교차검증 기준, 새로운 기간에서는 낮아질 수 있음"으로 바꿨다.

### 변경 파일

- `backend/app/corrections.py` (신규)
- `backend/app/prediction.py`
- `backend/app/schemas.py`
- `backend/app/settings.py`
- `backend/app/repository.py`
- `backend/models/model_info.json`
- `backend/models/threshold_metrics.json`
- `backend/models/final_rf_part_balanced.pkl` (신규), `backend/models/final_feature_columns.pkl` (신규)
- `backend/scripts/prepare_demo_data.py`
- `backend/data/realtime_sample.csv`
- `backend/tests/test_api.py`
- `frontend/src/App.jsx`
- `README.md`
- `plan.md`
- `change.md`

### 검증

- FastAPI 테스트: `11 passed`. 기존 7건 중 3건은 옛 모델을 전제로 해 수정했고, 보정·결측·미지원 품명 동작 테스트 4건을 추가했다.
  - `Average_Screw_RPM=292.5`로 요청하면 보정값 `29.25`를 직접 넣은 경우와 같은 확률이 나오고 경고가 기록된다.
  - 6개 변수가 0이면 `predictable: false`, `데이터 결측`, `missing_features` 6개를 반환한다.
  - 학습 범주에 없는 품명은 기준 범주로 조용히 예측되지 않고 `모델 입력 범주 미지원`으로 처리된다.
- 시연 구간 앞 3일이 알람률 3.5 ~ 3.9%인 안정 구간이라, 재생 직후 몇 건만 보고 알람을 기대하던 테스트를 재생 진행 방식(`advance_until_alarm`)으로 바꿨다.
- React/Vite 프로덕션 빌드: 성공
- 실행 확인: `/health`에서 `model_version: v1.1.0`, `/model/info`에서 특성 26개·기본 Threshold 0.163·AP 0.3931 ± 0.1107. 시연 132건 재생 시 알람 13건, 결측 0건, 미지원 4건.

### 적용 방법

FastAPI와 Vite 개발 서버를 재시작한 뒤 브라우저를 새로고침한다. 기존 `backend/data/dashboard_data.db`는 마이그레이션으로 컬럼이 보강되지만, 옛 모델로 만든 예측이 남아 있으면 `/demo/reset`으로 초기화하는 것이 좋다.

### 주의

성능 수치는 모두 **같은 기간 교차검증 기준**이다. 생산일 단위로 분할하면 AP가 0.02 수준으로 떨어진다(`ANALYSIS_RESULTS.md` 11절). 새로운 기간에 대한 실제 성능은 운영 중 표본검사로 확인해야 한다(`plan.md` 9절).
## 2026-09-09 — 반복 재생 추이 갱신 및 과거 구간 탐색

### 문제

- 데모 데이터가 한 바퀴 재생된 뒤 같은 `_id`가 다시 들어오면 기존 예측 행만 조회되어 추이에 새 점이 추가되지 않았다.
- 프런트엔드는 최근 예측 60건을 받아도 차트에서 다시 24건만 잘라 표시하여 그 이전 추이를 확인할 수 없었다.

### 변경 내용

- 제품과 검사 이력의 기준인 `predictions.record_id` 고유성은 유지했다.
- 재생될 때마다 별도로 쌓이는 `prediction_events` 이벤트 이력을 추가했다.
- 같은 `_id`가 다시 재생되어도 검사 대기열을 중복 생성하지 않고 추이 이벤트만 새로 기록한다.
- 절대 재생 순번 `demo_sequence`와 반복 회차 `replay_cycle`을 저장하고 화면에 현재 회차를 표시한다.
- 확률 추이 차트가 고유 제품 목록 대신 누적 예측 이벤트를 사용하도록 변경했다.
- 한 화면에 60건을 표시하고 `이전 60건`·`최근` 버튼으로 과거 구간과 최신 구간을 이동할 수 있게 했다.
- 선택한 사출기 호기 필터가 추이 이벤트 조회에도 동일하게 적용된다.
- 데모 초기화 시 이벤트 이력과 재생 회차도 함께 초기화한다.

### 변경 파일

- `backend/app/repository.py`
- `backend/app/main.py`
- `backend/tests/test_api.py`
- `frontend/src/services/api.js`
- `frontend/src/components/ProbabilityChart.jsx`
- `frontend/src/App.jsx`
- `frontend/src/styles.css`
- `supabase/migrations/001_quality_dashboard.sql`
- `README.md`
- `change.md`

## 2026-09-09 — Threshold 적용 버튼 영역 이탈 수정

### 문제

Threshold 카드의 `변경 사유 입력 후 적용` 버튼이 카드 오른쪽 경계를 넘어 표시됐다.

### 원인

카드 내부 요소에 좌우 19px 외부 여백이 적용된 상태에서 버튼에 `width: 100%`가 지정돼, 버튼의 전체 너비가 좌우 여백 38px만큼 카드 내부 가용 폭을 초과했다.

### 변경 내용

- Threshold 카드의 전체 너비 버튼을 `calc(100% - 38px)`로 설정했다.
- 기존 좌우 여백을 유지하면서 버튼의 오른쪽 끝이 카드 안에 맞도록 수정했다.

### 변경 파일

- `frontend/src/styles.css`

## 2026-09-09 — 실시간 수신 중 Threshold 임시 설정값 유지

### 문제

사용자가 Threshold 슬라이더를 변경하고 적용을 확정하기 전에 새 데이터가 수신되면, 대시보드 전체 조회가 다시 실행되면서 슬라이더 값이 서버에 저장된 기존 Threshold로 초기화됐다.

### 원인

실시간 데이터 수신 후 호출되는 공통 조회 함수가 매번 `current_threshold`를 `draftThreshold`에 덮어쓰고 있었다. 서버에 적용된 값과 사용자가 편집 중인 임시 값이 하나의 상태처럼 처리된 것이 원인이었다.

### 변경 내용

- 서버에 적용된 Threshold와 사용자가 편집 중인 임시 Threshold 상태를 분리했다.
- 사용자가 슬라이더를 변경하면 `미적용 변경` 상태로 표시한다.
- 미적용 변경이 있는 동안에는 다음 상황에서도 슬라이더 값을 유지한다.
  - 새 생산 데이터 수신
  - 실시간 자동 재생
  - 다음 제품 수동 처리
  - 사출기 필터 변경
  - 검사 상태 갱신
- Threshold 적용이 성공하거나 시연 데이터를 초기화했을 때만 서버 값과 다시 동기화한다.
- 슬라이더를 현재 적용값으로 되돌리면 미적용 상태가 자동으로 해제된다.

### 변경 파일

- `frontend/src/App.jsx`
- `frontend/src/styles.css`

## 2026-09-09 — 검사 대상 부품 식별정보 강화

### 문제

검사 대기열에서 `CN7LH`, `RG3RH`와 같은 `Part` 파생 범주만 크게 표시돼 작업자가 실제로 어떤 부품을 검사해야 하는지 충분히 식별하기 어려웠다. `Part`는 모델 입력을 위한 제품군·방향 범주이며 원본 부품명이 아니다.

### 변경 내용

- 검사 대기열에서 원본 `PART_NAME`을 기본 부품명으로 표시한다.
- 원본 부품명 아래에 `Part` 범주와 `PART_NO`를 함께 표시한다.
- 제품 상세 제목을 원본 `PART_NAME`으로 변경했다.
- 제품 상세에서 모델 제품 범주, 제품번호, 원본 레코드 ID, 생산시각, 사출기 정보를 구분해 표시한다.
- 검사 결과 입력 화면에서도 원본 부품명, 모델 범주, 제품번호, 사출기, 예측 Threshold를 확인할 수 있게 했다.
- 검사 이력에 원본 부품명과 사출기 코드를 추가했다.
- 최근 수신 내역에서도 원본 부품명과 모델 범주를 함께 표시한다.

### 변경 파일

- `backend/app/repository.py`
- `frontend/src/App.jsx`
- `frontend/src/components/InspectionForm.jsx`
- `frontend/src/styles.css`

## 2026-09-09 — 생산 사출기 정보 및 호기별 필터 추가

### 판단 근거

`EQUIP_CD`와 `EQUIP_NAME`은 데이터에서 개별 생산 설비를 식별한다. 별도의 생산 라인 필드나 사출기와 라인의 대응표가 없으므로, 기존 화면의 `화성 사출 1라인` 표기는 데이터로 확인할 수 없는 정보였다.

모델 지원 제품의 원본 데이터에서는 다음 두 사출기가 확인됐다.

- `S14`: `650톤-우진2호기` — 71,180건
- `S06`: `550TON-도시바` — 18,844건

### 변경 내용

- 상단의 `화성 사출 1라인` 문구를 제거하고 현재 선택된 사출기 범위를 표시한다.
- 전체 사출기, S06, S14를 선택할 수 있는 설비 현황 영역을 추가했다.
- 각 호기의 설비 코드, 설비명, 현재 수신 수와 불량 위험 수를 표시한다.
- 호기를 선택하면 다음 항목이 모두 같은 기준으로 필터링된다.
  - 전체 수신 및 모델 예측 건수
  - 불량 위험 및 검사 업무 건수
  - 불량확률 추이
  - 검사 대기열
  - 최근 수신 내역
- `GET /equipment/summary` API를 추가했다.
- `/dashboard/summary`, `/predictions`, `/inspection-queue`에 `equip_cd` 필터를 추가했다.
- 모바일에서는 사출기 선택 카드를 가로 스크롤로 탐색할 수 있다.

### 변경 파일

- `backend/app/settings.py`
- `backend/app/repository.py`
- `backend/app/main.py`
- `backend/tests/test_api.py`
- `frontend/src/services/api.js`
- `frontend/src/App.jsx`
- `frontend/src/styles.css`
- `README.md`

### 용어 주의

현재 데이터만으로는 사출기 한 대가 하나의 생산 라인과 동일하다고 확정할 수 없다. 화면에서는 검증 가능한 용어인 `사출기`, `호기`, `설비`를 사용한다. 추후 MES 또는 설비 마스터에서 라인 코드와 호기 매핑을 받으면 라인 → 호기 계층 필터로 확장한다.

## 2026-09-09 — 시연 데이터 150건 재구성

### 목적

기존 시연 데이터에서는 지원 대상 외 제품의 비중이 너무 높아 CN7·RG3 모델 예측과 검사 업무 흐름을 확인하기 어려웠다.

### 변경 내용

- 전체 시연 데이터 수를 150건으로 구성했다.
- 모델 지원 제품은 145건으로 구성했다.
  - `CN7LH`: 37건
  - `CN7RH`: 36건
  - `RG3LH`: 36건
  - `RG3RH`: 36건
- 지원 대상 외 제품은 5건만 포함했다.
- 불량확률을 기준으로 행을 선별하지 않고 원본 데이터의 전체 시간 구간에서 균등하게 추출했다.
- 원본에 존재하는 경우 같은 생산시각의 LH·RH 제품 쌍을 제품군별로 포함하도록 했다.
- 모델 입력에 필요한 24개 수치형 공정값이 모두 존재하는 지원 제품만 시연 데이터로 사용한다.
- 선택한 실제 원본 행은 생산시간 순서로 정렬해 재생한다.

### 변경 파일

- `backend/scripts/prepare_demo_data.py`
- `backend/data/realtime_sample.csv`
- `README.md`

### 데이터 해석 주의

이 데이터는 기능 발표를 위해 지원 제품 비중을 높인 `시연용 재구성 데이터`다. 제품 비율과 예측 결과 분포를 실제 공장의 생산 비율이나 불량률로 해석하지 않는다.

## 2026-09-09 — 검사 대기열 항목이 사라지는 문제 수정

### 현상

실시간 데이터가 계속 쌓이면 아직 검사를 시작하거나 완료하지 않은 제품이 검사 대기열에서 사라지는 문제가 있었다.

### 원인

검사 대기열을 별도 데이터로 조회하지 않고 최근 예측 목록에서 다시 계산하고 있었다.

- 프론트엔드는 최근 예측 60건만 API에서 조회했다.
- 검사 대기열도 이 60건 안에서 `검사 대기`, `검사 중` 상태를 필터링해 만들었다.
- 미검사 제품이 최근 60건 밖으로 밀리면 데이터베이스에는 남아 있어도 화면에서 사라졌다.
- 화면에서도 대기열을 최대 6건으로 잘라 표시하고 있었다.

### 변경 내용

#### 백엔드

- `GET /inspection-queue` 전용 API를 추가했다.
- 최근 수신 목록의 조회 제한과 관계없이 `검사 대기`, `검사 중` 제품을 별도로 조회한다.
- 검사 중 제품을 먼저 표시하고, 같은 상태에서는 불량확률이 높은 순으로 정렬한다.
- 검사 완료 전까지 해당 제품은 활성 검사 대기열에 유지된다.

#### 프론트엔드

- 최근 예측 목록과 검사 대기열 상태를 분리했다.
- 검사 대기열은 `/inspection-queue` 응답을 사용한다.
- 기존 최대 6건 표시 제한을 제거했다.
- 전체 활성 대기열을 세로 스크롤로 확인할 수 있도록 변경했다.
- 대기열 건수는 최근 조회 결과 길이가 아니라 전체 `검사 대기 + 검사 중` 건수를 표시한다.

### 변경 파일

- `backend/app/repository.py`
- `backend/app/main.py`
- `backend/tests/test_api.py`
- `frontend/src/services/api.js`
- `frontend/src/App.jsx`
- `frontend/src/styles.css`

### 검증

- 최근 예측 목록에서 오래된 제품이 제외된 뒤에도 검사 대기열 API에는 유지되는 회귀 테스트를 추가했다.
- FastAPI 테스트: `4 passed`
- React/Vite 프로덕션 빌드: 성공

### 적용 방법

서버가 실행 중이면 FastAPI와 Vite 개발 서버를 재시작한 뒤 브라우저를 새로고침한다. `--reload`와 Vite HMR이 정상 동작 중이면 브라우저 새로고침만으로 반영될 수 있다.
