import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CirclePause,
  CirclePlay,
  ClipboardCheck,
  Database,
  Factory,
  Gauge,
  History,
  Info,
  Layers3,
  LogOut,
  Menu,
  Pause,
  Play,
  RefreshCcw,
  RotateCcw,
  Settings2,
  ShieldCheck,
  SkipForward,
  SlidersHorizontal,
  Sparkles,
  TrendingDown,
  UserRound,
  X,
  Search,
} from "lucide-react";
import { InspectionForm } from "./components/InspectionForm";
import { Modal } from "./components/Modal";
import { ProbabilityChart } from "./components/ProbabilityChart";
import { StatusPill } from "./components/StatusPill";
import { api } from "./services/api";

const USERS = [
  { id: "manager-01", name: "박품질", role: "품질 관리자", shortRole: "관리자" },
  { id: "worker-01", name: "김현장", role: "사출 1조 작업자", shortRole: "작업자" },
  { id: "analyst-01", name: "이분석", role: "데이터 분석 담당자", shortRole: "분석" },
];

const DEFAULT_THRESHOLD = 0.163;

// 시연은 250건이 재생된 상태로 시작하므로 남은 재생은 750건, 약 12분 30초다.
// 표본이나 시드 건수(settings.DEMO_SEED_RECORDS)를 바꾸면 이 값도 같이 본다.
const REPLAY_INTERVAL_MS = 1000;

const EMPTY_SEARCH = { keyword: "", state: "all", from: "", to: "" };

// 설비 탭에 노출할 설비. 지원하지 않아도 비활성 상태로 보여준다.
// 시연 표본에 섞여 들어온 다른 설비 코드(S12 등)는 탭으로 만들지 않는다.
const KNOWN_EQUIPMENT_LABELS = { S06: "550TON-도시바", S14: "650톤-우진2호기" };

const EMPTY_SUMMARY = {
  received: 0, supported: 0, unsupported: 0, risk: 0, normal: 0,
  waiting: 0, inspecting: 0, completed: 0, current_threshold: DEFAULT_THRESHOLD,
  demo_cursor: 0, demo_total: 0, operating: { tp: 0, fp: 0, fn: 0, tn: 0 },
};

function formatDate(value, withDate = false) {
  if (!value) return "-";
  const date = new Date(value.includes("T") ? value : value.replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    ...(withDate ? { month: "2-digit", day: "2-digit" } : {}),
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).format(date);
}

// 불량확률은 대부분 1% 미만이라 정수로 반올림하면 전부 "0%"로 뭉개진다
// (예측 600건 중 28%가 0.5% 미만). 기준선인 threshold도 0.163처럼 소수점을
// 쓰므로 같은 자릿수로 보여야 판정 결과가 화면에서 납득된다.
function percentage(value, digits = 1) {
  if (value === null || value === undefined) return "-";
  return `${(value * 100).toFixed(digits)}%`;
}

// 지표는 카드 4장 대신 한 줄짜리 바로 묶는다. 강조색은 위험 지표에만 준다.
function Metric({ icon: Icon, label, value, note, tone = "" }) {
  return (
    <article className={`metric ${tone}`}>
      <p><Icon size={14} />{label}</p>
      <strong>{value}</strong>
      <span>{note}</span>
    </article>
  );
}

