import { useState } from "react";

const CHECK_ITEMS = ["금형", "사출 압력", "사출 속도", "실린더 온도", "설비 상태"];

export function InspectionForm({ record, worker, onSubmit, onCancel, submitting }) {
  const [actualLabel, setActualLabel] = useState("정상");
  const [defectType, setDefectType] = useState("");
  const [checkedItems, setCheckedItems] = useState(["금형", "사출 압력"]);
  const [action, setAction] = useState("");
  const [additional, setAdditional] = useState(false);

  const toggleCheck = (item) => {
    setCheckedItems((current) => current.includes(item) ? current.filter((value) => value !== item) : [...current, item]);
  };

  const submit = (event) => {
    event.preventDefault();
    onSubmit({
      worker_id: worker.id,
      actual_label: actualLabel,
      defect_type: actualLabel === "불량" ? defectType : null,
      checked_items: checkedItems,
      action,
      additional_inspection: additional,
    });
  };

  return (
    <form className="inspection-form" onSubmit={submit}>
      <div className="inspection-target">
        <div className="inspection-product"><span>검사 대상 부품</span><strong>{record.part_name}</strong><small>{record.part} · {record.part_no || "제품번호 없음"}</small></div>
        <div><span>사출기</span><strong>{record.equip_cd || "-"}</strong><small>{record.equip_name || "설비명 없음"}</small></div>
        <div><span>불량확률</span><strong className="risk-text">{Math.round(record.defect_probability * 100)}%</strong><small>기준 {Math.round(record.threshold * 100)}%</small></div>
      </div>

      <fieldset>
        <legend>실제 검사 결과</legend>
        <div className="segmented">
          {['정상', '불량'].map((value) => (
            <label key={value} className={actualLabel === value ? "active" : ""}>
              <input type="radio" name="actual" value={value} checked={actualLabel === value} onChange={() => setActualLabel(value)} />
              {value}
            </label>
          ))}
        </div>
      </fieldset>

      {actualLabel === "불량" && (
        <label className="field-label">불량 유형 <span>*</span>
          <select value={defectType} onChange={(event) => setDefectType(event.target.value)} required>
            <option value="">유형을 선택하세요</option>
            <option value="미성형">미성형</option>
            <option value="플래시">플래시</option>
            <option value="수축">수축</option>
            <option value="표면 불량">표면 불량</option>
            <option value="치수 이상">치수 이상</option>
            <option value="기타">기타</option>
          </select>
        </label>
      )}

      <fieldset>
        <legend>확인 항목</legend>
        <div className="check-grid">
          {CHECK_ITEMS.map((item) => (
            <label key={item} className={checkedItems.includes(item) ? "checked" : ""}>
              <input type="checkbox" checked={checkedItems.includes(item)} onChange={() => toggleCheck(item)} />
              {item}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="field-label">조치 내용 <span>*</span>
        <textarea value={action} onChange={(event) => setAction(event.target.value)} placeholder="확인한 내용과 조치를 기록하세요." required minLength={2} rows={3} />
      </label>

      <label className="switch-row">
        <input type="checkbox" checked={additional} onChange={(event) => setAdditional(event.target.checked)} />
        <span className="switch" aria-hidden="true" />
        <span><strong>추가 검사 필요</strong><small>같은 Lot 또는 후속 제품을 확인 대상으로 표시합니다.</small></span>
      </label>

      <div className="modal-actions">
        <button type="button" className="button secondary" onClick={onCancel}>취소</button>
        <button type="submit" className="button primary" disabled={submitting}>{submitting ? "저장 중…" : "검사 결과 저장"}</button>
      </div>
    </form>
  );
}
