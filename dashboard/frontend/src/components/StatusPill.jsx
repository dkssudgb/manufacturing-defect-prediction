export function StatusPill({ prediction, inspectionStatus, supported = true }) {
  const label = inspectionStatus || prediction;
  let tone = "neutral";
  if (!supported || prediction === "예측 불가") tone = "muted";
  else if (inspectionStatus === "검사 중") tone = "info";
  else if (inspectionStatus === "검사 완료") tone = "done";
  else if (prediction === "불량 위험" || inspectionStatus === "검사 대기") tone = "risk";
  else if (prediction === "정상") tone = "safe";

  return <span className={`status-pill ${tone}`}><span aria-hidden="true" />{label}</span>;
}

