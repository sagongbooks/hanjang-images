"""GitHub 자동 실행(10분마다): jobs/*/schedule.json에서 시간이 된 채널을 게시한다.

- 실제 게시는 scripts/post.py가 한다(승인.txt "올려" 확인, 첫 줄 고지 확인, 중복 방지 posted.json).
- 예약 시간에서 6시간 넘게 지난 글은 엉뚱한 시간에 올라가지 않게 건너뛰고 'missed'로 적는다.
- 모든 채널이 끝난 작업은 사진·영상을 지운다(인스타·스레드는 게시 때 이미 복사해 감).
- 토큰은 GitHub 비밀 보관함(Secrets)에서 환경 변수로만 받는다. 화면에 찍지 않는다.
"""
import datetime, glob, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://sagongbooks.github.io/hanjang-images"
DRY = os.environ.get("DRY") == "true"
LATE = datetime.timedelta(hours=6)
now = datetime.datetime.now(datetime.timezone.utc)
fail = 0
TOPIC = os.environ.get("NTFY_TOPIC", "")
NAMES = {"instagram": "인스타", "threads": "스레드"}


def notify(title, msg, click=None, tags="white_check_mark", prio=3):
    """휴대폰 알림 (ntfy 앱). 공개 게시물 링크만 담는다."""
    if not TOPIC: return
    import urllib.request
    body = {"topic": TOPIC, "title": title, "message": msg, "tags": [tags], "priority": prio}
    if click: body["click"] = click
    try:
        urllib.request.urlopen(urllib.request.Request("https://ntfy.sh/", data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"}), timeout=20)
    except Exception as e:
        print("알림 보내기 실패:", type(e).__name__)

if DRY:  # 미리보기 실행 때 열쇠(토큰)가 살아 있는지만 확인 (값은 출력하지 않음)
    import urllib.request
    for name, url in (("INSTAGRAM_ACCESS_TOKEN", "https://graph.facebook.com/v25.0/17841456827059483?fields=username"),
                      ("THREADS_ACCESS_TOKEN", "https://graph.threads.net/v1.0/me?fields=username"),
                      ("JECHEOL_INSTAGRAM_ACCESS_TOKEN", "https://graph.facebook.com/v25.0/17841418119618352?fields=username"),
                      ("JECHEOL_THREADS_ACCESS_TOKEN", "https://graph.threads.net/v1.0/me?fields=username")):
        tok = os.environ.get(name, "")
        try:
            with urllib.request.urlopen(url + "&access_token=" + tok, timeout=30) as r:
                print(f"열쇠 확인 {name}: OK ({json.load(r).get('username')})")
        except Exception as e:
            print(f"열쇠 확인 {name}: 실패 ({type(e).__name__})"); fail += 1

for sp in sorted(glob.glob(os.path.join(ROOT, "jobs", "*", "schedule.json"))):
    d = os.path.dirname(sp); job = os.path.basename(d)
    sch = json.load(open(sp, encoding="utf-8"))
    pp = os.path.join(d, "posted.json")
    posted = lambda: json.load(open(pp, encoding="utf-8")) if os.path.exists(pp) else {}
    for ch, at in sch["times"].items():
        p = posted()
        # 2026-11-14: 답글 링크 글은 답글까지 올라가야 끝 (본문만 올라가고 답글이 실패하면 다음 실행 때 답글만 다시)
        need_reply = ch == "threads" and bool(json.load(open(os.path.join(d, "post.json"), encoding="utf-8")).get("threads", {}).get("reply"))
        if (ch in p and not (need_reply and "threads_reply" not in p)) or f"{ch}_missed" in p: continue
        t = datetime.datetime.fromisoformat(at)
        if t > now and not DRY: continue
        if now - t > LATE and not DRY:
            p[f"{ch}_missed"] = at; json.dump(p, open(pp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"[{job}] {ch} 예약 시간 {at}에서 6시간 넘게 지나 건너뜀"); fail += 1
            notify(f"⚠️ {NAMES.get(ch, ch)} 놓침 ({job})", "예약 시간에서 6시간 넘게 지나 올리지 않았어요.", tags="warning", prio=4); continue
        print(f"\n=== [{job}] {ch} ({at}) {'미리보기' if DRY else '게시'}")
        cmd = [sys.executable, "-I", os.path.join(ROOT, "scripts", "post.py"), d,
               "--base-url", f"{BASE}/jobs/{job}", "--only", ch] + ([] if DRY else ["--publish"])
        ok = subprocess.run(cmd).returncode == 0
        if not ok: fail += 1
        if not DRY:
            link = posted().get(ch)
            if ok and link: notify(f"{NAMES.get(ch, ch)} 게시 완료 ({job})", f"올라갔어요: {link}", click=link)
            else: notify(f"❌ {NAMES.get(ch, ch)} 게시 실패 ({job})", "GitHub 실행 기록을 확인해 주세요. 다음 실행 때 다시 시도해요.", tags="x", prio=5)
    p = posted()
    if not DRY and all(ch in p or f"{ch}_missed" in p for ch in sch["times"]) and not ("threads" in p and "threads_reply" not in p and json.load(open(os.path.join(d, "post.json"), encoding="utf-8")).get("threads", {}).get("reply")):
        for m in sch.get("media", []):
            f = os.path.join(d, m)
            if os.path.exists(f): os.remove(f); print(f"[{job}] 게시 끝, 파일 정리: {m}")

if DRY and os.environ.get("NTFY_TEST") == "true":
    notify("리뷰한장 알림 시험", "이 알림이 보이면 설정 완료예요. 앞으로 게시가 끝날 때마다 여기로 알려 드려요.", tags="bell")
sys.exit(1 if fail else 0)   # 실패가 있으면 GitHub가 실패 표시(메일 알림)
