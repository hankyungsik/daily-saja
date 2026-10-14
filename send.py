#!/usr/bin/env python3
"""오늘의 사자성어 3개를 골라 메일로 보낸다.

환경변수:
  GMAIL_USER          보내는 Gmail 주소
  GMAIL_APP_PASSWORD  Gmail 앱 비밀번호 (16자리)
  MAIL_TO             받는 주소 (쉼표로 여러 개 가능)

사용법:
  python send.py              # 발송 후 state/sent.json에 기록
  python send.py --no-record  # 발송만 하고 기록하지 않음 (테스트용)
  python send.py --dry-run    # 발송하지 않고 preview.html만 생성
  python send.py --scheduled  # 예약 실행: 주말·당일 발송분은 건너뛰고, 이르면 06:58까지 기다렸다 발송
"""
import argparse
import html
import json
import os
import random
import smtplib
import sys
import time
from datetime import datetime, time as dtime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
STATE_FILE = ROOT / "state" / "sent.json"
KST = timezone(timedelta(hours=9))
PER_DAY = 3
SHUFFLE_SEED = 20261008
WEEKDAYS = "월화수목금토일"
SEND_AT = dtime(6, 58)  # KST


def load_idioms():
    idioms = []
    for path in sorted(DATA_DIR.glob("*.json")):
        for item in json.loads(path.read_text(encoding="utf-8")):
            item["_file"] = path.stem
            idioms.append(item)
    ids = [i["id"] for i in idioms]
    if len(ids) != len(set(ids)):
        sys.exit("데이터에 중복된 id가 있습니다.")
    return idioms


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"cycle": 1, "sent_ids": [], "history": []}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


FAMILY_BY_FILE = {
    "analects": "사서", "mencius": "사서", "zhongyong": "사서", "daxue": "사서",
    "buddhism": "불가", "taoism": "도가",
    "classics": "경전", "cultivation": "수양서",
}


def family(item):
    return FAMILY_BY_FILE.get(item["_file"], item["_file"])


def pick(idioms, state):
    """아직 보내지 않은 성어 중 하루 3개를 고른다. 가능하면 서로 다른 계열, 다른 책에서 고른다."""
    order = sorted(idioms, key=lambda i: i["id"])
    random.Random(SHUFFLE_SEED + state["cycle"]).shuffle(order)

    sent = set(state["sent_ids"])
    remaining = [i for i in order if i["id"] not in sent]
    if len(remaining) < PER_DAY:
        state["cycle"] += 1
        state["sent_ids"] = []
        return pick(idioms, state)

    chosen = []
    rules = [
        lambda it: family(it) not in {family(c) for c in chosen},
        lambda it: it["book"] not in {c["book"] for c in chosen},
        lambda it: True,
    ]
    for rule in rules:
        for item in remaining:
            if len(chosen) == PER_DAY:
                return chosen
            if item not in chosen and rule(item):
                chosen.append(item)
    return chosen


def esc(text):
    return html.escape(text)


def render_html(items, today):
    date_str = f"{today.year}년 {today.month}월 {today.day}일 ({WEEKDAYS[today.weekday()]})"
    cards = []
    for n, it in enumerate(items, 1):
        cards.append(f"""
      <tr><td style="padding:0 0 28px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e7dfd0;border-radius:10px;">
          <tr><td style="padding:26px 28px 8px 28px;">
            <div style="font-size:13px;color:#9a7b4f;letter-spacing:1px;">{n} / {len(items)} &nbsp;·&nbsp; 『{esc(it['book'])}』 {esc(it['chapter'])}</div>
            <div style="font-family:'Noto Serif KR','Batang','바탕',serif;font-size:38px;color:#2b2118;letter-spacing:6px;margin:10px 0 2px 0;">{esc(it['idiom'])}</div>
            <div style="font-size:17px;color:#5a4632;font-weight:bold;">{esc(it['reading'])} <span style="font-weight:normal;color:#7a6650;">— {esc(it['meaning'])}</span></div>
          </td></tr>
          <tr><td style="padding:14px 28px 0 28px;">
            <div style="background:#faf6ee;border-left:3px solid #b08d57;padding:14px 16px;border-radius:4px;">
              <div style="font-size:12px;color:#9a7b4f;margin-bottom:6px;">원문</div>
              <div style="font-family:'Noto Serif KR','Batang','바탕',serif;font-size:16px;line-height:1.8;color:#2b2118;">{esc(it['original'])}</div>
              <div style="font-size:12px;color:#9a7b4f;margin:12px 0 6px 0;">풀이</div>
              <div style="font-size:15px;line-height:1.75;color:#3d3024;">{esc(it['translation'])}</div>
            </div>
          </td></tr>
          <tr><td style="padding:18px 28px 0 28px;">
            <div style="font-size:13px;color:#9a7b4f;font-weight:bold;margin-bottom:6px;">배경과 이야기</div>
            <div style="font-size:15px;line-height:1.8;color:#3d3024;">{esc(it['story'])}</div>
          </td></tr>
          <tr><td style="padding:18px 28px 26px 28px;">
            <div style="background:#f3efe6;border-radius:6px;padding:14px 16px;">
              <div style="font-size:13px;color:#6b5a3e;font-weight:bold;margin-bottom:6px;">🌿 오늘의 묵상</div>
              <div style="font-size:15px;line-height:1.8;color:#3d3024;">{esc(it['reflection'])}</div>
            </div>
          </td></tr>
        </table>
      </td></tr>""")

    summary = " · ".join(f"{esc(i['idiom'])}({esc(i['reading'])})" for i in items)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>오늘의 사자성어</title></head>
