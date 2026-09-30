import { CalendarDays } from "@/components/icons";

/** 바깥 서비스의 표시. 로그인 버튼·연동 화면·스케줄의 [연동] 탭·관리자 [연결]이 같은 것을 쓴다. */
export function GoogleIcon({ size = 18 }: { size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.6 5.4 2.7 13.2l7.9 6.1C12.4 13.4 17.7 9.5 24 9.5z"/><path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4 7.1-10 7.1-17.5z"/><path fill="#FBBC05" d="M10.6 28.7c-.5-1.5-.8-3-.8-4.7s.3-3.2.8-4.7l-7.9-6.1C1 16.4 0 20.1 0 24s1 7.6 2.7 10.8l7.9-6.1z"/><path fill="#34A853" d="M24 48c6.3 0 11.7-2.1 15.6-5.7l-7.5-5.8c-2.1 1.4-4.8 2.3-8.1 2.3-6.3 0-11.6-3.9-13.4-9.4l-7.9 6.1C6.6 42.6 14.6 48 24 48z"/></svg>;
}

/** 카카오 말풍선. ``bare`` 면 말풍선만(노란 버튼 위), 아니면 노란 바탕 위에. */
export function KakaoIcon({ size = 18, bare = false }: { size?: number; bare?: boolean }) {
  const bubble = <path fill="#000" d="M12 4C7.03 4 3 7.13 3 10.99c0 2.5 1.68 4.69 4.2 5.93l-.86 3.14c-.08.28.24.5.48.34l3.73-2.47c.47.05.96.08 1.45.08 4.97 0 9-3.13 9-6.99S16.97 4 12 4z" />;
  if (bare) return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden>{bubble}</svg>;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden>
      <rect width="24" height="24" rx="6" fill="#FEE500" />
      <g transform="translate(2.4 2.4) scale(.8)">{bubble}</g>
    </svg>
  );
}

export function ProviderIcon({ provider, size = 18 }: { provider: string; size?: number }) {
  if (provider === "google") return <GoogleIcon size={size} />;
  if (provider === "kakao") return <KakaoIcon size={size} />;
  return <CalendarDays style={{ width: size, height: size }} aria-hidden />;
}
