"""Every mail black-moa sends, in one envelope.

A code arriving as a bare line of text reads like a phishing attempt, and a summary that
says `question_unanswered: 1건` reads like a log. Nothing leaves without the shell below:
the black-moa mark, a title, one sentence saying why the mail exists, the content, a button
that opens the right screen, and a footer that says where it came from and how to stop it.

Email HTML is not web HTML. Tables carry the layout, every style is inline, only the logo
is fetched from outside the message, and the plain-text alternative says the same thing on
its own — a client that refuses HTML still has to work.
"""

from __future__ import annotations

from html import escape

from blackmoa.config import get_settings

BRAND = "black-moa"
ACCENT = "#1a5fe0"
INK = "#111318"
MUTED = "#6b7280"
LINE = "#e3e6ec"
PAPER = "#f6f7f9"
SOFT = "#eef3ff"
FONT = "-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Pretendard','Malgun Gothic','Segoe UI',Roboto,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"


def site() -> str:
    try:
        return (get_settings().public_url or "https://black.memo-ora.com").rstrip("/")
    except Exception:  # noqa: BLE001 — a template must never fail because settings did
        return "https://black.memo-ora.com"


def _p(text: str, *, size: int = 14, color: str = INK, margin: str = "0", weight: int = 400, line: str = "1.7") -> str:
    return f'<p style="margin:{margin};font:{weight} {size}px/{line} {FONT};color:{color};">{text}</p>'


def _shell(*, title: str, intro: str, blocks: str, footer: str, kicker: str = "", links: list[tuple[str, str]] | None = None,
           tail: str = "") -> str:
    """The one black-moa envelope every message ships in.

    The footer carries the link back to the site because a message from a domain the
    recipient has never heard of has to say where it came from — otherwise the only signal
    they have is the sender address, which is exactly what a phishing attempt controls.
    """
    base = site()
    tail = escape(tail) if tail else f"{BRAND} · 이 메일은 발신 전용이에요"
    link_row = "".join(
        f'<a href="{escape(href, quote=True)}" style="color:{MUTED};text-decoration:underline;">{escape(label)}</a>'
        f'<span style="color:{LINE};"> · </span>'
        for label, href in (links or []))
    kicker_html = (f'<td align="right" style="font:500 12px/1 {FONT};color:{MUTED};white-space:nowrap;">{escape(kicker)}</td>'
                   if kicker else "")
    return f"""\
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{escape(title)}</title>
</head>
<body style="margin:0;padding:0;background:{PAPER};-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{escape(intro)}&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAPER};padding:28px 12px;">
  <tr><td align="center">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="max-width:560px;background:#ffffff;border:1px solid {LINE};border-radius:18px;">
      <tr><td style="padding:24px 28px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td style="vertical-align:middle;">
            <a href="{base}" style="text-decoration:none;display:inline-block;">
              <img src="{base}/brand/wordmark-trim.png" width="138" height="22" alt="{BRAND}"
                   style="display:block;border:0;outline:none;height:22px;width:114px;font:800 18px/22px {FONT};color:{ACCENT};">
            </a>
          </td>
          {kicker_html}
        </tr></table>
      </td></tr>
      <tr><td style="padding:22px 28px 0;">
        <h1 style="margin:0;font:700 21px/1.35 {FONT};color:{INK};letter-spacing:-.02em;">{escape(title)}</h1>
        {_p(escape(intro), size=14, color=MUTED, margin="8px 0 0") if intro else ""}
      </td></tr>
      {blocks}
      <tr><td style="padding:18px 28px 22px;border-top:1px solid {LINE};">
        {_p(footer, size=12, color=MUTED, line="1.6")}
        <p style="margin:10px 0 0;font:400 12px/1.6 {FONT};color:{MUTED};">
          {link_row}<a href="{base}" style="color:{ACCENT};text-decoration:none;font-weight:600;">black.memo-ora.com</a>
        </p>
      </td></tr>
    </table>
    <p style="max-width:560px;margin:14px auto 0;font:400 11px/1.6 {FONT};color:{MUTED};text-align:center;">{tail}</p>
  </td></tr>
</table>
</body>
</html>"""


