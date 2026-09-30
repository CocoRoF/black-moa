import { Integrations } from "@/lib/api";

/** 공급자를 연결(또는 권한을 더)하고, 끝나면 ``next`` 화면으로 돌아온다 (plan/57·59).
 *  [메일] 은 메일 읽기, [스케줄] 은 일정 읽기·넣기, [알림] 은 카카오톡 메시지를 청한다. 이미 허락한 권한은 서버가 그대로 지킨다. */
export async function connectProvider(provider: string, capabilities: string[], next: string): Promise<void> {
  const { url } = await Integrations.start(provider, capabilities, next);
  window.location.href = url;
}
