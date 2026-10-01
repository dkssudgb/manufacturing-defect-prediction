import { RealtimeClient } from "@supabase/realtime-js";

// 여러 화면이 같은 서버 상태를 본다. 한 화면이 데이터를 바꾸면 Supabase Realtime
// Broadcast로 "바뀌었다"는 신호만 보내고, 받은 화면이 API에서 다시 읽는다.
// 데이터 자체는 채널에 싣지 않는다. 테이블은 RLS로 막혀 있어 공개 키로 읽을 수 없다.
//
// 환경변수가 없거나(로컬 개발) 연결이 안 되면 신호 없이 지금처럼 동작한다.
const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL;
const SUPABASE_KEY = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
const CHANNEL = "dashboard-changes";
const EVENT = "changed";

const listeners = new Set();
let channel = null;
let subscribed = false;

if (SUPABASE_URL && SUPABASE_KEY) {
  // supabase-js 전체(인증·DB·Storage 클라이언트)는 쓰지 않으므로 Realtime만 가져온다
  const client = new RealtimeClient(`${SUPABASE_URL.replace(/\/$/, "")}/realtime/v1`, {
    params: { apikey: SUPABASE_KEY },
  });
  // self: false가 기본값이라 보낸 화면은 자기 신호를 받지 않는다. 보낸 화면은
  // 요청이 끝난 뒤 스스로 loadAll()을 부르므로 중복으로 읽지 않는다.
  channel = client.channel(CHANNEL);
  channel
    .on("broadcast", { event: EVENT }, () => listeners.forEach((listener) => listener()))
    .subscribe((status) => { subscribed = status === "SUBSCRIBED"; });
}

export function notifyChange() {
  if (!channel || !subscribed) return;
  channel.send({ type: "broadcast", event: EVENT, payload: {} }).catch(() => {});
}

export function onRemoteChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
