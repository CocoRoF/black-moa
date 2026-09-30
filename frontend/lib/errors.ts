import type { Locale } from "./i18n";

export class ApiError extends Error {
  status: number;
  code: string;
  detail: unknown;
  retryAfter: number | null;
  constructor(status: number, code: string, message: string, detail?: unknown, retryAfter: number | null = null) {
    super(message || code);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.retryAfter = retryAfter;
  }
}

const MESSAGES: Record<string, { ko: string; en: string }> = {
  credits_exhausted: { ko: "크레딧이 모두 소진됐어요. 충전 후 다시 시도해 주세요.", en: "You're out of credits. Top up and try again." },
  // A balance does not lift the plan's daily cap, so "out of credits" would be a lie here.
  daily_cap_reached: { ko: "오늘 쓸 수 있는 크레딧 한도를 모두 썼어요. 잔액이 남아 있어도 플랜의 하루 한도가 우선해요 — 내일 다시 이어집니다.", en: "Today's credit cap is used up. A balance does not lift the plan's daily cap — it resumes tomorrow." },
  visitor_daily_cap: { ko: "오늘 방문자 대화 한도를 모두 썼어요. 내일 다시 열려요.", en: "Today's visitor conversation cap is used up. It reopens tomorrow." },
  turn_cap_too_small: { ko: "이번 턴에 배정할 크레딧이 부족해요.", en: "Not enough credits to reserve for this turn." },
  link_paused: { ko: "이 링크는 지금 일시정지 상태예요.", en: "This link is currently paused." },
  link_expired: { ko: "이 링크는 만료됐어요.", en: "This link has expired." },
  link_revoked: { ko: "이 링크는 더 이상 사용할 수 없어요.", en: "This link is no longer available." },
  link_not_found: { ko: "링크를 찾을 수 없어요.", en: "Link not found." },
  secretary_resting: { ko: "비서가 잠시 쉬고 있어요. 메시지를 남겨주시면 전달할게요.", en: "The secretary is resting right now. Leave a message and it will be delivered." },
  rate_limited: { ko: "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.", en: "Too many requests. Please try again shortly." },
  agent_limit: { ko: "플랜에서 만들 수 있는 비서 수를 모두 사용했어요.", en: "You've reached the number of secretaries allowed on your plan." },
  link_exists: { ko: "이 비서는 이미 공개 링크가 있어요. 주소나 모양은 지금 링크에서 바꿔 주세요.", en: "This secretary already has a public link. Change its address or look on that link." },
  link_limit: { ko: "플랜에서 만들 수 있는 링크 수를 모두 사용했어요.", en: "You've reached the number of links allowed on your plan." },
  handle_taken: { ko: "이미 사용 중인 핸들이에요.", en: "That handle is already taken." },
  invalid_handle: { ko: "핸들 형식이 올바르지 않아요. 소문자·숫자·하이픈 3~32자.", en: "Invalid handle. Use 3–32 lowercase letters, digits or hyphens." },
  reserved_handle: { ko: "예약된 핸들이라 사용할 수 없어요.", en: "That handle is reserved." },
  email_taken: { ko: "이미 가입된 이메일이에요.", en: "That email is already registered." },
  invalid_credentials: { ko: "이메일 또는 비밀번호가 올바르지 않아요.", en: "Incorrect email or password." },
  account_locked: { ko: "로그인 시도가 너무 많아 잠시 잠겼어요. 잠시 후 다시 시도해 주세요.", en: "Too many attempts. The account is temporarily locked." },
  account_suspended: { ko: "정지된 계정이에요. 관리자에게 문의해 주세요.", en: "This account is suspended. Contact the administrator." },
  embedding_key_missing: { ko: "임베딩 프로바이더 키가 설정되지 않았어요. 관리자에게 문의해 주세요.", en: "Embedding provider key is not configured. Contact the administrator." },
  invite_required: { ko: "가입에는 초대 코드가 필요해요.", en: "An invite code is required to sign up." },
  invite_invalid: { ko: "초대 코드가 올바르지 않거나 만료됐어요.", en: "Invalid or expired invite code." },
  signup_closed: { ko: "지금은 가입을 받지 않아요.", en: "Sign-ups are closed right now." },
  terms_required: { ko: "만 14세 이상이며 이용약관에 동의해야 가입할 수 있어요.", en: "You must be 14 or older and agree to the terms to sign up." },
  terms_changed: { ko: "그 사이에 약관이 바뀌었어요. 새 내용을 확인해 주세요.", en: "The terms changed in the meantime. Please review them again." },
  no_refresh: { ko: "로그인이 필요해요.", en: "Please sign in." },
  unauthorized: { ko: "로그인이 필요해요.", en: "Please sign in." },
  forbidden: { ko: "권한이 없어요.", en: "You don't have permission to do that." },
  admin_only: { ko: "관리자만 할 수 있어요.", en: "Administrators only." },
  not_found: { ko: "찾을 수 없어요.", en: "Not found." },
  validation_error: { ko: "입력값을 확인해 주세요.", en: "Please check your input." },
  visitor_blocked: { ko: "이 대화는 더 이상 이용할 수 없어요.", en: "This conversation is no longer available." },
  voice_disabled: { ko: "이 비서는 음성 기능이 꺼져 있어요.", en: "Voice is disabled for this secretary." },
  stt_disabled: { ko: "지금은 음성으로 입력할 수 없어요.", en: "Voice input is not available right now." },
  tts_disabled: { ko: "지금은 음성으로 들을 수 없어요.", en: "Listening is not available right now." },
  turnstile_failed: { ko: "봇 확인에 실패했어요. 다시 시도해 주세요.", en: "Bot verification failed. Please try again." },
  service_unavailable: { ko: "서비스가 잠시 불안정해요. 잠시 후 다시 시도해 주세요.", en: "Service is temporarily unavailable. Please try again." },
  network: { ko: "네트워크 연결을 확인해 주세요.", en: "Check your network connection." },
  turn_not_found: { ko: "대화 턴을 찾을 수 없어요.", en: "Turn not found." },
  google_denied: { ko: "Google 로그인이 취소됐어요.", en: "Google sign-in was cancelled." },
  bad_state: { ko: "로그인 상태가 만료됐어요. 다시 시도해 주세요.", en: "Sign-in state expired. Please try again." },
  email_verification_required: { ko: "비서를 만들려면 이메일 인증이 필요해요. [계정 설정]에서 인증해 주세요.", en: "Verify your email before creating a secretary — you can do it in Account settings." },
  mail_send_failed: { ko: "인증 메일을 보내지 못했어요. 메일 서버 설정을 확인해 주세요.", en: "Could not send the verification mail. Check the mail server settings." },
  community_needs_verified_email: { ko: "글과 댓글은 이메일 인증 후에 쓸 수 있어요. [인증 및 연결]에서 인증해 주세요.", en: "Verify your email before posting or commenting — you can do it under Verification & connections." },
  community_name_required: { ko: "광장에서 쓸 이름을 먼저 정해 주세요. [내 정보]의 [커뮤니티 닉네임]에서 정할 수 있어요.", en: "Set your community nickname first — you can do it under My information." },
  name_too_short: { ko: "이름은 두 글자 이상이어야 해요.", en: "Use at least two characters." },
  name_taken: { ko: "이미 누가 쓰고 있는 이름이에요.", en: "That nickname is already taken." },
  name_change_too_soon: { ko: "아직 바꿀 수 없어요. 조금 뒤에 다시 시도해 주세요.", en: "It is too soon to change it. Please try again later." },
  community_rate_limited: { ko: "잠시 뒤에 다시 시도해 주세요. 짧은 시간에 너무 많이 올렸어요.", en: "Too many in a short time. Try again shortly." },
  // Proving where you work (plan/40 §10).
  free_mail: { ko: "개인 메일 주소로는 회사를 인증할 수 없어요. 회사 메일 주소를 적어주세요.", en: "A personal mailbox can't prove an employer. Use your work address." },
  invalid_email: { ko: "메일 주소 형식이 아니에요.", en: "That isn't an email address." },
  bad_code: { ko: "코드가 맞지 않아요. 메일을 다시 확인해 주세요.", en: "That code doesn't match. Check the mail again." },
  code_expired: { ko: "코드가 만료됐어요. 다시 받아주세요.", en: "The code has expired. Ask for a new one." },
  too_many_attempts: { ko: "코드를 너무 여러 번 틀렸어요. 새 코드를 받아주세요.", en: "Too many wrong tries. Ask for a new code." },
  verify_rate_limited: { ko: "코드를 너무 자주 요청했어요. 잠시 후 다시 시도해 주세요.", en: "Too many codes requested. Try again in a while." },
  no_pending_verification: { ko: "먼저 코드를 받아주세요.", en: "Ask for a code first." },
  company_email_taken: { ko: "이 메일 주소는 이미 다른 계정에서 인증에 썼어요.", en: "That address already verified another account." },
  bad_domain: { ko: "회사 메일 주소 형식이 아니에요.", en: "That isn't a company mail domain." },
  smtp_not_configured: { ko: "메일 서버가 아직 설정되지 않았어요. 관리자에게 문의해 주세요.", en: "No mail server is configured yet. Contact the administrator." },
  invalid_verification_code: { ko: "인증 코드가 올바르지 않거나 만료됐어요.", en: "That verification code is invalid or expired." },
  weak_password: { ko: "비밀번호는 8자 이상이어야 해요.", en: "Password must be at least 8 characters." },
  password_mismatch: { ko: "현재 비밀번호가 올바르지 않아요.", en: "Current password is incorrect." },
  // 파일 (plan/55). 서버가 거절한 이유를 사람 말로.
  file_too_large: { ko: "파일이 너무 커요. 사진은 10MB, 문서는 25MB까지 올릴 수 있어요.", en: "That file is too large. Photos up to 10MB, documents up to 25MB." },
  unsupported_type: { ko: "올릴 수 없는 파일 형식이에요. 사진, PDF, 워드·엑셀·파워포인트, 글 파일을 올릴 수 있어요.", en: "That file type isn't supported. Photos, PDF, Word/Excel/PowerPoint and text files are." },
  visitor_files_unavailable: { ko: "지금은 파일을 받을 수 없어요.", en: "Files can't be received right now." },
  visitor_file_too_large: { ko: "파일이 너무 커요.", en: "That file is too large." },
  visitor_files_daily: { ko: "오늘은 더 올릴 수 없어요. 내일 다시 올려 주세요.", en: "You've sent as many files as you can today. Try again tomorrow." },
  room_not_granted: { ko: "이 대화를 볼 수 있는 허락이 없어요.", en: "Permission to read this conversation is missing." },
  not_promotable: { ko: "이 파일은 지식으로 올릴 수 없어요. 문서(PDF·워드·엑셀·파워포인트·글)만 올릴 수 있어요.", en: "Only documents (PDF, Word, Excel, PowerPoint, text) can become knowledge." },
  visitor_file_private: { ko: "방문자가 건넨 파일은 공개 범위를 바꿀 수 없어요.", en: "A visitor's file can't be shared further." },
  storage_full: { ko: "저장 공간이 가득 찼어요. [내 정보 → 파일]에서 파일을 정리하거나 공간을 늘려 주세요.", en: "Your storage is full. Free up space or get more under Storage." },
  mime_mismatch: { ko: "파일 내용이 확장자와 맞지 않아요.", en: "The file's contents don't match its type." },
  invalid_image: { ko: "사진을 열 수 없어요. 파일이 손상됐을 수 있어요.", en: "That picture can't be opened. It may be damaged." },
  image_too_many_pixels: { ko: "사진 해상도가 너무 커요.", en: "That picture's resolution is too large." },
  token_invalid: { ko: "링크가 만료됐거나 올바르지 않아요.", en: "This link is invalid or expired." },
  // 집 — 소식·메신저·인맥 (plan/42, plan/44). 서버가 영어로 말한 것을 그대로 띄우면
  // 읽는 사람에게는 오류가 아니라 남의 집 사정이다.
  not_connected: { ko: "먼저 연결해야 메시지를 보낼 수 있어요.", en: "Connect with them first to send a message." },
  dm_self: { ko: "나에게는 메시지를 보낼 수 없어요.", en: "You can't message yourself." },
  follow_self: { ko: "나를 연결할 수는 없어요.", en: "You can't connect with yourself." },
  use_turn: { ko: "비서에게는 대화로 말을 걸어요.", en: "Talk to a secretary in the chat." },
  not_a_dm: { ko: "비서와 나눈 대화는 한 줄씩 지울 수 없어요.", en: "A conversation with a secretary isn't edited line by line." },
  empty_message: { ko: "보낼 말을 적어주세요.", en: "Write something to send." },
  empty_comment: { ko: "댓글을 적어주세요.", en: "Write a comment first." },
  empty_body: { ko: "올릴 내용을 적어주세요.", en: "Write something to post." },
  empty_title: { ko: "제목을 적어주세요.", en: "Give it a title." },
  empty_query: { ko: "검색어를 적어주세요.", en: "Type something to search for." },
  empty_email: { ko: "메일 주소를 적어주세요.", en: "Enter an email address." },
  too_many_agents: { ko: "한 글에서 부를 수 있는 비서 수를 넘었어요.", en: "That's more secretaries than one post can call." },
  post_too_long: { ko: "글이 너무 길어요. 줄여서 올려주세요.", en: "That post is too long. Shorten it." },
  comment_too_long: { ko: "댓글이 너무 길어요. 줄여서 남겨주세요.", en: "That comment is too long. Shorten it." },
  comment_empty: { ko: "댓글을 적어주세요.", en: "Write a comment first." },
  room_not_found: { ko: "이 대화를 찾을 수 없어요.", en: "That conversation was not found." },
  message_not_found: { ko: "이 메시지를 찾을 수 없어요.", en: "That message was not found." },
  conversation_not_found: { ko: "대화를 찾을 수 없어요.", en: "That conversation was not found." },
  post_not_found: { ko: "이 글을 찾을 수 없어요. 지워졌을 수 있어요.", en: "That post was not found. It may have been taken down." },
  comment_not_found: { ko: "이 댓글을 찾을 수 없어요.", en: "That comment was not found." },
  account_not_found: { ko: "이 회원을 찾을 수 없어요.", en: "That member was not found." },
  agent_not_found: { ko: "이 비서를 찾을 수 없어요.", en: "That secretary was not found." },
  node_not_found: { ko: "이 카드를 찾을 수 없어요.", en: "That card was not found." },
  not_your_post: { ko: "내 글만 고치거나 지울 수 있어요.", en: "You can only change your own posts." },
  not_your_comment: { ko: "내 댓글만 지울 수 있어요.", en: "You can only remove your own comments." },
  not_owner: { ko: "권한이 없어요.", en: "You don't have permission to do that." },
  agent_not_active: { ko: "이 비서는 지금 쉬고 있어요.", en: "That secretary is resting right now." },
  link_closed: { ko: "이 링크는 지금 닫혀 있어요.", en: "That link is closed right now." },
  email_unverified: { ko: "이메일 인증 후에 쓸 수 있어요. [인증 및 연결]에서 인증해 주세요.", en: "Verify your email first, under Verification & connections." },
  // 연결로 로그인 · 데이터 연동 (plan/59). 공급자에서 돌아온 주소의 error= 도 이 표로 읽는다.
  sso_unavailable: { ko: "지금은 이 방법으로 로그인할 수 없어요.", en: "This sign-in method isn't available right now." },
  sso_denied: { ko: "로그인을 취소했어요.", en: "Sign-in was cancelled." },
  sso_failed: { ko: "로그인하지 못했어요. 다시 시도해 주세요.", en: "Couldn't sign you in. Please try again." },
  state_browser_mismatch: { ko: "로그인을 시작한 화면과 달라요. 이 화면에서 다시 시작해 주세요.", en: "This didn't start here. Please start again from this page." },
  invalid_state: { ko: "가입 마무리 링크가 만료됐어요. 처음부터 다시 시작해 주세요.", en: "This sign-up link has expired. Please start again." },
  id_token_invalid: { ko: "로그인 정보를 확인하지 못했어요. 다시 시도해 주세요.", en: "Couldn't confirm who you are. Please try again." },
  identity_taken: { ko: "이 계정은 이미 다른 Memora 계정에 이어져 있어요.", en: "That account is already linked to another Memora account." },
  identity_provider_linked: { ko: "같은 서비스의 다른 계정이 이미 이어져 있어요. 그 계정을 먼저 떼어 주세요.", en: "Another account from this service is already linked. Remove it first." },
  identity_not_found: { ko: "이 로그인 방법을 찾을 수 없어요.", en: "That sign-in method was not found." },
  last_login_method: { ko: "하나 남은 로그인 방법이라 뗄 수 없어요. 비밀번호를 먼저 만들어 주세요.", en: "It's your only way in. Set a password first." },
  user_inactive: { ko: "사용할 수 없는 계정이에요.", en: "This account can't be used." },
  provider_unknown: { ko: "연결할 수 없는 서비스예요.", en: "That service can't be connected." },
  provider_unavailable: { ko: "지금은 이 서비스를 연결할 수 없어요.", en: "This service can't be connected right now." },
  no_capability: { ko: "쓸 기능을 하나 이상 골라 주세요.", en: "Pick at least one feature." },
  denied: { ko: "연결을 취소했어요.", en: "Connecting was cancelled." },
  connection_not_found: { ko: "이 연결을 찾을 수 없어요.", en: "That connection was not found." },
  calendar_forbidden: { ko: "지금은 이 달력에서 일정을 가져올 수 없어요. 연결을 해제하고 다시 연결하거나 관리자에게 문의해 주세요.", en: "Events can't be imported from this calendar right now. Reconnect it or contact the administrator." },
  calendar_failed: { ko: "일정을 가져오지 못했어요. 잠시 후 다시 시도해 주세요.", en: "Couldn't import events. Try again in a moment." },
  contacts_forbidden: { ko: "지금은 연락처를 가져올 수 없어요. 관리자에게 문의해 주세요.", en: "Contacts can't be imported right now. Contact the administrator." },
  contacts_failed: { ko: "연락처를 가져오지 못했어요. 잠시 후 다시 시도해 주세요.", en: "Couldn't import contacts. Try again in a moment." },
  drive_not_connected: { ko: "Google Drive가 연결되어 있지 않아요. 다시 연결해 주세요.", en: "Google Drive is not connected. Connect it again." },
  drive_picker_unconfigured: { ko: "지금은 Drive에서 파일을 고를 수 없어요. 관리자에게 문의해 주세요.", en: "Picking files from Drive is not available right now. Contact the administrator." },
  drive_picker_load: { ko: "Google 파일 선택 창을 열지 못했어요. 잠시 후 다시 시도해 주세요.", en: "Could not open the Google file picker. Try again in a moment." },
  drive_folder: { ko: "폴더는 가져올 수 없어요. 폴더 안의 파일을 골라 주세요.", en: "Folders cannot be imported. Pick the files inside." },
  drive_unsupported: { ko: "이 종류의 Google 파일은 가져올 수 없어요.", en: "This kind of Google file cannot be imported." },
  drive_not_found: { ko: "Drive에서 파일을 찾지 못했어요. 지워졌거나 권한이 없는 파일이에요.", en: "The file was not found in Drive. It was deleted or you no longer have access." },
  drive_failed: { ko: "Drive에서 파일을 받지 못했어요. 잠시 후 다시 시도해 주세요.", en: "Could not get the file from Drive. Try again in a moment." },
  drive_nothing_chosen: { ko: "가져올 파일을 골라 주세요.", en: "Choose files to import." },
  imap_auth_failed: { ko: "로그인하지 못했어요. 메일 주소와 앱 비밀번호, 메일 서비스의 IMAP 사용 설정을 확인해 주세요.", en: "Could not sign in. Check the address, the app password and that IMAP is turned on." },
  imap_unreachable: { ko: "메일 서버에 연결하지 못했어요. 잠시 뒤 다시 해 주세요.", en: "Could not reach the mail server. Please try again shortly." },
  imap_host_blocked: { ko: "이 메일 서버 주소는 쓸 수 없어요.", en: "This mail server address cannot be used." },
  imap_host_invalid: { ko: "메일 서버 주소를 확인해 주세요.", en: "Check the mail server address." },
  imap_username_required: { ko: "메일 주소를 넣어 주세요.", en: "Enter your mail address." },
  imap_password_required: { ko: "앱 비밀번호를 넣어 주세요.", en: "Enter the app password." },
  imap_preset_unknown: { ko: "메일 서비스를 골라 주세요.", en: "Choose a mail service." },
  kakao_not_connected: { ko: "먼저 카카오를 연결해 주세요.", en: "Connect Kakao first." },
  kakao_message_off: { ko: "[연동]의 카카오에서 카카오톡 메시지를 먼저 켜 주세요.", en: "Turn on KakaoTalk messages under Integrations first." },
  connection_missing_fields: { ko: "필수 칸을 먼저 채워 주세요.", en: "Fill in the required fields first." },
  field_required: { ko: "꼭 있어야 하는 값이라 지울 수 없어요.", en: "That value is required." },
  unknown_field: { ko: "알 수 없는 항목이에요.", en: "Unknown field." },
  unknown_feature: { ko: "알 수 없는 기능이에요.", en: "Unknown feature." },
  holidays_key_missing: { ko: "서비스 키를 먼저 저장해 주세요.", en: "Save a service key first." },
};

