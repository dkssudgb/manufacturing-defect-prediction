# manufacturing-defect-prediction

사출성형 공정 센서 데이터로 **검사할 제품을 골라내는** 모델. 전수 검사 대신 하루 생산량의 10%만 검사해 그날 불량의 대부분을 잡는 것이 목표다.

| 항목 | 값 |
| --- | --- |
| 데이터 | KAMP 사출성형 (CN7 · RG3, 650톤 우진2호기) |
| 분석 대상 | 5,230건, 불량 60건 (1.15%) |
| 기간 | 2020-10-16 ~ 11-06 (생산일 13일) |
| 최종 모델 | RandomForest (26개 특성, `class_weight='balanced'`) |
| 운영점 | 검사 물량 10%, Threshold 0.163 |

---

## 노트북 역할

번호 순서가 곧 분석 순서다. 각 노트북 상단에 역할·평가 프로토콜·주의를 세 줄로 적어 두었다.

### 전처리

| 노트북 | 역할 | 산출물 |
| --- | --- | --- |
| [02_EDA](02_EDA.ipynb) | 데이터 구조 파악과 **기록 오류 7건** 확인·보정. 03 이후가 쓸 전처리 데이터를 저장 | `data/labeled_modeling.csv`, `data/unlabeled_modeling.csv` |

03 이후 노트북은 원본을 다시 읽지 않고 `labeled_modeling.csv`만 불러온다. 같은 전처리를 매번 다시 쓰지 않기 위해서다.

### 1층 — 탐색과 후보 축소

무엇을 버릴지 정하는 단계다. 80/20 단일 분할로 재며, **이 층의 수치는 보고서 본문에 쓰지 않는다.**

| 노트북 | 역할 | 결론 |
| --- | --- | --- |
| [03_Baseline_Modeling](03_Baseline_Modeling.ipynb) | 기준선 확보 | 모델 후보군 확정 |
| [04_1_Imbalance_and_Feature_Experiments](04_1_Imbalance_and_Feature_Experiments.ipynb) | 불균형 처리(SMOTE 등)와 특징 실험 | `Part` 파생변수 채택, 시간축 특성 기각 |
| [04_1_1_Split_Structure](04_1_1_Split_Structure.ipynb) | 무작위 분할이 왜 낙관적인지 규명 | 구간 지문은 한 변수가 아니라 **변수 조합 전체**의 성질 |
| [04_3_PCA](04_3_PCA.ipynb) | 차원축소 검토 | 기각 (성능 붕괴) |
| [04_4_Feature_Selection](04_4_Feature_Selection.ipynb) | 특징 선택 검토 | 기각 (성능 하락) |

### 2층 — 후보 검증

| 노트북 | 역할 | 프로토콜 |
| --- | --- | --- |
| [04_2_GridSearchCV](04_2_GridSearchCV.ipynb) | 하이퍼파라미터 선택과 OOF 확인 | 학습셋 5-fold OOF |
| [04_5_AutoEncoder+GridSearch](04_5_AutoEncoder+GridSearch.ipynb) | 오토인코더 복원 오차를 특성으로 쓸지 판단 | 80/20 + GridSearch |

### 3층 — 성능 추정 (보고 수치)

보고서와 대시보드에 쓰는 수치는 모두 이 층에서 나온다.

| 노트북 | 역할 | 프로토콜 |
| --- | --- | --- |
| [04_6_AutoEncoder_CV_Validation](04_6_AutoEncoder_CV_Validation.ipynb) | **최종 성능 추정 (상한)** | 5-fold × 3반복 |
| [07_1_Episode_Detection](07_1_Episode_Detection.ipynb) | 샷 단위 지표를 **불량 에피소드** 단위로 재집계 | 저장된 OOF 확률 재사용 |
| [07_2_WalkForward_Validation](07_2_WalkForward_Validation.ipynb) | **운영 조건 성능 추정** | 시간순 순차 재학습 (walk-forward) |
| [08_Unsupervised_Defect_Scoring](08_Unsupervised_Defect_Scoring.ipynb) | 라벨 없이 검사 우선순위를 매길 수 있는지 확인 | 07_2와 동일한 walk-forward |

04_6은 **상한**이고 07_2가 **실제 운영 조건**이다. 둘 다 보고하며 하나로 다른 하나를 대체하지 않는다.

### 4층 — 운영 결정과 배포

| 노트북 | 역할 | 산출물 |
| --- | --- | --- |
| [05_Operating_Point](05_Operating_Point.ipynb) | 검사 물량 k와 Threshold 확정, 최종 모델 선택 | 운영점 표 |
| [06_Final_Model](06_Final_Model.ipynb) | 전체 5,230건으로 재학습해 배포용으로 저장 | `models/final_*` |

### 검증 (부록)

| 노트북 | 역할 |
| --- | --- |
| [09_Preprocessing_Validation](09_Preprocessing_Validation.ipynb) | 02에서 정한 기록 오류 보정이 성능에 영향을 주는지 사후 확인 |

보정 여부는 **단위와 물리 관계로 판단**한 것이지 성능으로 판단한 것이 아니다. 그래서 02에서 결정을 내리고, 측정은 모델과 프로토콜이 확정된 뒤인 여기서 한다. 이 노트북만 보정 전 값이 필요해 원본을 다시 읽는다.

### 이전 작업

현재 분석 흐름에 포함되지 않으며 기록으로 남겨 둔 노트북이다.

| 노트북 | 내용 |
| --- | --- |
| `260811_EDA_v2.ipynb` | 초기 EDA. 02_EDA로 정리됨 |
| `260813_Modeling_SMOTE.ipynb` | 초기 모델링. 03과 04_1로 분할됨 |
| [data_info](data_info.ipynb) | 원본 두 파일의 컬럼 확인 |
| `guide.ipynb` | KAMP 가이드북 「2.3 분석 체험」 재현 |
| `test.ipynb` | unlabeled `ERR_FACT_QTY` 분포 검토 |

---

## 디렉터리

```text
├── data/          원본 CSV, 전처리 데이터, 노트북별 결과 CSV (git 제외)
├── models/        학습된 모델과 스케일러 (git 제외)
├── utils/         preprocessing, model_evaluation, model_tuning, model_validation
└── dashboard/     실시간 예측 대시보드 (FastAPI + 프론트엔드 + Supabase)
```

## 실행 환경

```bash
conda activate kmu_project
jupyter lab
```

노트북은 `data/`를 작업 디렉터리로 잡고 실행한다. 번호 순서대로 실행하되, 03 이후는 02가 저장한 `labeled_modeling.csv`가 있어야 한다.