function MonitoringView({
  summary, predictions, inspectionQueue, equipmentSummary, selectedEquipment, setSelectedEquipment,
  trendHistory, trendOffset, onOlderTrend, onNewerTrend,
  modelInfo, draftThreshold, onDraftThresholdChange, thresholdDirty, metric,
  running, busy, demoFinished, onToggleRun, onNext, onReset, onThresholdApply, onSelect, onSelectRecordId,
  onStartInspection, user, search, onSearchChange, onSearchReset, searchResult, searchBusy,
  queueFamily, onQueueFamilyChange,
}) {
  // 제품군은 금형 단위다. CN7과 RG3는 원본에서도 블록으로 분리돼 생산되지만
  // (CN7 6,520건 -> 금형 교체 -> RG3 7,146건), 교체 후에도 이전 제품군의
  // 미검사 건이 대기열에 남아 확률 순서로 끼어든다. 지금 기계에서 나오지도
  // 않는 제품을 찾으러 가게 되므로 검사자가 작업 중인 제품군만 볼 수 있게 한다.
  // 정렬은 확률 내림차순을 유지한다 (plan.md 7절 운영 원칙).
  const familyCounts = inspectionQueue.reduce((acc, item) => {
    const family = (item.part || "").slice(0, 3);
    if (family) acc[family] = (acc[family] || 0) + 1;
    return acc;
  }, {});
  const families = Object.keys(familyCounts).sort();
  // 고른 제품군이 대기열에서 사라지면(전부 검사 완료, 설비 필터 변경 등)
  // 그 선택을 유지하면 빈 목록에 갇힌다. 없는 제품군이면 전체로 되돌린다.
  const activeFamily = queueFamily !== "all" && !familyCounts[queueFamily] ? "all" : queueFamily;
  const queue = activeFamily === "all"
    ? inspectionQueue
    : inspectionQueue.filter((item) => (item.part || "").startsWith(activeFamily));
  const supported = predictions.filter((item) => item.supported);
  const current = predictions[0];
  const defaultThreshold = modelInfo?.default_threshold ?? DEFAULT_THRESHOLD;
  const searchActive = Boolean(search.keyword.trim() || search.state !== "all" || search.from || search.to);
  const rows = searchActive ? searchResult.items : predictions;
  const dailyBaseline = modelInfo?.validation?.daily_production_records ?? 402;
  const selectedEquipmentInfo = selectedEquipment === "all"
    ? null
    : equipmentSummary.find((item) => item.equip_cd === selectedEquipment);
  const trendStart = Math.max(1, trendHistory.total - trendOffset - trendHistory.items.length + 1);
  const trendEnd = Math.max(0, trendHistory.total - trendOffset);

  return (
    <>
      <section className="page-heading">
        <div>
          <p className="eyebrow">LIVE QUALITY CONTROL</p>
          <h1>실시간 공정 모니터링</h1>
          <p>수신 제품을 순서대로 분석하고 검사 우선순위를 관리합니다.</p>
        </div>
      </section>

      <section className="equip-switch" aria-label="사출기별 현황">
        <button type="button" className={selectedEquipment === "all" ? "active" : ""} onClick={() => setSelectedEquipment("all")}>
          <Factory size={14} />
          전체 사출기
          <span className="equip-n">{equipmentSummary.reduce((sum, item) => sum + item.received, 0).toLocaleString()}</span>
        </button>
        {equipmentSummary.filter((item) => item.equip_cd in KNOWN_EQUIPMENT_LABELS).map((equipment) => (
          <button
            type="button"
            key={equipment.equip_cd}
            className={selectedEquipment === equipment.equip_cd ? "active" : ""}
            onClick={() => equipment.model_supported && setSelectedEquipment(equipment.equip_cd)}
            disabled={!equipment.model_supported}
            title={equipment.model_supported ? undefined : "모델이 학습하지 않은 설비라 예측을 지원하지 않음"}
          >
            <span className="equip-code">{equipment.equip_cd}</span>
            {equipment.equip_name}
            {equipment.model_supported
              ? <>
                  <span className="equip-n">{equipment.received.toLocaleString()}</span>
                  {equipment.risk > 0 && <span className="equip-risk">위험 {equipment.risk}</span>}
                </>
              : <span className="equip-n">지원 안 함</span>}
          </button>
        ))}
      </section>

      <section className="replay-bar">
        <div className="replay-now">
          <div className={`pulse-ring ${running ? "active" : ""}`}><Activity size={16} /></div>
          <div>
            <span>시연 데이터 재생</span>
            <strong>{demoFinished ? "재생 완료" : running ? "실시간 수신 중" : "일시 정지"}</strong>
          </div>
        </div>
        <div className="replay-progress">
          <div className="progress-copy"><span>재생 위치 · {(summary.demo_cycle || 0) + 1}회차</span><strong>{summary.demo_cursor} / {summary.demo_total}</strong></div>
          <div className="progress-track"><span style={{ width: `${summary.demo_total ? (summary.demo_cursor / summary.demo_total) * 100 : 0}%` }} /></div>
        </div>
        <div className="replay-actions">
          <button type="button" className={`button ${running ? "danger-soft" : "primary"}`} onClick={onToggleRun} disabled={demoFinished}>
            {running ? <Pause size={17} /> : <Play size={17} />}{running ? "일시정지" : "재생"}
          </button>
          <button type="button" className="icon-button labeled" onClick={onNext} disabled={busy || demoFinished} title={demoFinished ? "표본을 모두 재생함" : "다음 제품"}><SkipForward size={18} /><span>다음</span></button>
          <button type="button" className="icon-button labeled" onClick={onReset} disabled={busy} title="초기화"><RotateCcw size={18} /><span>초기화</span></button>
        </div>
      </section>

      <section className="metric-bar">
        <Metric icon={Database} label="전체 수신" value={summary.received.toLocaleString()} note={`지원 외 ${summary.unsupported}건 포함`} />
        <Metric icon={ShieldCheck} label="모델 예측" value={summary.supported.toLocaleString()} note={`정상 ${summary.normal}건`} />
        <Metric icon={AlertTriangle} label="불량 위험" value={summary.risk.toLocaleString()} note={`현재 기준 ${percentage(summary.current_threshold)}`} tone="risk" />
        <Metric icon={ClipboardCheck} label="검사 업무" value={(summary.waiting + summary.inspecting).toLocaleString()} note={`대기 ${summary.waiting} · 진행 ${summary.inspecting}`} />
      </section>

      <section className="dashboard-grid">
        <article className="panel trend-panel">
          <header className="panel-header">
            <div><p className="eyebrow">RISK SIGNAL</p><h2>불량확률 추이</h2></div>
            <div className="trend-header-tools">
              <div className="legend"><span className="line-swatch" />불량확률 <span className="dash-swatch" />Threshold</div>
              <div className="trend-pager">
                <span>{trendHistory.total ? `${trendStart}–${trendEnd} / ${trendHistory.total}` : "0건"}</span>
                <button type="button" onClick={onOlderTrend} disabled={trendOffset + trendHistory.limit >= trendHistory.total} aria-label="이전 추이 보기"><ChevronLeft size={15} /></button>
                <button type="button" onClick={onNewerTrend} disabled={trendOffset === 0} aria-label="최근 추이 보기"><ChevronRight size={15} /></button>
              </div>
            </div>
          </header>
          <ProbabilityChart predictions={trendHistory.items} threshold={summary.current_threshold} onSelect={onSelectRecordId} emptyMessage={selectedEquipmentInfo && !selectedEquipmentInfo.received ? `${selectedEquipmentInfo.equip_name}에서 수신된 데이터 없음${selectedEquipmentInfo.trained ? "" : " · 모델 학습에 사용되지 않은 설비"}` : undefined} />
          <div className="chart-summary">
            <div><span>최근 지원 제품</span><strong>{current?.supported ? current.part : supported[0]?.part || "-"}</strong></div>
            <div><span>최근 불량확률</span><strong className={(current?.defect_probability || 0) >= summary.current_threshold ? "risk-text" : ""}>{current?.supported ? percentage(current.defect_probability) : supported[0] ? percentage(supported[0].defect_probability) : "-"}</strong></div>
            <div><span>지원 처리율</span><strong>{summary.received ? percentage(summary.supported / summary.received, 0) : "-"}</strong></div>
          </div>
        </article>

        <article className="panel threshold-panel">
          <header className="panel-header">
            <div><p className="eyebrow">DECISION STANDARD</p><h2>판정 Threshold</h2></div>
            <SlidersHorizontal size={20} />
          </header>
          <div className="threshold-value"><strong>{(draftThreshold * 100).toFixed(1)}</strong><span>%</span><small>허용 범위 8~64%</small>{thresholdDirty && <em>미적용 변경</em>}</div>
          <input
            className="threshold-slider"
            type="range" min="0.079" max="0.639" step="0.001"
            value={draftThreshold}
            onChange={(event) => onDraftThresholdChange(Number(event.target.value))}
            aria-label="불량 위험 판정 Threshold"
            style={{ "--slider-value": `${((draftThreshold - 0.079) / 0.56) * 100}%` }}
          />
          <div className="slider-labels"><span>민감 · 검사량 증가</span><span>엄격 · 미탐 주의</span></div>
          <div className="metric-pair">
            <div><span>Recall@{metric ? percentage(metric.inspect_ratio, 0) : "k"} (예상 검출률)</span><strong>{metric ? percentage(metric.recall_at_k, 1) : "-"}</strong></div>
            <div><span>검사 물량 (하루 {dailyBaseline}건 기준)</span><strong>{metric ? `${metric.inspection_count_per_day}건` : "-"}</strong></div>
          </div>
          <div className="threshold-note"><Info size={15} /><span>같은 기간 교차검증(5-fold × 3반복) 기준 예상값. 새 기간에서는 낮아질 수 있음</span></div>
          <div className="threshold-actions">
            <button
              type="button"
              className="button secondary"
              onClick={() => onDraftThresholdChange(defaultThreshold)}
              disabled={Math.abs(draftThreshold - defaultThreshold) < 0.001}
              title={`모델 권장 기본값 ${(defaultThreshold * 100).toFixed(1)}%로 되돌립니다`}
            >
              <RotateCcw size={16} /> 기본값 {(defaultThreshold * 100).toFixed(1)}%로
            </button>
            <button type="button" className="button primary" onClick={onThresholdApply} disabled={!thresholdDirty}>변경 사유 입력 후 적용</button>
          </div>
        </article>
      </section>

      <section className="panel queue-panel">
        <header className="panel-header">
          <div><p className="eyebrow">ACTION REQUIRED</p><h2>검사 대기열 <span className="count-badge">{summary.waiting + summary.inspecting}</span></h2></div>
          <span className="panel-meta">검사 중 우선 · 불량확률순</span>
        </header>
        {families.length > 1 && (
          <div className="queue-family" role="group" aria-label="제품군 범위">
            <button type="button" className={activeFamily === "all" ? "active" : ""} onClick={() => onQueueFamilyChange("all")}>
              전체 <span>{inspectionQueue.length}</span>
            </button>
            {families.map((family) => (
              <button
                type="button"
                key={family}
                className={activeFamily === family ? "active" : ""}
                onClick={() => onQueueFamilyChange(family)}
              >
                {family} <span>{familyCounts[family]}</span>
              </button>
            ))}
            <small>금형이 바뀌어도 이전 제품군의 미검사 건은 대기열에 남음</small>
          </div>
        )}
        {queue.length ? (
          <div className="queue-list">
            {queue.map((record) => (
              <button type="button" className="queue-row" key={record.record_id} onClick={() => onSelect(record)}>
                <div className="part-mark">{record.part?.slice(0, 3)}<small>{record.part?.slice(3)}</small></div>
                <div className="queue-product"><strong>{record.part_name}</strong><span>{record.part} · {record.part_no || "제품번호 없음"}</span></div>
                <div className="queue-equipment"><span>설비</span><strong>{record.equip_cd || "-"}</strong></div>
                <div className="probability-cell"><span>불량확률</span><strong>{percentage(record.defect_probability)}</strong><div><i style={{ width: percentage(record.defect_probability) }} /></div></div>
                <div className="status-cell">
                  <StatusPill prediction={record.prediction} inspectionStatus={record.inspection_status} />
                  {record.inspector && <span className="inspector">{record.inspector}</span>}
                </div>
                <span className="time-cell">{formatDate(record.produced_at)}</span>
                <ChevronRight size={18} />
              </button>
            ))}
          </div>
        ) : <div className="empty-state"><CheckCircle2 size={26} /><strong>{activeFamily === "all" ? "검사 대기 제품 없음" : `${activeFamily} 제품군에 검사 대기 없음`}</strong><span>{activeFamily === "all" ? "불량 위험 제품이 수신되면 이곳에 표시됨" : "전체를 선택하면 다른 제품군의 대기 건도 볼 수 있음"}</span></div>}
      </section>

      <section className="panel recent-panel">
        <header className="panel-header">
          <div><p className="eyebrow">RECENT INTAKE</p><h2>최근 수신 내역</h2></div>
          <span className="panel-meta">
            {searchActive
              ? `검색 ${searchResult.total}건 중 ${rows.length}건`
              : `최신 ${rows.length}건`}
          </span>
        </header>
        <div className="intake-search">
          <div className="search-field">
            <Search size={15} />
            <input
              type="search"
              value={search.keyword}
              onChange={(event) => onSearchChange({ keyword: event.target.value })}
              placeholder="제품명 · 제품 ID · 제품번호 검색"
              aria-label="예측 이력 검색"
            />
          </div>
          <select value={search.state} onChange={(event) => onSearchChange({ state: event.target.value })} aria-label="판정 상태">
            <option value="all">판정 전체</option>
            <option value="risk">불량 위험</option>
            <option value="normal">정상</option>
            <option value="unavailable">예측 불가</option>
          </select>
          <div className="search-dates">
            <input type="date" value={search.from} onChange={(event) => onSearchChange({ from: event.target.value })} aria-label="시작일" />
            <span>~</span>
            <input type="date" value={search.to} onChange={(event) => onSearchChange({ to: event.target.value })} aria-label="종료일" />
          </div>
          <button type="button" className="button secondary" onClick={onSearchReset} disabled={!searchActive}>
            <X size={15} /> 초기화
          </button>
        </div>
        <div className="table-scroll intake-scroll">
          <table>
            <thead><tr><th>수신 시각</th><th>제품</th><th>제품번호</th><th>설비</th><th>불량확률</th><th>처리 상태</th></tr></thead>
            <tbody>
              {rows.map((record) => (
                <tr key={record.record_id} onClick={() => onSelect(record)} tabIndex="0">
                  <td>{formatDate(record.produced_at, true)}</td>
                  <td><strong>{record.part_name}</strong><small className="table-sub">{record.part || "지원 외 제품"}</small></td>
                  <td>{record.part_no || "-"}</td><td>{record.equip_cd || "-"}</td>
                  <td className={record.predicted_label === 1 ? "risk-text" : ""}>{percentage(record.defect_probability)}</td>
                  <td>
                    <StatusPill prediction={record.prediction} inspectionStatus={record.inspection_status} supported={record.supported} />
                    {record.inspector && <small className="table-sub">담당 {record.inspector}</small>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {searchActive && !rows.length && !searchBusy && (
            <div className="empty-state compact"><strong>검색 결과 없음</strong><span>조건을 바꾸거나 초기화</span></div>
          )}
        </div>
      </section>
    </>
  );
}

function HistoryView({ inspections, thresholdHistory, summary }) {
  const completeCount = inspections.filter((item) => item.completed_at).length;
  const precisionDenominator = summary.operating.tp + summary.operating.fp;
  const operatingPrecision = precisionDenominator ? summary.operating.tp / precisionDenominator : null;
  return (
    <>
      <section className="page-heading"><div><p className="eyebrow">TRACEABILITY</p><h1>검사 및 변경 이력</h1><p>예측 이후의 검사 결과와 판정 기준 변경을 추적합니다.</p></div></section>
      <section className="metric-bar three">
        <Metric icon={ClipboardCheck} label="검사 완료" value={completeCount} note={`전체 검사 ${inspections.length}건`} />
        <Metric icon={CheckCircle2} label="운영 Precision" value={operatingPrecision === null ? "표본 없음" : percentage(operatingPrecision, 1)} note="검사 완료 제품 기준" />
        <Metric icon={SlidersHorizontal} label="Threshold 변경" value={thresholdHistory.length} note={`현재 ${percentage(summary.current_threshold)}`} />
      </section>
      <section className="panel">
        <header className="panel-header"><div><p className="eyebrow">INSPECTION LOG</p><h2>검사 이력</h2></div></header>
        {inspections.length ? <div className="table-scroll"><table><thead><tr><th>부품명</th><th>사출기</th><th>불량확률</th><th>검사자</th><th>상태</th><th>실제 결과</th><th>평가</th><th>완료 시각</th></tr></thead><tbody>
          {inspections.map((item) => <tr key={item.id}><td><strong>{item.part_name}</strong><small className="table-sub">{item.part} · {item.part_no}</small></td><td>{item.equip_cd || "-"}</td><td className="risk-text">{percentage(item.defect_probability)}</td><td>{item.worker_name}</td><td>{item.completed_at ? "검사 완료" : "검사 중"}</td><td>{item.actual_label || "-"}</td><td>{item.evaluation || "-"}</td><td>{formatDate(item.completed_at, true)}</td></tr>)}
        </tbody></table></div> : <div className="empty-state"><ClipboardCheck size={26} /><strong>검사 이력 없음</strong><span>검사 대기열에서 업무를 시작</span></div>}
      </section>
      <section className="panel">
        <header className="panel-header"><div><p className="eyebrow">AUDIT LOG</p><h2>Threshold 변경 이력</h2></div></header>
        {thresholdHistory.length ? <div className="history-list">{thresholdHistory.map((item) => <div key={item.id} className="history-item"><div className="history-icon"><SlidersHorizontal size={17} /></div><div><strong>{percentage(item.previous_threshold)} <ChevronRight size={14} /> {percentage(item.new_threshold)}</strong><span>{item.reason}</span></div><div><strong>{item.changed_by}</strong><span>{formatDate(item.changed_at, true)}</span></div></div>)}</div> : <div className="empty-state compact"><History size={24} /><strong>변경 이력 없음</strong></div>}
      </section>
    </>
  );
}

function ModelView({ modelInfo, walkforward }) {
  if (!modelInfo) return null;
  // 같은 숫자를 두 방식으로 잰 값을 나란히 보여준다. 이 표는 같은 기간
  // 교차검증이라 높게 나오고, 07_2는 시간순으로 재학습하며 잰 값이다.
  // 재검증하면 앞 숫자가 바뀌므로 화면에서 그때그때 꺼낸다.
  const operatingPoint = modelInfo.threshold_metrics.find(
    (row) => Math.abs(row.inspect_ratio - 0.1) < 1e-9,
  );
  const realistic = (walkforward?.rows || [])
    .filter((row) => !row.is_baseline && row.band === walkforward?.best_band)
    .sort((a, b) => b.recall_at_10 - a.recall_at_10)[0];
  return (
    <>
      <section className="page-heading"><div><p className="eyebrow">MODEL GOVERNANCE</p><h1>모델 및 검증 정보</h1><p>현재 운영 중인 모델의 입력 계약과 검사 물량별 교차검증 결과입니다.</p></div></section>
      <section className="model-hero panel">
        <div className="model-icon"><Layers3 size={28} /></div>
        <div>
          <span className="overline">ACTIVE MODEL</span>
          <h2>{modelInfo.model_type}</h2>
          <p>{modelInfo.model_version}{modelInfo.model_source ? ` · ${modelInfo.model_source}` : ""}</p>
        </div>
        <div className="model-hero-stats">
          <div><span>입력 피처</span><strong>{modelInfo.feature_count}</strong></div>
          <div><span>기본 Threshold</span><strong>{percentage(modelInfo.default_threshold)}</strong></div>
          <div>
            <span>학습 데이터</span>
            <strong>{(modelInfo.train_records ?? modelInfo.validation.records).toLocaleString()}건</strong>
            <small>불량 {modelInfo.train_defects ?? modelInfo.validation.defects}건{modelInfo.added_records ? ` · 검사 반영 +${modelInfo.added_records}` : ""}</small>
          </div>
        </div>
      </section>
      <section className="panel">
        <header className="panel-header">
          <div><p className="eyebrow">INFERENCE PATH</p><h2>추론 경로</h2></div>
          <span className="panel-meta">제품 한 건이 들어와 판정이 나오기까지</span>
        </header>
        <ol className="inference-path">
          {(modelInfo.inference_path || []).map((step, index) => (
            <li key={step.label} className={step.gate ? "gate" : step.model ? "model-step" : ""}>
              <span className="step-no">{String(index + 1).padStart(2, "0")}</span>
              <div>
                <strong>{step.label}</strong>
                <p>{step.detail}</p>
              </div>
              {step.gate && <span className="gate-chip">걸리면 예측 안 함 · {step.gate}</span>}
              {step.model && <span className="model-chip">모델 내부</span>}
            </li>
          ))}
        </ol>
      </section>

      <section className="model-grid">
        <article className="panel"><header className="panel-header"><h2>모델 구조</h2></header><div className="pipeline-list">{modelInfo.pipeline.map((item, index) => <div key={item}><span>{String(index + 1).padStart(2, '0')}</span><strong>{item}</strong>{index < modelInfo.pipeline.length - 1 && <ChevronRight size={17} />}</div>)}</div><div className="validation-warning"><Info size={17} /><span>{modelInfo.pipeline_note || "저장된 모델 파일 안의 단계"}</span></div></article>
        <article className="panel"><header className="panel-header"><h2>지원 제품</h2><span className="panel-meta">{modelInfo.supported_parts.length}종</span></header><div className="part-grid">{modelInfo.supported_parts.map((part) => (
          <div key={part}>
            <ShieldCheck size={18} />
            <strong>{modelInfo.supported_part_names?.[part] || part}</strong>
            <span>모델 범주 {part}</span>
          </div>
        ))}</div></article>
      </section>
      <section className="panel validation-panel">
        <header className="panel-header">
          <div>
            <p className="eyebrow">CROSS VALIDATION</p>
            <h2>검사 물량별 검증 성능</h2>
          </div>
          {/* 칩은 성격만 말하고, 얼마나 차이 나는지는 아래 각주가 숫자로 보여준다 */}
          <span className="warning-chip"><AlertTriangle size={14} /> 최상 조건 기준</span>
        </header>
        {modelInfo.validation_stale && (
          <div className="stale-banner">
            <AlertTriangle size={18} />
            <div>
              <strong>아래 검증 수치는 현재 운영 중인 {modelInfo.model_version}의 성능이 아님</strong>
              <span>
                초기 모델 v1.1.0을 5,230건으로 5-fold × 3반복 교차검증해 얻은 값.
                재학습 모델의 수치는 「모델 운영」 탭의 <strong>검증 실행</strong>으로 다시 측정 가능(약 8초).
                Threshold {percentage(modelInfo.default_threshold)}도 v1.1.0 기준 운영점
              </span>
            </div>
          </div>
        )}
        <p className="table-intro">
          <strong>k는 검사 물량</strong>
          <span>
            「확률이 높은 상위 k%를 검사했다면」을 가정하고 잰 값이며, Threshold는 그 k에 해당하는 확률 컷.
            운영은 반대로 Threshold를 고정하므로 하루 검사 건수는 공정 상태에 따라 달라짐
          </span>
        </p>
        <div className="table-scroll"><table><thead><tr><th>검사 물량 (k)</th><th>Threshold</th><th>Recall@k (불량 검출률)</th><th>Precision@k (검사 적중률)</th><th>Lift</th><th>예상 검사 수 (하루)</th></tr></thead><tbody>
          {modelInfo.threshold_metrics.map((row) => {
            // 운영점 0.163은 성능표의 0.1627을 반올림한 값이라 === 비교로는 절대
            // 맞지 않는다. 같은 운영점으로 볼 만한 거리인지로 판단한다.
            const isDefault = Math.abs(row.threshold - modelInfo.default_threshold) < 0.001;
            return <tr key={row.threshold} className={isDefault ? "selected-row" : ""}><td><strong>{percentage(row.inspect_ratio, 0)}</strong>{isDefault && <span className="default-tag">기본</span>}</td><td>{percentage(row.threshold)}</td><td>{percentage(row.recall_at_k, 1)}</td><td>{percentage(row.precision_at_k, 1)}</td><td>{row.lift.toFixed(1)}배</td><td>{row.inspection_count_per_day}건</td></tr>;
          })}
        </tbody></table></div>
        <div className="table-footnotes">
          <p>
            <strong>측정 조건</strong>
            <span>
              {modelInfo.validation.records.toLocaleString()}건 · 불량 {modelInfo.validation.defects}건
              {modelInfo.validation.defect_episodes ? ` (에피소드 ${modelInfo.validation.defect_episodes}개)` : ""}
              {" · "}{modelInfo.validation.method}
            </span>
          </p>
          <p>
            <strong>한계</strong>
            <span>
              {operatingPoint && realistic
                ? `같은 기간 교차검증이라 최상의 조건. 시간순으로 재학습하며 재면 검사 물량 10% 검출률이 ${percentage(operatingPoint.recall_at_k, 1)} → ${percentage(realistic.recall_at_10, 1)}로 내려감 (「모델 운영」 탭 재학습 주기별 성능)`
                : modelInfo.validation.warning}
            </span>
          </p>
          <p><strong>하루 기준</strong><span>{modelInfo.validation.daily_basis_note}</span></p>
        </div>
      </section>
    </>
  );
}

function ModelOpsView({ modelInfo, registry, status, walkforward, summary, busy, onRetrain, onValidate }) {
  if (!status) return null;
  const active = registry.find((item) => item.active) || registry[0];
  const operating = summary.operating || { tp: 0, fp: 0, fn: 0, tn: 0 };
  const evaluated = operating.tp + operating.fp + operating.fn + operating.tn;
  const autoProgress = status.auto_threshold
    ? Math.min(100, (status.pending_inspections / status.auto_threshold) * 100)
    : 0;

  return (
    <>
      <section className="page-heading">
        <div>
          <p className="eyebrow">CONTINUOUS LEARNING</p>
          <h1>모델 운영과 재학습</h1>
          <p>검사 결과를 학습에 반영하고 모델 버전을 관리합니다.</p>
        </div>
      </section>

      {status.recommended && (
        <section className="recommend-banner">
          <TrendingDown size={20} />
          <div>
            <strong>재학습 권고</strong>
            <ul>{status.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
          </div>
          <button type="button" className="button primary" onClick={onRetrain} disabled={busy}>
            <Sparkles size={16} /> 재학습 실행
          </button>
        </section>
      )}

      <section className="metric-bar">
        <Metric
          icon={Layers3}
          label="운영 중인 모델"
          value={status.active_version || "-"}
          note={active ? `${active.source} · 학습 ${active.train_records.toLocaleString()}건` : "-"}
        />
        <Metric
          icon={ClipboardCheck}
          label="반영 대기 검사"
          value={status.pending_inspections.toLocaleString()}
          note={status.pending_inspections >= status.auto_threshold
            ? "자동 기준 도달"
            : `자동 실행까지 ${status.remaining_for_auto}건`}
          tone={status.pending_inspections >= status.auto_threshold ? "risk" : ""}
        />
        <Metric
          icon={CheckCircle2}
          label="운영 Precision"
          value={status.observed_precision === null ? "표본 없음" : percentage(status.observed_precision, 1)}
          note={`검증 기준 ${percentage(status.expected_precision, 1)} · 평가 ${evaluated}건`}
        />
        <Metric
          icon={RefreshCcw}
          label="재학습 횟수"
          value={registry.filter((item) => item.source !== "초기 배포").length}
          note={status.auto_enabled ? `자동 ${status.auto_threshold}건마다` : "자동 꺼짐"}
        />
      </section>

      <section className="dashboard-grid">
        <article className="panel">
          <header className="panel-header">
            <div><p className="eyebrow">MODEL VERSIONS</p><h2>재학습 이력</h2></div>
            <span className="panel-meta">최신순</span>
          </header>
          {registry.length ? (
            <div className="table-scroll">
              <table>
                <thead><tr><th>버전</th><th>구분</th><th>학습 건수</th><th>불량</th><th>추가 라벨</th><th>검증</th><th>실행자</th><th>시각</th></tr></thead>
                <tbody>
                  {registry.map((item) => (
                    <tr key={item.id} className={item.active ? "selected-row" : ""}>
                      <td>
                        <strong>{item.version}</strong>
                        {item.active && <span className="default-tag">운영 중</span>}
                      </td>
                      <td>{item.source}{item.trigger ? ` · ${item.trigger}` : ""}</td>
                      <td>{item.train_records.toLocaleString()}</td>
                      <td>{item.train_defects}</td>
                      <td>{item.added_records ? `+${item.added_records} (불량 ${item.added_defects})` : "-"}</td>
                      <td>{item.validated ? <span className="default-tag">측정 완료</span> : "미측정"}</td>
                      <td>{item.created_by || "-"}</td>
                      <td>{formatDate(item.created_at, true)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <div className="empty-state compact"><strong>이력 없음</strong></div>}
        </article>

        <article className="panel retrain-panel">
          <header className="panel-header">
            <div><p className="eyebrow">NEXT RETRAIN</p><h2>재학습 실행</h2></div>
            <Sparkles size={18} />
          </header>
          <div className="retrain-progress">
            <div className="progress-copy">
              <span>반영 대기 검사</span>
              <strong>{status.pending_inspections} / {status.auto_threshold}</strong>
            </div>
            <div className="progress-track"><span style={{ width: `${autoProgress}%` }} /></div>
          </div>
          <p className="retrain-note">
            검사 결과가 {status.auto_threshold}건 쌓이면 자동 재학습.
            지금 실행하려면 사유를 남기고 수동 실행
          </p>
          {modelInfo?.validation_stale && (
            <div className="threshold-note">
              <Info size={15} />
              <span>
                화면의 검증 성능(AP·Threshold 성능표)은 초기 모델 v1.1.0을 교차검증한 값.
                재학습 모델에는 아직 해당 검증을 다시 수행하지 않음
              </span>
            </div>
          )}
          <button
            type="button"
            className="button primary full"
            onClick={onRetrain}
            disabled={busy || status.pending_inspections === 0}
            title={status.pending_inspections === 0 ? "반영할 검사 결과 없음" : undefined}
          >
            <Sparkles size={16} /> 사유 입력 후 재학습
          </button>
        </article>
      </section>

      <section className="panel validate-panel">
        <header className="panel-header">
          <div><p className="eyebrow">VALIDATION</p><h2>검증 재측정</h2></div>
          <span className="panel-meta">
            {modelInfo?.validated_at ? `최근 측정 ${formatDate(modelInfo.validated_at, true)}` : "이 모델은 아직 미측정"}
          </span>
        </header>
        <div className="validate-body">
          <p>
            모델 정보 탭의 AP와 검사 물량별 성능표를 현재 학습 데이터로 다시 계산.
            5-fold × 3반복 교차검증이라 <strong>약 8초</strong>가 걸리며, 재학습(0.5초)의 14배
          </p>
          <button type="button" className="button primary" onClick={onValidate} disabled={busy}>
            {busy ? "측정 중…" : "검증 실행"}
          </button>
        </div>
        <div className="table-footnotes">
          <p>
            <strong>실행 시점</strong>
            <span>
              재학습마다 자동으로 돌리지 않음. 같은 데이터로 fold 난수만 바꿔도 AP가 0.355~0.391로 흔들리는데,
              검사 {status.auto_threshold}건은 학습 데이터의 0.1%라 그 흔들림에 묻힘. 학습 데이터가 충분히 늘었을 때 실행
            </span>
          </p>
        </div>
      </section>

      <section className="panel">
        <header className="panel-header">
          <div><p className="eyebrow">WHY CADENCE MATTERS</p><h2>재학습 주기별 성능</h2></div>
          <span className="panel-meta">검사 물량 10% 기준</span>
        </header>
        {walkforward?.rows?.length ? (
          <>
            <p className="table-intro">
              <strong>사전 분석에서 미리 계산해 둔 값</strong>
              <span>
                정답이 있는 라벨 데이터로 「검사 결과를 얼마나 자주 반영하느냐」만 바꿔가며 측정한 결과이며,
                시연 중 실시간으로 재는 값이 아니라 자동 재학습 기준을 정한 근거
              </span>
            </p>
            <div className="table-scroll">
              <table>
                <thead><tr><th>재학습 주기 (생산 샷)</th><th>반영 지연</th><th>성능 구간</th><th>AP</th><th>검출률 (Recall@10%)</th><th>Lift</th><th>에피소드 감지</th></tr></thead>
                <tbody>
                  {walkforward.rows.map((row) => (
                    <tr key={row.label} className={row.band === walkforward.best_band ? "selected-row" : ""}>
                      <td>
                        <strong>{row.is_baseline ? "무작위 CV (상한)" : row.cadence}</strong>
                        {row.band === walkforward.best_band && <span className="default-tag">권장 구간</span>}
                      </td>
                      <td>{row.horizon_minutes ? `약 ${Math.round(row.horizon_minutes)}분` : "-"}</td>
                      <td>{row.band || "-"}</td>
                      <td>{row.average_precision.toFixed(4)}</td>
                      <td>{percentage(row.recall_at_10, 1)}</td>
                      <td>{row.lift_at_10.toFixed(1)}배</td>
                      <td>{row.episode_detection}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="table-footnotes">
              <p><strong>측정 방법</strong><span>{walkforward.evaluation}</span></p>
              <p><strong>읽는 법</strong><span>{walkforward.note}</span></p>
              <p>
                <strong>현재 설정</strong>
                <span>
                  검사 {status.auto_threshold}건마다 자동 재학습 = 생산 {status.auto_threshold * 10}샷마다 반영
                  (검사 물량이 생산의 10%) = 반영 지연 약 {Math.round(status.auto_threshold * 10 / 2)}분
                </span>
              </p>
            </div>
          </>
        ) : <div className="empty-state compact"><strong>근거 자료를 불러오지 못함</strong><span>scripts/prepare_walkforward_reference.py 실행 필요</span></div>}
      </section>
    </>
  );
}

export default function App() {
  const [activeView, setActiveView] = useState("monitor");
  const [mobileNav, setMobileNav] = useState(false);
  const [user, setUser] = useState(USERS[0]);
  const [summary, setSummary] = useState(EMPTY_SUMMARY);
  const [predictions, setPredictions] = useState([]);
  const [search, setSearch] = useState(EMPTY_SEARCH);
  const [searchResult, setSearchResult] = useState({ items: [], total: 0 });
  const [searchBusy, setSearchBusy] = useState(false);
  const [inspectionQueue, setInspectionQueue] = useState([]);
  const [equipmentSummary, setEquipmentSummary] = useState([]);
  const [selectedEquipment, setSelectedEquipment] = useState("all");
  const [queueFamily, setQueueFamily] = useState("all");
  const [trendOffset, setTrendOffset] = useState(0);
  const [trendHistory, setTrendHistory] = useState({ items: [], total: 0, limit: 60, offset: 0 });
  const [inspections, setInspections] = useState([]);
  const [thresholdHistory, setThresholdHistory] = useState([]);
  const [modelInfo, setModelInfo] = useState(null);
  const [modelRegistry, setModelRegistry] = useState([]);
  const [retrainState, setRetrainState] = useState(null);
  const [walkforward, setWalkforward] = useState(null);
  const [retrainModal, setRetrainModal] = useState(false);
  const [retrainReason, setRetrainReason] = useState("");
  const [draftThreshold, setDraftThreshold] = useState(DEFAULT_THRESHOLD);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(null);
  const [inspectionRecord, setInspectionRecord] = useState(null);
  const [thresholdModal, setThresholdModal] = useState(false);
  const [thresholdReason, setThresholdReason] = useState("");
  const [thresholdDirty, setThresholdDirty] = useState(false);
  const [toast, setToast] = useState(null);
  const [fatalError, setFatalError] = useState(null);
  const busyRef = useRef(false);
  const thresholdDirtyRef = useRef(false);

  const notify = useCallback((message, tone = "success") => {
    setToast({ message, tone });
    window.setTimeout(() => setToast(null), 3200);
  }, []);

  const loadAll = useCallback(async () => {
    try {
      const [nextSummary, nextPredictions, nextEvents, nextQueue, nextEquipmentSummary, nextInspections, nextHistory, nextModel, nextRegistry, nextRetrainStatus] = await Promise.all([
        api.summary(selectedEquipment), api.predictions(60, selectedEquipment), api.predictionEvents(60, trendOffset, selectedEquipment), api.inspectionQueue(500, selectedEquipment), api.equipmentSummary(), api.inspections(), api.thresholdHistory(), api.modelInfo(), api.modelRegistry(), api.retrainStatus(),
      ]);
      setSummary(nextSummary);
      setPredictions(nextPredictions);
      setTrendHistory(nextEvents);
      setInspectionQueue(nextQueue);
      setEquipmentSummary(nextEquipmentSummary);
      setInspections(nextInspections);
      setThresholdHistory(nextHistory);
      setModelInfo(nextModel);
      setModelRegistry(nextRegistry);
      setRetrainState(nextRetrainStatus);
      if (!thresholdDirtyRef.current) {
        setDraftThreshold(nextSummary.current_threshold);
      }
      setFatalError(null);
    } catch (error) {
      setFatalError(error.message);
    }
  }, [selectedEquipment, trendOffset]);

  useEffect(() => { loadAll(); }, [loadAll]);
  // 07_2 근거표는 고정 자료라 최초 1회만 읽는다.
  useEffect(() => { api.walkforward().then(setWalkforward).catch(() => setWalkforward(null)); }, []);

  const advance = useCallback(async (count = 1, silent = false) => {
    if (busyRef.current) return;
    busyRef.current = true;
    // 자동 재생(silent)은 1초마다 돌기 때문에 busy를 올렸다 내리면 disabled={busy}가
    // 걸린 버튼들이 매초 흐려졌다 진해져 깜빡인다. 재진입은 busyRef가 막으므로
    // 자동 재생 중에는 busy를 건드리지 않는다.
    if (!silent) setBusy(true);
    try {
      await api.next(count);
      await loadAll();
    } catch (error) {
      setRunning(false);
      notify(error.message, "error");
    } finally {
      busyRef.current = false;
      if (!silent) {
        setBusy(false);
        setSelected(null);
      }
    }
  }, [loadAll, notify]);

  const demoFinished = summary.demo_total > 0 && summary.demo_cursor >= summary.demo_total;

  useEffect(() => {
    // 표본을 한 바퀴 재생하면 순환하지 않고 정지 상태로 둔다
    if (demoFinished && running) setRunning(false);
  }, [demoFinished, running]);

  useEffect(() => {
    if (!running || demoFinished) return undefined;
    const timer = window.setInterval(() => advance(1, true), REPLAY_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [running, demoFinished, advance]);

  const searchActive = Boolean(search.keyword.trim() || search.state !== "all" || search.from || search.to);

  useEffect(() => {
    if (!searchActive) {
      setSearchResult({ items: [], total: 0 });
      return undefined;
    }
    setSearchBusy(true);
    const timer = window.setTimeout(() => {
      api.searchPredictions({ ...search, equipCd: selectedEquipment })
        .then((result) => setSearchResult({ items: result.items, total: result.total }))
        .catch(() => setSearchResult({ items: [], total: 0 }))
        .finally(() => setSearchBusy(false));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [search, searchActive, selectedEquipment, summary.received]);

  const selectByRecordId = useCallback(async (recordId) => {
    // 추이 그래프의 이벤트 행에는 공정값과 검사 상태가 없어 원본 예측 행을 다시 가져온다
    const fromFeed = predictions.find((item) => item.record_id === recordId);
    if (fromFeed) {
      setSelected(fromFeed);
      return;
    }
    try {
      setSelected(await api.prediction(recordId));
    } catch (error) {
      setToast({ tone: "error", message: "제품 상세를 불러오지 못했습니다." });
    }
  }, [predictions]);

  const changeSearch = (patchValue) => setSearch((previous) => ({ ...previous, ...patchValue }));
  const resetSearch = () => setSearch(EMPTY_SEARCH);

  const metric = useMemo(() => {
    if (!modelInfo?.threshold_metrics?.length) return null;
    return modelInfo.threshold_metrics.reduce((best, row) =>
      Math.abs(row.threshold - draftThreshold) < Math.abs(best.threshold - draftThreshold) ? row : best,
    );
  }, [modelInfo, draftThreshold]);

  const changeDraftThreshold = (value) => {
    const dirty = Math.abs(value - summary.current_threshold) >= 0.001;
    setDraftThreshold(value);
    setThresholdDirty(dirty);
    thresholdDirtyRef.current = dirty;
  };

  const changeEquipment = (equipment) => {
    setTrendOffset(0);
    setSelectedEquipment(equipment);
  };

  const reset = async () => {
    setRunning(false);
    setBusy(true);
    try {
      await api.reset();
      setTrendOffset(0);
      thresholdDirtyRef.current = false;
      setThresholdDirty(false);
      await loadAll();
      notify("시연 데이터와 업무 상태를 초기화했습니다.");
    } catch (error) { notify(error.message, "error"); }
    finally { setBusy(false); }
  };

  const applyThreshold = async () => {
    if (!thresholdReason.trim()) return;
    setBusy(true);
    try {
      await api.changeThreshold(draftThreshold, user.name, thresholdReason.trim());
      thresholdDirtyRef.current = false;
      setThresholdDirty(false);
      await loadAll();
      setThresholdModal(false);
      setThresholdReason("");
      notify(`Threshold를 ${percentage(draftThreshold)}로 변경했습니다.`);
    } catch (error) { notify(error.message, "error"); }
    finally { setBusy(false); }
  };

  const runRetrain = async () => {
    if (!retrainReason.trim()) return;
    setBusy(true);
    try {
      const entry = await api.retrain(user.name, retrainReason.trim());
      await loadAll();
      setRetrainModal(false);
      setRetrainReason("");
      notify(`${entry.version}으로 재학습했습니다. 학습 ${entry.train_records.toLocaleString()}건 (검사 ${entry.added_records}건 반영)`);
    } catch (error) { notify(error.message, "error"); }
    finally { setBusy(false); }
  };

  const runValidation = async () => {
    setBusy(true);
    try {
      const entry = await api.validate();
      await loadAll();
      const ap = entry.validation?.average_precision_mean;
      notify(`${entry.version} 검증을 마쳤습니다. AP ${ap?.toFixed(4)} (학습 ${entry.train_records.toLocaleString()}건 기준)`);
    } catch (error) { notify(error.message, "error"); }
    finally { setBusy(false); }
  };

  const startInspection = async (record) => {
    setBusy(true);
    try {
      await api.startInspection(record.record_id, user);
      await loadAll();
      setSelected(null);
      notify(`${record.part} 검사를 시작했습니다.`);
    } catch (error) { notify(error.message, "error"); }
    finally { setBusy(false); }
  };

  const completeInspection = async (payload) => {
    setBusy(true);
    try {
      const result = await api.completeInspection(inspectionRecord.record_id, payload);
      await loadAll();
      setInspectionRecord(null);
      if (result?.auto_retrained) {
        notify(`검사 결과 저장 후 ${result.auto_retrained.version}으로 자동 재학습했습니다.`);
      } else {
        notify("검사 결과와 조치 내용을 저장했습니다.");
      }
    } catch (error) { notify(error.message, "error"); }
    finally { setBusy(false); }
  };

  const navItems = [
    { id: "monitor", label: "실시간 관제", icon: Gauge },
    { id: "history", label: "검사·변경 이력", icon: History },
    { id: "model", label: "모델 정보", icon: BarChart3 },
    { id: "ops", label: "모델 운영", icon: RefreshCcw },
  ];

  const activeEquipment = equipmentSummary.find((item) => item.equip_cd === selectedEquipment);

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNav ? "open" : ""}`}>
        <div className="brand"><div className="brand-symbol"><Activity size={18} /></div><div><strong>사출 품질 관제</strong><span>Defect Prevention</span></div></div>
        <nav>{navItems.map(({ id, label, icon: Icon }) => <button type="button" key={id} className={activeView === id ? "active" : ""} onClick={() => { setActiveView(id); setMobileNav(false); }}><Icon size={19} /><span>{label}</span></button>)}</nav>
        <div className="sidebar-user"><div className="avatar">{user.name[0]}</div><div><strong>{user.name}</strong><span>{user.role}</span></div><LogOut size={17} /></div>
      </aside>
      {mobileNav && <button className="nav-scrim" onClick={() => setMobileNav(false)} aria-label="메뉴 닫기" />}

      <div className="workspace">
        <header className="topbar">
          <button className="mobile-menu" type="button" onClick={() => setMobileNav(true)} aria-label="메뉴 열기"><Menu size={21} /></button>
          <div className="plant-context"><span>설비 범위</span><strong>{activeEquipment ? `${activeEquipment.equip_cd} · ${activeEquipment.equip_name}` : "전체 사출기"}</strong></div>
          <div className="topbar-actions">
            <div className="server-health"><span className="live-dot" />API 정상<em>{modelInfo?.model_version || "모델 확인 중"}</em></div>
            <label className="user-select"><UserRound size={16} /><select value={user.id} onChange={(event) => setUser(USERS.find((item) => item.id === event.target.value))} aria-label="시연 사용자"><option value="manager-01">박품질 · 관리자</option><option value="worker-01">김현장 · 작업자</option><option value="analyst-01">이분석 · 분석</option></select></label>
          </div>
        </header>

        <main>
          {fatalError ? <section className="connection-error"><AlertTriangle size={28} /><div><strong>예측 서버에 연결할 수 없습니다.</strong><p>{fatalError}</p><span>FastAPI 서버가 8001번 포트에서 실행 중인지, 그리고 이 화면 주소가 127.0.0.1:5173인지 확인하세요. 다른 포트(예: 5174)로 열리면 브라우저가 요청을 차단합니다.</span></div><button className="button secondary" onClick={loadAll}><RefreshCcw size={16} /> 다시 연결</button></section> : (
            <>
              {activeView === "monitor" && <MonitoringView summary={summary} predictions={predictions} inspectionQueue={inspectionQueue} equipmentSummary={equipmentSummary} selectedEquipment={selectedEquipment} setSelectedEquipment={changeEquipment} trendHistory={trendHistory} trendOffset={trendOffset} onOlderTrend={() => setTrendOffset((value) => value + 60)} onNewerTrend={() => setTrendOffset((value) => Math.max(0, value - 60))} modelInfo={modelInfo} draftThreshold={draftThreshold} onDraftThresholdChange={changeDraftThreshold} thresholdDirty={thresholdDirty} metric={metric} running={running} busy={busy} demoFinished={demoFinished} onToggleRun={() => setRunning((value) => !value)} onNext={() => advance(1)} onReset={reset} onThresholdApply={() => setThresholdModal(true)} onSelect={setSelected} onSelectRecordId={selectByRecordId} onStartInspection={startInspection} user={user} search={search} onSearchChange={changeSearch} onSearchReset={resetSearch} searchResult={searchResult} searchBusy={searchBusy} queueFamily={queueFamily} onQueueFamilyChange={setQueueFamily} />}
              {activeView === "history" && <HistoryView inspections={inspections} thresholdHistory={thresholdHistory} summary={summary} />}
              {activeView === "model" && <ModelView modelInfo={modelInfo} walkforward={walkforward} />}
              {activeView === "ops" && <ModelOpsView modelInfo={modelInfo} registry={modelRegistry} status={retrainState} walkforward={walkforward} summary={summary} busy={busy} onRetrain={() => setRetrainModal(true)} onValidate={runValidation} />}
            </>
          )}
        </main>
      </div>

      <Modal open={Boolean(selected)} onClose={() => setSelected(null)} title={selected?.part_name || "수신 제품 상세"} eyebrow={selected?.part ? `${selected.part} · PRODUCT DETAIL` : "PRODUCT DETAIL"} size="large">
        {selected && <div className="detail-layout">
          <div className="detail-main">
            <div className={`probability-hero ${selected.predicted_label === 1 ? "risk" : "safe"}`}><div><span>불량확률</span><strong>{percentage(selected.defect_probability)}</strong><small>예측 당시 기준 {percentage(selected.threshold)}</small></div><div className="status-cell right"><StatusPill prediction={selected.prediction} inspectionStatus={selected.inspection_status} supported={selected.supported} />{selected.inspector && <span className="inspector">담당 {selected.inspector}</span>}</div></div>
            <div className="detail-section"><h3>제품 정보</h3><dl className="detail-grid"><div><dt>모델 제품 범주</dt><dd>{selected.part || "지원 외 제품"}</dd></div><div><dt>제품번호</dt><dd>{selected.part_no || "-"}</dd></div><div><dt>원본 ID</dt><dd>{selected.record_id}</dd></div><div><dt>생산 시각</dt><dd>{selected.produced_at || "-"}</dd></div><div><dt>사출기</dt><dd>{selected.equip_cd || "-"} · {selected.equip_name || "이름 없음"}</dd></div></dl></div>
            {selected.supported ? <div className="detail-section"><h3>우선 확인할 공정값</h3><p className="section-note">원인 확정값이 아닌 현장 점검 후보</p><div className="process-grid">{Object.entries(selected.process_values || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><strong>{typeof value === 'number' ? value.toFixed(2) : value ?? '-'}</strong></div>)}</div></div> : <div className="unsupported-box"><Info size={18} /><div><strong>{selected.prediction}</strong><span>{selected.unsupported_reason}</span></div></div>}
          </div>
          <aside className="detail-side"><h3>업무 처리</h3>{selected.inspection_status === "검사 대기" && <><p>검사 대기 제품입니다. 담당자로 본인을 등록하고 검사를 시작합니다.</p><button className="button primary full" onClick={() => startInspection(selected)} disabled={busy}><CirclePlay size={17} /> 검사 시작</button></>}{selected.inspection_status === "검사 중" && <><p>{selected.inspector ? `${selected.inspector} 담당으로 검사가 진행 중입니다` : "검사가 진행 중입니다"}{selected.inspection_started_at ? ` (${formatDate(selected.inspection_started_at)} 시작)` : ""}. 확인을 마친 후 실제 결과와 조치를 기록하세요.</p><button className="button primary full" onClick={() => { setInspectionRecord(selected); setSelected(null); }}><ClipboardCheck size={17} /> 결과 입력</button></>}{selected.inspection_status === "검사 완료" && <><p>검사 결과가 저장된 제품입니다. 이력 화면에서 조치 내용을 확인할 수 있습니다.</p><button className="button secondary full" onClick={() => { setSelected(null); setActiveView("history"); }}>이력으로 이동</button></>}{!selected.inspection_status && <><p>{selected.supported ? "현재 Threshold 미만으로 정상 판정된 제품입니다." : "현재 모델의 추론 범위 밖인 제품입니다."}</p><div className="no-action"><CirclePause size={20} /> 별도 검사 업무 없음</div></>}</aside>
        </div>}
      </Modal>

      <Modal open={Boolean(inspectionRecord)} onClose={() => setInspectionRecord(null)} title="검사 결과 입력" eyebrow="INSPECTION RESULT">
        {inspectionRecord && <InspectionForm record={inspectionRecord} worker={user} onSubmit={completeInspection} onCancel={() => setInspectionRecord(null)} submitting={busy} />}
      </Modal>

      <Modal open={thresholdModal} onClose={() => setThresholdModal(false)} title="Threshold 변경" eyebrow="DECISION STANDARD">
        <div className="threshold-confirm"><div className="change-display"><span>{percentage(summary.current_threshold)}</span><ChevronRight size={24} /><strong>{percentage(draftThreshold)}</strong></div><div className="threshold-impact"><div><span>Recall@{metric ? percentage(metric.inspect_ratio, 0) : "k"} (예상 검출률)</span><strong>{metric ? percentage(metric.recall_at_k, 1) : "-"}</strong></div><div><span>Lift (무작위 대비)</span><strong>{metric ? `${metric.lift.toFixed(1)}배` : "-"}</strong></div><div><span>검사 물량 (하루 402건 기준)</span><strong>{metric?.inspection_count_per_day || "-"}건</strong></div></div><label className="field-label">변경 사유 <span>*</span><textarea value={thresholdReason} onChange={(event) => setThresholdReason(event.target.value)} placeholder="예: 검사 인력 증가에 따라 민감도를 높임" rows={3} /></label><div className="threshold-note"><Info size={15} /><span>이미 검사 대기·진행 중인 제품은 유지되며, 변경 후 수신 제품부터 적용</span></div><div className="modal-actions"><button className="button secondary" onClick={() => { changeDraftThreshold(summary.current_threshold); setThresholdModal(false); }}>취소하고 되돌리기</button><button className="button primary" onClick={applyThreshold} disabled={!thresholdReason.trim() || busy}>{busy ? "적용 중…" : "변경 적용"}</button></div></div>
      </Modal>

      <Modal open={retrainModal} onClose={() => setRetrainModal(false)} title="모델 재학습" eyebrow="CONTINUOUS LEARNING">
        <div className="threshold-confirm">
          <div className="change-display">
            <span>{retrainState?.active_version || "-"}</span>
            <ChevronRight size={24} />
            <strong>다음 버전</strong>
          </div>
          <div className="threshold-impact">
            <div><span>반영할 검사 결과</span><strong>{retrainState?.pending_inspections ?? 0}건</strong></div>
            <div><span>현재 학습 규모</span><strong>{(modelRegistry.find((item) => item.active)?.train_records ?? 0).toLocaleString()}건</strong></div>
            <div><span>운영 Precision</span><strong>{retrainState?.observed_precision === null || retrainState?.observed_precision === undefined ? "표본 없음" : percentage(retrainState.observed_precision, 1)}</strong></div>
          </div>
          <label className="field-label">재학습 사유 <span>*</span>
            <textarea value={retrainReason} onChange={(event) => setRetrainReason(event.target.value)} placeholder="예: 검사 결과 12건 확보, 운영 성능 점검 후 반영" rows={3} />
          </label>
          <div className="threshold-note">
            <Info size={15} />
            <span>기준 학습 데이터 5,230건에 검사로 확보한 라벨을 더해 다시 학습. 완료 즉시 다음 예측부터 새 모델이 적용되며, 초기화하면 v1.1.0으로 복귀</span>
          </div>
          <div className="modal-actions">
            <button className="button secondary" onClick={() => setRetrainModal(false)}>취소</button>
            <button className="button primary" onClick={runRetrain} disabled={!retrainReason.trim() || busy}>{busy ? "학습 중…" : "재학습 실행"}</button>
          </div>
        </div>
      </Modal>

      {toast && <div className={`toast ${toast.tone}`}><CheckCircle2 size={18} />{toast.message}<button onClick={() => setToast(null)} aria-label="알림 닫기"><X size={16} /></button></div>}
    </div>
  );
}
