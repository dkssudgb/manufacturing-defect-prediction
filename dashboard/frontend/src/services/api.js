const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `요청에 실패했습니다. (${response.status})`);
  }
  return response.json();
}

export const api = {
  health: () => request("/health"),
  modelInfo: () => request("/model/info"),
  summary: (equipCd = "all") => request(`/dashboard/summary${equipCd === "all" ? "" : `?equip_cd=${encodeURIComponent(equipCd)}`}`),
  equipmentSummary: () => request("/equipment/summary"),
  demoProgress: () => request("/demo/progress"),
  prediction: (recordId) => request(`/predictions/${encodeURIComponent(recordId)}`),
  predictions: (limit = 60, equipCd = "all") => request(`/predictions?limit=${limit}${equipCd === "all" ? "" : `&equip_cd=${encodeURIComponent(equipCd)}`}`),
  searchPredictions: ({ keyword = "", state = "all", from = "", to = "", equipCd = "all", limit = 60, offset = 0 } = {}) => {
    const params = new URLSearchParams({ prediction_state: state, limit, offset });
    if (keyword.trim()) params.set("keyword", keyword.trim());
    if (from) params.set("date_from", from);
    if (to) params.set("date_to", to);
    if (equipCd !== "all") params.set("equip_cd", equipCd);
    return request(`/predictions/search?${params.toString()}`);
  },
  predictionEvents: (limit = 60, offset = 0, equipCd = "all") => request(`/prediction-events?limit=${limit}&offset=${offset}${equipCd === "all" ? "" : `&equip_cd=${encodeURIComponent(equipCd)}`}`),
  inspectionQueue: (limit = 500, equipCd = "all") => request(`/inspection-queue?limit=${limit}${equipCd === "all" ? "" : `&equip_cd=${encodeURIComponent(equipCd)}`}`),
  inspections: (limit = 60) => request(`/inspections?limit=${limit}`),
  thresholdHistory: () => request("/threshold/history"),
  next: (count = 1) => request("/demo/next", { method: "POST", body: JSON.stringify({ count }) }),
  reset: () => request("/demo/reset", { method: "POST" }),
  changeThreshold: (threshold, actor, reason) =>
    request("/threshold", {
      method: "PATCH",
      body: JSON.stringify({ threshold, actor, reason }),
    }),
  startInspection: (recordId, worker) =>
    request(`/inspections/${recordId}/start`, {
      method: "POST",
      body: JSON.stringify({ worker_id: worker.id, worker_name: worker.name }),
    }),
  completeInspection: (recordId, payload) =>
    request(`/inspections/${recordId}/complete`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
