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

for sp in sorted(glob.glob(os.path.join(ROOT, "jobs", "*", "schedule.json"))):
    d = os.path.dirname(sp); job = os.path.basename(d)
    sch = json.load(open(sp, encoding="utf-8"))
    pp = os.path.join(d, "posted.json")
    posted = lambda: json.load(open(pp, encoding="utf-8")) if os.path.exists(pp) else {}
    for ch, at in sch["times"].items():
        p = posted()
        if ch in p or f"{ch}_missed" in p: continue
        t = datetime.datetime.fromisoformat(at)
        if t > now and not DRY: continue
        if now - t > LATE and not DRY:
            p[f"{ch}_missed"] = at; json.dump(p, open(pp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"[{job}] {ch} 예약 시간 {at}에서 6시간 넘게 지나 건너뜀"); fail += 1; continue
        print(f"\n=== [{job}] {ch} ({at}) {'미리보기' if DRY else '게시'}")
        cmd = [sys.executable, "-I", os.path.join(ROOT, "scripts", "post.py"), d,
               "--base-url", f"{BASE}/jobs/{job}", "--only", ch] + ([] if DRY else ["--publish"])
        if subprocess.run(cmd).returncode != 0: fail += 1
    p = posted()
    if not DRY and all(ch in p or f"{ch}_missed" in p for ch in sch["times"]):
        for m in sch.get("media", []):
            f = os.path.join(d, m)
            if os.path.exists(f): os.remove(f); print(f"[{job}] 게시 끝, 파일 정리: {m}")

sys.exit(1 if fail else 0)   # 실패가 있으면 GitHub가 실패 표시(메일 알림)