<body style="margin:0;padding:0;background:#f4efe6;font-family:'Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4efe6;">
    <tr><td align="center" style="padding:28px 12px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;">
        <tr><td style="padding:0 4px 22px 4px;">
          <div style="font-size:13px;color:#9a7b4f;letter-spacing:2px;">아침을 여는 고전 한 줄</div>
          <div style="font-family:'Noto Serif KR','Batang','바탕',serif;font-size:28px;color:#2b2118;margin-top:4px;">📜 오늘의 사자성어</div>
          <div style="font-size:14px;color:#7a6650;margin-top:6px;">{date_str} &nbsp;|&nbsp; {summary}</div>
        </td></tr>
        {''.join(cards)}
        <tr><td style="padding:4px 4px 0 4px;font-size:12px;line-height:1.7;color:#a08c70;text-align:center;">
          사서삼경과 불경, 노장, 소학·명심보감·채근담 등 옛 고전에서 고른 구절을 평일 아침마다 보내 드립니다.<br>
          좋은 하루 되십시오.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def render_text(items, today):
    lines = [f"오늘의 사자성어 · {today:%Y-%m-%d}", ""]
    for n, it in enumerate(items, 1):
        lines += [
            f"{n}. {it['idiom']} ({it['reading']}) — {it['meaning']}",
            f"   출전: 『{it['book']}』 {it['chapter']}",
            f"   원문: {it['original']}",
            f"   풀이: {it['translation']}",
            f"   배경: {it['story']}",
            f"   묵상: {it['reflection']}",
            "",
        ]
    return "\n".join(lines)


def send_mail(subject, html_body, text_body):
    user = os.environ["GMAIL_USER"]
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    recipients = [a.strip() for a in os.environ["MAIL_TO"].split(",") if a.strip()]

    # 받는 사람끼리 서로의 주소가 보이지 않도록 한 사람씩 따로 보낸다.
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(user, password)
        for to in recipients:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = formataddr(("오늘의 사자성어", user))
            msg["To"] = to
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))
            smtp.sendmail(user, [to], msg.as_string())
    print(f"받는 사람 {len(recipients)}명")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="발송하지 않고 preview.html 생성")
    parser.add_argument("--no-record", action="store_true", help="발송 기록을 남기지 않음")
    parser.add_argument("--scheduled", action="store_true", help="예약 실행 모드")
    args = parser.parse_args()

    now = datetime.now(KST)
    today = now.date()
    state = load_state()

    if args.scheduled:
        if today.weekday() >= 5:
            print("주말이라 건너뜁니다.")
            return
        if any(h["date"] == today.isoformat() for h in state["history"]):
            print("오늘 이미 발송했습니다.")
            return
        send_at = datetime.combine(today, SEND_AT, tzinfo=KST)
        if now < send_at:
            wait = (send_at - now).total_seconds()
            print(f"{send_at:%H:%M} KST까지 {wait / 60:.0f}분 대기합니다.", flush=True)
            time.sleep(wait)

    items = pick(load_idioms(), state)

    subject = f"[오늘의 사자성어] {today.month}/{today.day} " + " · ".join(i["idiom"] for i in items)
    html_body = render_html(items, today)
    text_body = render_text(items, today)

    if args.dry_run:
        (ROOT / "preview.html").write_text(html_body, encoding="utf-8")
        print(f"preview.html 생성: {subject}")
        return

    send_mail(subject, html_body, text_body)
    print(f"발송 완료: {subject}")

    if not args.no_record:
        ids = [i["id"] for i in items]
        state["sent_ids"].extend(ids)
        state["history"].append({"date": today.isoformat(), "cycle": state["cycle"], "ids": ids})
        save_state(state)


if __name__ == "__main__":
    main()