# ── blocks ──────────────────────────────────────────────────────────
def _code_block(code: str, minutes: int) -> str:
    """The code, opened up by letter-spacing rather than by real spaces.

    Spacing it with actual characters looks the same and copies wrong: "0 2 2 1 3 9" pasted
    into a six-character field lands as three digits.
    """
    return f"""\
      <tr><td style="padding:22px 28px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="background:{PAPER};border:1px solid {LINE};border-radius:12px;">
          <tr><td align="center" style="padding:20px 16px;">
            <div style="font:700 32px/1.2 {MONO};letter-spacing:.28em;margin-right:-.28em;color:{INK};">{escape(code)}</div>
            <div style="margin-top:8px;font:400 12px/1.5 {FONT};color:{MUTED};">{minutes}분 안에 입력해 주세요</div>
          </td></tr>
        </table>
      </td></tr>"""


def _button(label: str, href: str) -> str:
    return f"""\
      <tr><td style="padding:22px 28px 0;">
        <a href="{escape(href, quote=True)}"
           style="display:inline-block;padding:12px 22px;border-radius:10px;background:{ACCENT};color:#ffffff;
                  font:600 14px/1 {FONT};text-decoration:none;">{escape(label)}</a>
      </td></tr>"""


def _note(text: str) -> str:
    return f"""\
      <tr><td style="padding:18px 28px 22px;">
        {_p(escape(text), size=13, color=MUTED)}
      </td></tr>"""


def _paragraphs(body: str, *, top: int = 20, bottom: int = 4, size: int = 15) -> str:
    """Body text as paragraphs. Blank lines separate paragraphs; single line breaks stay."""
    paras = [chunk.strip() for chunk in (body or "").replace("\r\n", "\n").split("\n\n") if chunk.strip()]
    inner = "".join(_p(escape(chunk).replace("\n", "<br>"), size=size, margin="0 0 12px", line="1.75") for chunk in paras)
    return f'      <tr><td style="padding:{top}px 28px {bottom}px;">{inner}</td></tr>'


def _quote(text: str, who: str = "") -> str:
    """Something a person said, set apart from what we say about it."""
    who_html = _p(escape(who), size=12, color=MUTED, margin="0 0 6px", weight=600) if who else ""
    body = escape((text or "").strip()).replace("\n", "<br>")
    return f"""\
      <tr><td style="padding:20px 28px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="background:{PAPER};border-left:3px solid {ACCENT};border-radius:0 12px 12px 0;">
          <tr><td style="padding:14px 18px;">
            {who_html}{_p(body, size=15, line="1.75")}
          </td></tr>
        </table>
      </td></tr>"""


def _stats(items: list[tuple[str, str]]) -> str:
    """Label on the left, number on the right: a summary, not a log line per key.

    Values are coerced rather than trusted. A count that arrives as a number instead of a
    string is not worth losing somebody's whole morning mail over.
    """
    rows = "".join(
        f'<tr><td style="padding:11px 0;border-top:1px solid {LINE};font:400 14px/1.5 {FONT};color:{INK};">{escape(str(label))}</td>'
        f'<td align="right" style="padding:11px 0;border-top:1px solid {LINE};font:700 15px/1.5 {FONT};color:{INK};white-space:nowrap;">{escape(str(value))}</td></tr>'
        for label, value in items)
    return f"""\
      <tr><td style="padding:16px 28px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-bottom:1px solid {LINE};">{rows}</table>
      </td></tr>"""


def _facts(rows: list[tuple[str, str]]) -> str:
    inner = "".join(
        f'<tr><td style="padding:4px 12px 4px 0;font:400 13px/1.6 {FONT};color:{MUTED};white-space:nowrap;vertical-align:top;">{escape(k)}</td>'
        f'<td style="padding:4px 0;font:500 13px/1.6 {FONT};color:{INK};">{escape(v)}</td></tr>' for k, v in rows)
    return f'      <tr><td style="padding:16px 28px 0;"><table role="presentation" cellpadding="0" cellspacing="0">{inner}</table></td></tr>'


# ── messages ────────────────────────────────────────────────────────
def verification(*, code: str, name: str = "", minutes: int = 30) -> tuple[str, str, str]:
    """(subject, text, html) for the account email-verification code."""
    who = f"{name}님, " if name.strip() else ""
    subject = f"[{BRAND}] 이메일 인증 코드 {code}"
    intro = f"{who}아래 코드를 인증 화면에 입력하면 인증이 끝나요."
    text = (f"{intro}\n\n인증 코드: {code}\n{minutes}분 안에 입력해 주세요.\n\n"
            "본인이 요청한 것이 아니라면 이 메일은 무시하셔도 돼요. 코드는 아무에게도 알려주지 마세요.")
    html = _shell(title="이메일 인증 코드", intro=intro, kicker="계정 인증",
                  blocks=_code_block(code, minutes)
                  + _note("본인이 요청한 것이 아니라면 이 메일은 무시하셔도 돼요. "
                          "저희는 어떤 경우에도 이 코드를 묻지 않으니, 아무에게도 알려주지 마세요."),
                  footer=f"{BRAND} 계정 인증을 요청한 주소로 보낸 메일이에요.")
    return subject, text, html


