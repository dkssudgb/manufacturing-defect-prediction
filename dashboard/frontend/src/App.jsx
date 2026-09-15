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

function percentage(value, digits = 0) {
  if (value === null || value === undefined) return "-";
  return `${(value * 100).toFixed(digits)}%`;
}

function StatCard({ icon: Icon, label, value, note, tone = "blue" }) {
  return (
    <article className={`stat-card ${tone}`}>
      <div className="stat-icon"><Icon size={21} /></div>
      <div><p>{label}</p><strong>{value}</strong><span>{note}</span></div>
    </article>
  );
}

function MonitoringView({
  summary, predictions, inspectionQueue, equipmentSummary, selectedEquipment, setSelectedEquipment,
  trendHistory, trendOffset, onOlderTrend, onNewerTrend,
  modelInfo, draftThreshold, onDraftThresholdChange, thresholdDirty, metric,
  running, busy, demoFinished, onToggleRun, onNext, onReset, onThresholdApply, onSelect, onSelectRecordId,
  onStartInspection, user, search, onSearchChange, onSearchReset, searchResult, searchBusy,
}) {
  const queue = inspectionQueue;
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
        <div className="heading-status">
          <span className="live-dot" />
          <div><strong>예측 서버 정상</strong><small>{modelInfo?.model_version || "모델 확인 중"}</small></div>
        </div>
      </section>

      <section className="equipment-selector" aria-label="사출기별 현황">
        <button type="button" className={selectedEquipment === "all" ? "active" : ""} onClick={() => setSelectedEquipment("all")}>
          <div className="equipment-icon"><Factory size={19} /></div>
          <div><span>전체 설비</span><strong>전체 사출기</strong></div>
          <small>{equipmentSummary.reduce((sum, item) => sum + item.received, 0)}건 수신</small>
        </button>
        {equipmentSummary.filter((item) => item.equip_cd in KNOWN_EQUIPMENT_LABELS).map((equipment) => (
          <button
            type="button"
            key={equipment.equip_cd}
            className={`${selectedEquipment === equipment.equip_cd ? "active" : ""}${equipment.model_supported ? "" : " unsupported"}`}
            onClick={() => equipment.model_supported && setSelectedEquipment(equipment.equip_cd)}
            disabled={!equipment.model_supported}
            title={equipment.model_supported ? undefined : "모델이 학습하지 않은 설비로 예측을 지원하지 않습니다"}
          >
            <div className="equipment-code">{equipment.equip_cd}</div>
            <div>
              <span>{equipment.model_supported ? "지원 설비" : "지원 안 함"}</span>
              <strong>{equipment.equip_name}</strong>
            </div>
            <small>{equipment.model_supported
              ? (equipment.received ? `수신 ${equipment.received} · 위험 ${equipment.risk}` : "수신 없음")
              : "학습 데이터 없음"}</small>
          </button>
        ))}
      </section>

      <section className="replay-bar">
        <div className="replay-now">
          <div className={`pulse-ring ${running ? "active" : ""}`}><Activity size={19} /></div>
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
          <button type="button" className="icon-button labeled" onClick={onNext} disabled={busy || demoFinished} title={demoFinished ? "표본을 모두 재생했습니다" : "다음 제품"}><SkipForward size={18} /><span>다음</span></button>
          <button type="button" className="icon-button labeled" onClick={onReset} disabled={busy} title="초기화"><RotateCcw size={18} /><span>초기화</span></button>
        </div>
      </section>

      <section className="stats-grid">
        <StatCard icon={Database} label="전체 수신" value={summary.received.toLocaleString()} note={`지원 외 ${summary.unsupported}건 포함`} />
        <StatCard icon={ShieldCheck} label="모델 예측" value={summary.supported.toLocaleString()} note={`정상 ${summary.normal}건`} tone="cyan" />
        <StatCard icon={AlertTriangle} label="불량 위험" value={summary.risk.toLocaleString()} note={`현재 기준 ${percentage(summary.current_threshold)}`} tone="orange" />
        <StatCard icon={ClipboardCheck} label="검사 업무" value={(summary.waiting + summary.inspecting).toLocaleString()} note={`대기 ${summary.waiting} · 진행 ${summary.inspecting}`} tone="violet" />
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
          <ProbabilityChart predictions={trendHistory.items} threshold={summary.current_threshold} onSelect={onSelectRecordId} emptyMessage={selectedEquipmentInfo && !selectedEquipmentInfo.received ? `${selectedEquipmentInfo.equip_name}에서 수신된 데이터가 없습니다.${selectedEquipmentInfo.trained ? "" : " 이 설비는 모델 학습에 사용되지 않았습니다."}` : undefined} />
          <div className="chart-summary">
            <div><span>최근 지원 제품</span><strong>{current?.supported ? current.part : supported[0]?.part || "-"}</strong></div>
            <div><span>최근 불량확률</span><strong className={(current?.defect_probability || 0) >= summary.current_threshold ? "risk-text" : ""}>{current?.supported ? percentage(current.defect_probability) : supported[0] ? percentage(supported[0].defect_probability) : "-"}</strong></div>
            <div><span>지원 처리율</span><strong>{summary.received ? percentage(summary.supported / summary.received) : "-"}</strong></div>
          </div>
        </article>

        <article className="panel threshold-panel">
          <header className="panel-header">
            <div><p className="eyebrow">DECISION STANDARD</p><h2>판정 Threshold</h2></div>
            <SlidersHorizontal size={20} />
          </header>
          <div className="threshold-value"><strong>{Math.round(draftThreshold * 100)}</strong><span>%</span><small>허용 범위 8~64%</small>{thresholdDirty && <em>미적용 변경</em>}</div>
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
            <div><span>Recall@k (예상 검출률)</span><strong>{metric ? percentage(metric.recall_at_k, 1) : "-"}</strong></div>
            <div><span>검사 물량 (하루 {dailyBaseline}건 기준)</span><strong>{metric ? `${metric.inspection_count_per_day}건` : "-"}</strong></div>
          </div>
          <div className="threshold-note"><Info size={15} /><span>같은 기간 교차검증(5-fold × 3반복) 기준 예상값입니다. 새로운 기간에서는 낮아질 수 있습니다.</span></div>
          <div className="threshold-actions">
            <button
              type="button"
              className="button secondary"
              onClick={() => onDraftThresholdChange(defaultThreshold)}
              disabled={Math.abs(draftThreshold - defaultThreshold) < 0.001}
              title={`모델 권장 기본값 ${Math.round(defaultThreshold * 100)}%로 되돌립니다`}
            >
              <RotateCcw size={16} /> 기본값 {Math.round(defaultThreshold * 100)}%로
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
        {queue.length ? (
          <div className="queue-list">
            {queue.map((record) => (
              <button type="button" className="queue-row" key={record.record_id} onClick={() => onSelect(record)}>
                <div className="part-mark">{record.part?.slice(0, 3)}<small>{record.part?.slice(3)}</small></div>
                <div className="queue-product"><strong>{record.part_name}</strong><span>{record.part} · {record.part_no || "제품번호 없음"}</span></div>
                <div className="queue-equipment"><span>설비</span><strong>{record.equip_cd || "-"}</strong></div>
                <div className="probability-cell"><span>불량확률</span><strong>{percentage(record.defect_probability)}</strong><div><i style={{ width: percentage(record.defect_probability) }} /></div></div>
                <StatusPill prediction={record.prediction} inspectionStatus={record.inspection_status} />
                <span className="time-cell">{formatDate(record.produced_at)}</span>
                <ChevronRight size={18} />
              </button>
            ))}
          </div>
        ) : <div className="empty-state"><CheckCircle2 size={26} /><strong>현재 검사 대기 제품이 없습니다.</strong><span>불량 위험 제품이 수신되면 이곳에 표시됩니다.</span></div>}
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
                  <td><StatusPill prediction={record.prediction} inspectionStatus={record.inspection_status} supported={record.supported} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {searchActive && !rows.length && !searchBusy && (
            <div className="empty-state compact"><strong>검색 결과가 없습니다</strong><span>조건을 바꾸거나 초기화해 보세요</span></div>
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
      <section className="stats-grid three">
        <StatCard icon={ClipboardCheck} label="검사 완료" value={completeCount} note={`전체 검사 ${inspections.length}건`} tone="violet" />
        <StatCard icon={CheckCircle2} label="운영 Precision" value={operatingPrecision === null ? "표본 없음" : percentage(operatingPrecision, 1)} note="검사 완료 제품 기준" tone="cyan" />
        <StatCard icon={SlidersHorizontal} label="Threshold 변경" value={thresholdHistory.length} note={`현재 ${percentage(summary.current_threshold)}`} tone="orange" />
      </section>
      <section className="panel">
        <header className="panel-header"><div><p className="eyebrow">INSPECTION LOG</p><h2>검사 이력</h2></div></header>
        {inspections.length ? <div className="table-scroll"><table><thead><tr><th>부품명</th><th>사출기</th><th>불량확률</th><th>검사자</th><th>상태</th><th>실제 결과</th><th>평가</th><th>완료 시각</th></tr></thead><tbody>
          {inspections.map((item) => <tr key={item.id}><td><strong>{item.part_name}</strong><small className="table-sub">{item.part} · {item.part_no}</small></td><td>{item.equip_cd || "-"}</td><td className="risk-text">{percentage(item.defect_probability)}</td><td>{item.worker_name}</td><td>{item.completed_at ? "검사 완료" : "검사 중"}</td><td>{item.actual_label || "-"}</td><td>{item.evaluation || "-"}</td><td>{formatDate(item.completed_at, true)}</td></tr>)}
        </tbody></table></div> : <div className="empty-state"><ClipboardCheck size={26} /><strong>아직 검사 이력이 없습니다.</strong><span>검사 대기열에서 업무를 시작해 보세요.</span></div>}
      </section>
      <section className="panel">
        <header className="panel-header"><div><p className="eyebrow">AUDIT LOG</p><h2>Threshold 변경 이력</h2></div></header>
        {thresholdHistory.length ? <div className="history-list">{thresholdHistory.map((item) => <div key={item.id} className="history-item"><div className="history-icon"><SlidersHorizontal size={17} /></div><div><strong>{percentage(item.previous_threshold)} <ChevronRight size={14} /> {percentage(item.new_threshold)}</strong><span>{item.reason}</span></div><div><strong>{item.changed_by}</strong><span>{formatDate(item.changed_at, true)}</span></div></div>)}</div> : <div className="empty-state compact"><History size={24} /><strong>변경 이력이 없습니다.</strong></div>}
      </section>
    </>
  );
}

function ModelView({ modelInfo }) {
  if (!modelInfo) return null;
  return (
    <>
      <section className="page-heading"><div><p className="eyebrow">MODEL GOVERNANCE</p><h1>모델 및 검증 정보</h1><p>현재 운영 모델의 입력 계약과 검사 물량별 교차검증 결과입니다.</p></div></section>
      <section className="model-hero panel">
        <div className="model-icon"><Layers3 size={28} /></div>
        <div><span className="overline">ACTIVE MODEL</span><h2>{modelInfo.model_type}</h2><p>{modelInfo.model_version}</p></div>
        <div className="model-hero-stats"><div><span>입력 피처</span><strong>{modelInfo.feature_count}</strong></div><div><span>기본 Threshold</span><strong>{percentage(modelInfo.default_threshold)}</strong></div><div><span>Average Precision</span><strong>{modelInfo.validation.average_precision_mean.toFixed(3)} ± {modelInfo.validation.average_precision_std.toFixed(3)}</strong></div></div>
      </section>
      <section className="model-grid">
        <article className="panel"><header className="panel-header"><h2>추론 파이프라인</h2></header><div className="pipeline-list">{modelInfo.pipeline.map((item, index) => <div key={item}><span>{String(index + 1).padStart(2, '0')}</span><strong>{item}</strong>{index < modelInfo.pipeline.length - 1 && <ChevronRight size={17} />}</div>)}</div></article>
        <article className="panel"><header className="panel-header"><h2>지원 제품</h2></header><div className="part-grid">{modelInfo.supported_parts.map((part) => <div key={part}><ShieldCheck size={18} /><strong>{part}</strong><span>추론 가능</span></div>)}</div></article>
      </section>
      <section className="panel validation-panel">
        <header className="panel-header"><div><p className="eyebrow">CROSS VALIDATION</p><h2>검사 물량별 검증 성능</h2></div><span className="warning-chip"><AlertTriangle size={14} /> 불량 {modelInfo.validation.defects}건 기준</span></header>
        <div className="validation-warning"><Info size={17} /><span>{modelInfo.validation.warning}</span></div>
        <div className="validation-warning"><Info size={17} /><span>{modelInfo.validation.daily_basis_note}</span></div>
        <div className="table-scroll"><table><thead><tr><th>Threshold</th><th>검사 물량</th><th>Recall@k (불량 검출률)</th><th>Precision@k (검사 적중률)</th><th>Lift</th><th>예상 검사 수 (하루)</th></tr></thead><tbody>
          {modelInfo.threshold_metrics.map((row) => <tr key={row.threshold} className={row.threshold === modelInfo.default_threshold ? "selected-row" : ""}><td><strong>{percentage(row.threshold)}</strong>{row.threshold === modelInfo.default_threshold && <span className="default-tag">기본</span>}</td><td>{percentage(row.inspect_ratio, 0)}</td><td>{percentage(row.recall_at_k, 1)}</td><td>{percentage(row.precision_at_k, 1)}</td><td>{row.lift.toFixed(1)}배</td><td>{row.inspection_count_per_day}건</td></tr>)}
        </tbody></table></div>
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
  const [trendOffset, setTrendOffset] = useState(0);
  const [trendHistory, setTrendHistory] = useState({ items: [], total: 0, limit: 60, offset: 0 });
  const [inspections, setInspections] = useState([]);
  const [thresholdHistory, setThresholdHistory] = useState([]);
  const [modelInfo, setModelInfo] = useState(null);
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
      const [nextSummary, nextPredictions, nextEvents, nextQueue, nextEquipmentSummary, nextInspections, nextHistory, nextModel] = await Promise.all([
        api.summary(selectedEquipment), api.predictions(60, selectedEquipment), api.predictionEvents(60, trendOffset, selectedEquipment), api.inspectionQueue(500, selectedEquipment), api.equipmentSummary(), api.inspections(), api.thresholdHistory(), api.modelInfo(),
      ]);
      setSummary(nextSummary);
      setPredictions(nextPredictions);
      setTrendHistory(nextEvents);
      setInspectionQueue(nextQueue);
      setEquipmentSummary(nextEquipmentSummary);
      setInspections(nextInspections);
      setThresholdHistory(nextHistory);
      setModelInfo(nextModel);
      if (!thresholdDirtyRef.current) {
        setDraftThreshold(nextSummary.current_threshold);
      }
      setFatalError(null);
    } catch (error) {
      setFatalError(error.message);
    }
  }, [selectedEquipment, trendOffset]);

  useEffect(() => { loadAll(); }, [loadAll]);

  const advance = useCallback(async (count = 1, silent = false) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try {
      await api.next(count);
      await loadAll();
    } catch (error) {
      setRunning(false);
      notify(error.message, "error");
    } finally {
      busyRef.current = false;
      setBusy(false);
      if (!silent) setSelected(null);
    }
  }, [loadAll, notify]);

  const demoFinished = summary.demo_total > 0 && summary.demo_cursor >= summary.demo_total;

  useEffect(() => {
    // 표본을 한 바퀴 재생하면 순환하지 않고 정지 상태로 둔다
    if (demoFinished && running) setRunning(false);
  }, [demoFinished, running]);

  useEffect(() => {
    if (!running || demoFinished) return undefined;
    const timer = window.setInterval(() => advance(1, true), 2500);
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
      await api.completeInspection(inspectionRecord.record_id, payload);
      await loadAll();
      setInspectionRecord(null);
      notify("검사 결과와 조치 내용을 저장했습니다.");
    } catch (error) { notify(error.message, "error"); }
    finally { setBusy(false); }
  };

  const navItems = [
    { id: "monitor", label: "실시간 관제", icon: Gauge },
    { id: "history", label: "검사·변경 이력", icon: History },
    { id: "model", label: "모델 정보", icon: BarChart3 },
  ];

  const activeEquipment = equipmentSummary.find((item) => item.equip_cd === selectedEquipment);

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNav ? "open" : ""}`}>
        <div className="brand"><div className="brand-symbol"><Activity size={22} /></div><div><strong>사출 품질 관제</strong><span>Defect Prevention</span></div></div>
        <nav>{navItems.map(({ id, label, icon: Icon }) => <button type="button" key={id} className={activeView === id ? "active" : ""} onClick={() => { setActiveView(id); setMobileNav(false); }}><Icon size={19} /><span>{label}</span></button>)}</nav>
        <div className="sidebar-model"><div><span className="live-dot" /><strong>MODEL ONLINE</strong></div><p>{modelInfo ? `${modelInfo.model_type} · ${modelInfo.model_version}` : "모델 확인 중"}</p><small>{modelInfo ? `${modelInfo.feature_count} features` : "-"}</small></div>
        <div className="sidebar-user"><div className="avatar">{user.name[0]}</div><div><strong>{user.name}</strong><span>{user.role}</span></div><LogOut size={17} /></div>
      </aside>
      {mobileNav && <button className="nav-scrim" onClick={() => setMobileNav(false)} aria-label="메뉴 닫기" />}

      <div className="workspace">
        <header className="topbar">
          <button className="mobile-menu" type="button" onClick={() => setMobileNav(true)} aria-label="메뉴 열기"><Menu size={21} /></button>
          <div className="plant-context"><span>설비 범위</span><strong>{activeEquipment ? `${activeEquipment.equip_cd} · ${activeEquipment.equip_name}` : "전체 사출기"}</strong><ChevronRight size={15} /><span>주간조</span></div>
          <div className="topbar-actions">
            <div className="server-health"><span className="live-dot" /> API 정상</div>
            <label className="user-select"><UserRound size={16} /><select value={user.id} onChange={(event) => setUser(USERS.find((item) => item.id === event.target.value))} aria-label="시연 사용자"><option value="manager-01">박품질 · 관리자</option><option value="worker-01">김현장 · 작업자</option><option value="analyst-01">이분석 · 분석</option></select></label>
          </div>
        </header>

        <main>
          {fatalError ? <section className="connection-error"><AlertTriangle size={28} /><div><strong>예측 서버에 연결할 수 없습니다.</strong><p>{fatalError}</p><span>FastAPI 서버가 8000번 포트에서 실행 중인지 확인하세요.</span></div><button className="button secondary" onClick={loadAll}><RefreshCcw size={16} /> 다시 연결</button></section> : (
            <>
              {activeView === "monitor" && <MonitoringView summary={summary} predictions={predictions} inspectionQueue={inspectionQueue} equipmentSummary={equipmentSummary} selectedEquipment={selectedEquipment} setSelectedEquipment={changeEquipment} trendHistory={trendHistory} trendOffset={trendOffset} onOlderTrend={() => setTrendOffset((value) => value + 60)} onNewerTrend={() => setTrendOffset((value) => Math.max(0, value - 60))} modelInfo={modelInfo} draftThreshold={draftThreshold} onDraftThresholdChange={changeDraftThreshold} thresholdDirty={thresholdDirty} metric={metric} running={running} busy={busy} demoFinished={demoFinished} onToggleRun={() => setRunning((value) => !value)} onNext={() => advance(1)} onReset={reset} onThresholdApply={() => setThresholdModal(true)} onSelect={setSelected} onSelectRecordId={selectByRecordId} onStartInspection={startInspection} user={user} search={search} onSearchChange={changeSearch} onSearchReset={resetSearch} searchResult={searchResult} searchBusy={searchBusy} />}
              {activeView === "history" && <HistoryView inspections={inspections} thresholdHistory={thresholdHistory} summary={summary} />}
              {activeView === "model" && <ModelView modelInfo={modelInfo} />}
            </>
          )}
        </main>
      </div>

      <Modal open={Boolean(selected)} onClose={() => setSelected(null)} title={selected?.part_name || "수신 제품 상세"} eyebrow={selected?.part ? `${selected.part} · PRODUCT DETAIL` : "PRODUCT DETAIL"} size="large">
        {selected && <div className="detail-layout">
          <div className="detail-main">
            <div className={`probability-hero ${selected.predicted_label === 1 ? "risk" : "safe"}`}><div><span>불량확률</span><strong>{percentage(selected.defect_probability)}</strong><small>예측 당시 기준 {percentage(selected.threshold)}</small></div><StatusPill prediction={selected.prediction} inspectionStatus={selected.inspection_status} supported={selected.supported} /></div>
            <div className="detail-section"><h3>제품 정보</h3><dl className="detail-grid"><div><dt>모델 제품 범주</dt><dd>{selected.part || "지원 외 제품"}</dd></div><div><dt>제품번호</dt><dd>{selected.part_no || "-"}</dd></div><div><dt>원본 ID</dt><dd>{selected.record_id}</dd></div><div><dt>생산 시각</dt><dd>{selected.produced_at || "-"}</dd></div><div><dt>사출기</dt><dd>{selected.equip_cd || "-"} · {selected.equip_name || "이름 없음"}</dd></div></dl></div>
            {selected.supported ? <div className="detail-section"><h3>우선 확인할 공정값</h3><p className="section-note">원인 확정값이 아닌 현장 점검 후보입니다.</p><div className="process-grid">{Object.entries(selected.process_values || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><strong>{typeof value === 'number' ? value.toFixed(2) : value ?? '-'}</strong></div>)}</div></div> : <div className="unsupported-box"><Info size={18} /><div><strong>{selected.prediction}</strong><span>{selected.unsupported_reason}</span></div></div>}
          </div>
          <aside className="detail-side"><h3>업무 처리</h3>{selected.inspection_status === "검사 대기" && <><p>검사 대기 제품입니다. 담당자로 본인을 등록하고 검사를 시작합니다.</p><button className="button primary full" onClick={() => startInspection(selected)} disabled={busy}><CirclePlay size={17} /> 검사 시작</button></>}{selected.inspection_status === "검사 중" && <><p>검사가 진행 중입니다. 확인을 마친 후 실제 결과와 조치를 기록하세요.</p><button className="button primary full" onClick={() => { setInspectionRecord(selected); setSelected(null); }}><ClipboardCheck size={17} /> 결과 입력</button></>}{selected.inspection_status === "검사 완료" && <><p>검사 결과가 저장된 제품입니다. 이력 화면에서 조치 내용을 확인할 수 있습니다.</p><button className="button secondary full" onClick={() => { setSelected(null); setActiveView("history"); }}>이력으로 이동</button></>}{!selected.inspection_status && <><p>{selected.supported ? "현재 Threshold 미만으로 정상 판정된 제품입니다." : "현재 모델의 추론 범위 밖인 제품입니다."}</p><div className="no-action"><CirclePause size={20} /> 별도 검사 업무 없음</div></>}</aside>
        </div>}
      </Modal>

      <Modal open={Boolean(inspectionRecord)} onClose={() => setInspectionRecord(null)} title="검사 결과 입력" eyebrow="INSPECTION RESULT">
        {inspectionRecord && <InspectionForm record={inspectionRecord} worker={user} onSubmit={completeInspection} onCancel={() => setInspectionRecord(null)} submitting={busy} />}
      </Modal>

      <Modal open={thresholdModal} onClose={() => setThresholdModal(false)} title="Threshold 변경" eyebrow="DECISION STANDARD">
        <div className="threshold-confirm"><div className="change-display"><span>{percentage(summary.current_threshold)}</span><ChevronRight size={24} /><strong>{percentage(draftThreshold)}</strong></div><div className="threshold-impact"><div><span>Recall@k (예상 검출률)</span><strong>{metric ? percentage(metric.recall_at_k, 1) : "-"}</strong></div><div><span>Lift (무작위 대비)</span><strong>{metric ? `${metric.lift.toFixed(1)}배` : "-"}</strong></div><div><span>검사 물량 (하루 402건 기준)</span><strong>{metric?.inspection_count_per_day || "-"}건</strong></div></div><label className="field-label">변경 사유 <span>*</span><textarea value={thresholdReason} onChange={(event) => setThresholdReason(event.target.value)} placeholder="예: 검사 인력 증가에 따라 민감도를 높임" rows={3} /></label><div className="threshold-note"><Info size={15} /><span>이미 검사 대기·진행 중인 제품은 유지되며, 변경 후 수신 제품부터 적용됩니다.</span></div><div className="modal-actions"><button className="button secondary" onClick={() => { changeDraftThreshold(summary.current_threshold); setThresholdModal(false); }}>취소하고 되돌리기</button><button className="button primary" onClick={applyThreshold} disabled={!thresholdReason.trim() || busy}>{busy ? "적용 중…" : "변경 적용"}</button></div></div>
      </Modal>

      {toast && <div className={`toast ${toast.tone}`}><CheckCircle2 size={18} />{toast.message}<button onClick={() => setToast(null)} aria-label="알림 닫기"><X size={16} /></button></div>}
    </div>
  );
}