/** 공급자마다 이름이 붙는 코드(google_expired · kakao_token_failed …)를 한 문장으로. */
const PROVIDER_CODES: [RegExp, { ko: string; en: string }][] = [
  [/^[a-z]+_not_configured$/, { ko: "지금은 이 서비스를 쓸 수 없어요.", en: "This service isn't available right now." }],
  [/^[a-z]+_expired$/, { ko: "연결이 끊겼어요. 다시 연결해 주세요.", en: "The connection has lapsed. Please reconnect." }],
  [/^[a-z]+_(token_)?failed$/, { ko: "연결하지 못했어요. 잠시 후 다시 시도해 주세요.", en: "Couldn't connect. Please try again shortly." }],
];

/** 주소로 돌아온 오류 코드(``?error=``)를 읽는 사람의 말로. 모르는 코드는 한 문장으로 뭉뚱그린다. */
export function codeMessage(code: string, locale: Locale = "ko"): string {
  const m = MESSAGES[code] ?? PROVIDER_CODES.find(([re]) => re.test(code))?.[1];
  return (m ?? UNKNOWN)[locale];
}

//: 우리가 아직 문구를 붙이지 않은 모든 것. 원인은 콘솔에 남는다.
const UNKNOWN: { ko: string; en: string } = {
  ko: "처리하지 못했어요. 잠시 후 다시 시도해 주세요.",
  en: "That didn't go through. Please try again in a moment.",
};

export function friendlyError(err: unknown, locale: Locale = "ko"): string {
  if (err instanceof ApiError) {
    const m = MESSAGES[err.code] ?? PROVIDER_CODES.find(([re]) => re.test(err.code))?.[1];
    if (m) {
      // A countdown in seconds is our plumbing, not something the reader can act on:
      // the sentence already says to come back in a moment.
      return m[locale];
    }
    // 서버가 읽는 사람을 향해 쓴 문장은 그대로 낸다: 한글이 들어 있으면 그 자리에서 읽히라고
    // 쓴 말이다. 나머지는 필드 이름이 붙은 영문 검증 메시지이거나 코드 이름이고, 그것은
    // 읽는 사람이 할 수 있는 일이 없는 우리 쪽 사정이다. 화면에는 한 문장만 내고 원문은
    // 콘솔에 남겨 고칠 때 찾을 수 있게 한다.
    if (/[가-힣]/.test(err.message)) return err.message;
    if (typeof console !== "undefined") console.warn("[api]", err.status, err.code, err.message, err.detail);
    return UNKNOWN[locale];
  }
  if (err instanceof TypeError && /fetch|network/i.test(err.message)) return MESSAGES.network[locale];
  if (err instanceof Error) return err.message;
  return String(err);
}