def company_verification(*, code: str, name: str = "", minutes: int = 15) -> tuple[str, str, str]:
    """(subject, text, html) for the work-mailbox code that proves where someone works."""
    who = f"{name}님, " if name.strip() else ""
    subject = f"[{BRAND}] 회사 인증 코드 {code}"
    intro = f"{who}아래 코드를 내 정보의 회사 인증 화면에 입력하면 돼요."
    text = (f"{intro}\n\n인증 코드: {code}\n{minutes}분 안에 입력해 주세요.\n\n"
            "본인이 요청한 것이 아니라면 이 메일은 무시하셔도 돼요. 이 메일 주소는 저장하지 않아요.")
    html = _shell(title="회사 이메일 인증 코드", intro=intro, kicker="내 회사 인증",
                  blocks=_code_block(code, minutes)
                  + _note("본인이 요청한 것이 아니라면 이 메일은 무시하셔도 돼요. "
                          "이 메일 주소는 저장하지 않고, 인증한 회사만 남아요."),
                  footer=f"{BRAND} 회원이 회사 인증에 적은 주소로 보낸 메일이에요.")
    return subject, text, html


def password_reset(*, link: str, minutes: int = 30) -> tuple[str, str, str]:
    subject = f"[{BRAND}] 비밀번호 재설정"
    intro = f"아래 버튼으로 새 비밀번호를 정할 수 있어요. 링크는 {minutes}분 동안 쓸 수 있어요."
    text = (f"{intro}\n\n{link}\n\n본인이 요청한 것이 아니라면 이 메일은 무시하셔도 돼요. "
            "비밀번호는 바뀌지 않아요.")
    html = _shell(title="비밀번호 재설정", intro=intro, kicker="계정",
                  blocks=_button("비밀번호 재설정하기", link)
                  + _note("본인이 요청한 것이 아니라면 이 메일은 무시하셔도 돼요. 비밀번호는 그대로예요."),
                  footer=f"버튼이 열리지 않으면 이 주소를 붙여넣어 주세요: {escape(link)}")
    return subject, text, html


def notification(*, subject: str, title: str, intro: str, body: str = "", quote_from: str = "",
                 link: str = "", link_label: str = "인박스 열기", kicker: str = "",
                 settings_url: str = "", unsubscribe_url: str = "", facts: list[tuple[str, str]] | None = None) -> tuple[str, str, str]:
    """One thing that happened, said once: what, who, and a button to the screen it lives on.

    `body` with `quote_from` is something a person said and is set as a quote; without it,
    the body is our own sentence. The footer says which settings page turns this off, and
    the unsubscribe link is the one-click way out that mail providers expect."""
    blocks = ""
    if body and quote_from:
        blocks += _quote(body, quote_from)
    elif body:
        blocks += _paragraphs(body, bottom=0)
    if facts:
        blocks += _facts(facts)
    if link:
        blocks += _button(link_label, link)
    blocks += '      <tr><td style="padding:0 0 22px;"></td></tr>'
    links = []
    if settings_url:
        links.append(("알림 설정", settings_url))
    if unsubscribe_url:
        links.append(("이 채널 수신 거부", unsubscribe_url))
    text = f"{title}\n\n{intro}"
    if body:
        text += f"\n\n{(quote_from + ':' + chr(10)) if quote_from else ''}{body}"
    if facts:
        text += "\n\n" + "\n".join(f"{k}: {v}" for k, v in facts)
    if link:
        text += f"\n\n{link_label}: {link}"
    if settings_url:
        text += f"\n알림 설정: {settings_url}"
    if unsubscribe_url:
        text += f"\n이 채널 수신 거부: {unsubscribe_url}"
    html = _shell(title=title, intro=intro, kicker=kicker, blocks=blocks, links=links,
                  footer="알림 설정에서 어떤 일을 어디로 알릴지 정할 수 있어요." if settings_url else f"{BRAND}에서 보낸 알림이에요.")
    return subject, text, html


