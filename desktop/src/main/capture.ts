/**
 * 화면 보여주기 (plan/70) — 지금 화면 한 장을 찍는다. PC 앱에서만 할 수 있는 일이다.
 *
 * 누를 때만 찍는다. 주기적으로 찍어 올리지 않는다 — 무엇이 언제 나갔는지 사람이 안다. 찍은 것은 곧바로 보내지
 * 않고 빠른 대화에 붙여 보여 준 뒤, 사람이 보내기를 눌러야 물음과 함께 비서에게 간다. (나중에 "잠깐마다 보고 말 걸기"
 * 같은 것을 붙일 때도 이 한 장 찍기를 그대로 쓴다.)
 *
 * - **어느 화면**: 마우스가 있는 화면. 사람이 보고 있는 곳이다.
 * - **메모라의 창은 비킨다**: 찍는 동안 아바타·그 컨트롤·빠른 대화를 잠깐 숨긴다. 화면을 물었는데 아바타가 한가운데
 *   찍혀 있으면 안 된다. (창을 캡처에서 빼는 운영체제 기능은 옛 윈도에서 검은 네모로 찍혀 쓰지 않는다.)
 * - **크기**: 긴 변 1920. 원본 4K 는 수 MB 이고 모델이 글을 읽는 데 그만큼 필요하지 않다(Geny 와 같은 기준).
 * - **조용히 넘어가지 않는다**: 맥은 화면 기록 권한이 없으면 검거나 빈 화면을 준다. 그것을 "찍었다" 로 보내면 비서는
 *   화면을 본 척 엉뚱하게 답한다 — 까닭을 한 문장으로 돌려준다.
 */
import { desktopCapturer, screen, shell, systemPreferences, type NativeImage } from 'electron';
import type { ShotPreview } from '@shared/contract';

const MAX_EDGE = 1920;
const JPEG_QUALITY = 82;
const PREVIEW_EDGE = 480;
/** 창을 숨기고 합성기가 화면을 다시 그릴 때까지. */
const STEP_ASIDE_MS = 160;

export interface Shot extends ShotPreview {
  jpeg: Buffer;
  at: number;
}

export class CaptureError extends Error {
  constructor(message: string, readonly code = 'capture_failed') {
    super(message);
  }
}

/** 맥의 화면 기록 권한. 다른 운영체제는 물을 것이 없다. */
export function access(): 'granted' | 'denied' | 'restricted' | 'not-determined' | 'unknown' {
  if (process.platform !== 'darwin') return 'granted';
  try {
    return systemPreferences.getMediaAccessStatus('screen');
  } catch {
    return 'unknown';
  }
}

/** 맥: 화면 기록 권한을 켜는 곳을 연다. */
export function openPermission(): void {
  if (process.platform === 'darwin') void shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture');
}

const PERMISSION_MSG = '화면 기록 권한이 필요해요. 시스템 설정 → 개인정보 보호 및 보안 → 화면 기록에서 Memora 를 켠 뒤 앱을 다시 켜 주세요.';

function fit(width: number, height: number, edge: number): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= edge) return { width, height };
  const k = edge / longest;
  return { width: Math.round(width * k), height: Math.round(height * k) };
}

/** 거의 다 검은가(권한 없이 찍힌 맥, 합성되지 않은 화면). 1000 점만 본다. */
export function looksBlank(img: NativeImage): boolean {
  const { width, height } = img.getSize();
  if (!width || !height) return true;
  const bmp = img.toBitmap();
  const n = width * height;
  const step = Math.max(1, Math.floor(n / 1000));
  let bright = 0;
  for (let i = 0; i < n; i += step) {
    const o = i * 4;
    // BGRA
    if (bmp[o] + bmp[o + 1] + bmp[o + 2] > 36) bright++;
    if (bright > 5) return false;
  }
  return true;
}

let hooks: { stepAside: (on: boolean) => void } = { stepAside: () => {} };

/** 찍는 동안 메모라의 창을 비키게 하는 손잡이(아바타·빠른 대화가 건다). */
export function setStepAside(fn: (on: boolean) => void): void {
  hooks = { stepAside: fn };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** 지금 화면 한 장. 실패하면 사람에게 보일 한 문장을 담은 CaptureError. */
export async function take(): Promise<Shot> {
  const a = access();
  if (a === 'denied' || a === 'restricted') {
    openPermission();
    throw new CaptureError(PERMISSION_MSG, 'capture_permission');
  }
  const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  const scale = display.scaleFactor || 1;
  const want = fit(Math.round(display.size.width * scale), Math.round(display.size.height * scale), MAX_EDGE);

  hooks.stepAside(true);
  let sources: Electron.DesktopCapturerSource[] = [];
  try {
    await sleep(STEP_ASIDE_MS);
    sources = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: want, fetchWindowIcons: false });
  } catch {
    throw new CaptureError('화면을 찍지 못했어요.');
  } finally {
    hooks.stepAside(false);
  }
  if (!sources.length) {
    throw new CaptureError(process.platform === 'darwin' ? PERMISSION_MSG : '찍을 화면을 찾지 못했어요.', process.platform === 'darwin' ? 'capture_permission' : 'capture_failed');
  }
  // 화면의 번호로 고른다. 리눅스는 번호를 비워 줄 때가 있어 화면의 순서로도 맞춰 본다.
  const order = screen.getAllDisplays().findIndex((d) => d.id === display.id);
  const chosen =
    sources.find((s) => s.display_id && s.display_id === String(display.id)) ??
    (order >= 0 && sources.length === screen.getAllDisplays().length ? sources[order] : undefined) ??
    sources[0];
  const img = chosen.thumbnail;
  if (!img || img.isEmpty() || looksBlank(img)) {
    throw new CaptureError(process.platform === 'darwin' ? PERMISSION_MSG : '화면이 비어 있게 찍혔어요. 잠시 뒤에 다시 해 주세요.', process.platform === 'darwin' ? 'capture_permission' : 'capture_failed');
  }
  const size = img.getSize();
  const small = img.resize(fit(size.width, size.height, PREVIEW_EDGE));
  return {
    jpeg: img.toJPEG(JPEG_QUALITY),
    width: size.width,
    height: size.height,
    preview: `data:image/jpeg;base64,${small.toJPEG(70).toString('base64')}`,
    at: Date.now(),
  };
}