def digest(*, name: str, date_label: str, items: list[tuple[str, str]], link: str,
           settings_url: str = "", unsubscribe_url: str = "") -> tuple[str, str, str]:
    """The morning summary: numbers with names a person uses, one per line, biggest first."""
    who = f"{name}님, " if name.strip() else ""
    subject = f"[{BRAND}] 오늘의 요약 · {date_label}"
    title = "오늘의 요약"
    intro = f"{who}지난 하루 동안 있었던 일이에요."
    blocks = _stats(items) + _button("인박스 열기", link) + '      <tr><td style="padding:0 0 22px;"></td></tr>'
    links = []
    if settings_url:
        links.append(("알림 설정", settings_url))
    if unsubscribe_url:
        links.append(("이 채널 수신 거부", unsubscribe_url))
    text = f"{title} · {date_label}\n\n{intro}\n\n" + "\n".join(f"{k}: {v}" for k, v in items) + f"\n\n인박스 열기: {link}"
    if settings_url:
        text += f"\n알림 설정: {settings_url}"
    if unsubscribe_url:
        text += f"\n이 채널 수신 거부: {unsubscribe_url}"
    html = _shell(title=title, intro=intro, kicker=date_label, blocks=blocks, links=links,
                  footer="아침마다 한 번, 지난 하루를 모아서 보내요. 알림 설정에서 끌 수 있어요.")
    return subject, text, html


def owner_reply(*, owner_name: str, reply: str, agent_name: str = "") -> tuple[str, str, str]:
    """The owner's answer to something a visitor left with the secretary."""
    who = owner_name.strip() or "상대방"
    subject = f"[{who}] 답장이 도착했어요"
    intro = (f"비서 {agent_name}에게 남기신 메시지에 {who}님이 답장을 보냈어요." if agent_name
             else f"남기신 메시지에 {who}님이 답장을 보냈어요.")
    text = f"{intro}\n\n{reply}\n\n---\n{BRAND} 비서를 통해 전해진 답장이에요."
    html = _shell(title=f"{who}님의 답장", intro=intro, kicker="답장",
                  blocks=_quote(reply, who) + '      <tr><td style="padding:0 0 22px;"></td></tr>',
                  footer=f"{BRAND} 비서를 통해 전해진 답장이에요. 이 메일에 답장을 보내도 {who}님에게 닿지 않아요.")
    return subject, text, html


def admin_alert(*, subject: str, text: str) -> tuple[str, str, str]:
    """Something an administrator should look at, with the console one click away."""
    title = subject.replace(f"[{BRAND}]", "").strip() or "운영 알림"
    subject = subject if subject.startswith("[") else f"[{BRAND}] {subject}"
    body = f"{title}\n\n{text}\n\n관리자 콘솔: {site()}/admin"
    html = _shell(title=title, intro="", kicker="관리자",
                  blocks=_paragraphs(text, bottom=0) + _button("관리자 콘솔 열기", f"{site()}/admin")
                  + '      <tr><td style="padding:0 0 22px;"></td></tr>',
                  footer="관리자 계정으로 보낸 운영 알림이에요.")
    return subject, body, html


def plain(*, title: str, text: str, kicker: str = "") -> tuple[str, str, str]:
    """A short message with nothing but a sentence: connection tests and the like."""
    subject = f"[{BRAND}] {title}"
    html = _shell(title=title, intro="", kicker=kicker,
                  blocks=_paragraphs(text, bottom=22), footer=f"{BRAND}에서 보낸 메일이에요.")
    return subject, text, html


def agent_message(*, sender_name: str, agent_name: str, subject: str, body: str, reply_to: str) -> tuple[str, str, str]:
    """A message a secretary wrote for its owner.

    It says who it is from and where an answer should go. Nothing here relays anything: the
    message carries a Reply-To and the recipient's mail client honours it, so the wording
    asks rather than promises. Claiming we forward replies would be describing a mailbox we
    do not run.
    """
    # AI 가 쓴 글이라는 것을 받는 사람이 알 수 있게 적는다(인공지능 기본법 제31조, plan/73).
    who = sender_name.strip() or agent_name
    footer = (f"{who}님의 AI 비서 {agent_name}가 대신 쓰고 보낸 메일이에요. 답장은 {who}님({reply_to})에게 보내주세요."
              if sender_name.strip() else
              f"AI 비서 {agent_name}가 쓰고 보낸 메일이에요. 답장은 {reply_to} 로 보내주세요.")
    text = f"{body}\n\n---\n{footer}\n{BRAND}"
    html = _shell(title=subject, intro=f"{who}님이 보낸 메일", kicker=f"AI 비서 {agent_name}",
                  blocks=_paragraphs(body, bottom=22),
                  footer=escape(footer),
                  tail=f"{BRAND} AI 비서가 보낸 메일이에요 · 답장 주소 {reply_to}")
    return subject, text, html
