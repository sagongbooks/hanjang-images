"""리뷰한장 게시 프로그램 (인스타그램 캐러셀 + 스레드).

사용법:
  python3 -I tools/post.py <콘텐츠폴더> --base-url <이미지 공개 주소>           # 미리보기만 (기본)
  python3 -I tools/post.py <콘텐츠폴더> --base-url <이미지 공개 주소> --publish # 실제 게시

안전장치:
  - --publish 없이는 아무것도 올리지 않는다 (미리보기만).
  - --publish여도 콘텐츠 폴더에 승인.txt(사용자 "올려" 기록)가 없으면 멈춘다.
  - 모든 글의 첫 줄이 수수료 고지인지 확인하고, 아니면 멈춘다.
  - 이미 올린 채널은 posted.json에 남겨 두고 다시 올리지 않는다.
  - 토큰은 .env에서만 읽고 화면에 출력하지 않는다.

콘텐츠 폴더의 post.json 형식:
  {"instagram": {"images": ["card_1.jpg", ...], "caption": "..."},
   "threads":   {"images": ["card_1.jpg", ...], "text": "...", "topic": "스킨케어"}}
  일상글(스레드 글만, 링크·홍보 없음): {"channel": "jecheol", "threads": {"kind": "daily", "text": "...", "topic": "살림"}}
  릴스(영상): {"instagram": {"video": "reel.mp4", "caption": "...", "thumb_offset": 2600},
              "threads":   {"video": "reel.mp4", "text": "...", "topic": "스킨케어"}}
"""
import argparse, json, os, sys, time, urllib.parse, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 채널별 계정 (post.json의 "channel" 값, 없으면 hanjang)
CHANNELS = {
    "hanjang": {"name": "리뷰한장", "ig_id": "17841456827059483", "ig_tok": "INSTAGRAM_ACCESS_TOKEN", "th_tok": "THREADS_ACCESS_TOKEN"},
    "jecheol": {"name": "제철템상점", "ig_id": "17841418119618352", "ig_tok": "JECHEOL_INSTAGRAM_ACCESS_TOKEN", "th_tok": "JECHEOL_THREADS_ACCESS_TOKEN"},
}
TOKEN_NAMES = [v for c in CHANNELS.values() for v in (c["ig_tok"], c["th_tok"])]
IG_API = "https://graph.facebook.com/v25.0"
TH_API = "https://graph.threads.net/v1.0"
DISCLOSURE_WORDS = ("쿠팡 파트너스", "수수료")


def load_env():
    env = {}
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):  # GitHub 자동 실행: 비밀 보관함(Secrets)이 환경 변수로 들어온다
        return {k: os.environ[k] for k in TOKEN_NAMES if os.environ.get(k)}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def call(method, url, params, token):
    params = dict(params, access_token=token)
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        req = urllib.request.Request(url + "?" + data.decode())
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"API 오류 {e.code}: {body[:500]}")


def wait_ready(api, cid, token, field, tries=30):
    for _ in range(tries):
        r = call("GET", f"{api}/{cid}", {"fields": field}, token)
        st = r.get(field)
        if st in ("FINISHED", "PUBLISHED"):
            return
        if st in ("ERROR", "EXPIRED"):
            raise SystemExit(f"컨테이너 {cid} 상태 {st}: {r}")
        time.sleep(3)
    raise SystemExit(f"컨테이너 {cid} 준비 시간 초과")


def th_media_any(th):
    return bool(th.get("images") or th.get("image") or th.get("video"))


def check_first_line(name, text):
    first = text.strip().splitlines()[0]
    if not all(w in first for w in DISCLOSURE_WORDS):
        raise SystemExit(f"{name}: 첫 줄에 수수료 고지가 없어요 → '{first}'")


def check_url(url):
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            ct = r.headers.get("Content-Type", "")
            return r.status == 200 and ct.startswith(("image/", "video/")), ct
    except Exception as e:
        return False, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--base-url", required=True, help="이미지가 공개된 주소 (끝에 / 없이)")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--only", choices=["instagram", "threads"])
    a = ap.parse_args()

    folder = os.path.abspath(a.folder)
    post = json.load(open(os.path.join(folder, "post.json"), encoding="utf-8"))
    chan = post.get("channel", "hanjang")
    if chan not in CHANNELS: raise SystemExit(f"모르는 채널이에요: {chan}")
    C = CHANNELS[chan]; IG_ID = C["ig_id"]
    print(f"  채널: {C['name']} ({chan})")
    done_path = os.path.join(folder, "posted.json")
    done = json.load(open(done_path)) if os.path.exists(done_path) else {}
    base = a.base_url.rstrip("/")
    q = lambda name: base + "/" + urllib.parse.quote(name)

    ig, th = post.get("instagram"), post.get("threads")
    channels = [c for c in ("instagram", "threads") if post.get(c) and (a.only in (None, c))]

    # 1) 검사
    if ig: check_first_line("인스타그램", ig["caption"])
    # 일상글(kind=daily, 2026-11-11 사용자 결정): 링크·상품 홍보가 없는 스레드 글만 허용, 그때만 수수료 고지 생략
    if th and th.get("kind") == "daily":
        if ig or th_media_any(th): raise SystemExit("일상글은 스레드 글(텍스트)만 올려요")
        low = th["text"].lower()
        if any(k in low for k in ("http", "link.", "coupang", "쿠팡", "구매", "링크", "할인", "최저가")):
            raise SystemExit("일상글에 링크·구매 유도 말이 있어요. 홍보 글이면 수수료 고지를 넣은 쇼핑글로 올려야 해요")
        print("  일상글: 링크·홍보 없음 확인 (수수료 고지 생략)")
    elif th: check_first_line("스레드", th["text"])
    if ig and not ig.get("video") and not (2 <= len(ig["images"]) <= 10):
        raise SystemExit("인스타 캐러셀은 이미지 2~10장이어야 해요")
    if ig and len(ig["caption"]) > 2200: raise SystemExit("인스타 캡션이 2,200자를 넘어요")
    if th and len(th["text"]) > 500: raise SystemExit("스레드 글이 500자를 넘어요")
    th_imgs = (th.get("images") or ([th["image"]] if th.get("image") else [])) if th else []
    if len(th_imgs) > 20: raise SystemExit("스레드 캐러셀은 20장까지예요")
    # 2026-11-11 사용자 규칙: 카드 글은 스레드도 인스타와 같은 장수·순서로 올린다 (일부만 올리면 "덜 올라갔다"로 보임)
    if ig and th and ig.get("images") and th_imgs and th_imgs != ig["images"]:
        raise SystemExit(f"스레드 카드({len(th_imgs)}장)가 인스타 카드({len(ig['images'])}장)와 달라요. 같은 카드를 모두 올려야 해요.")
    if th and th.get("topic") and any(c in th["topic"] for c in ".&"):
        raise SystemExit("스레드 주제 태그에는 . 과 & 를 쓸 수 없어요")
    if th: print(f"  스레드 주제 태그: {th.get('topic') or '없음 (노출이 줄 수 있어요)'}")
    names = ((([ig["video"]] if ig.get("video") else ig["images"])) if ig else []) + th_imgs + ([th["video"]] if th and th.get("video") else [])
    bad = []
    for n in dict.fromkeys(names):
        ok, info = check_url(q(n))
        print(f"  이미지 {'OK ' if ok else '실패'} {q(n)} ({info})")
        if not ok: bad.append(n)
    if bad: raise SystemExit("공개 주소에서 열리지 않는 이미지가 있어요. 게시하지 않아요.")

    for c in channels:
        print(f"\n[{c}] {'이미 게시됨: ' + done[c] if c in done else '게시 예정'}")
    if not a.publish:
        print("\n미리보기만 했어요. 실제 게시는 --publish (승인.txt 필요).")
        return

    # 2) 승인 확인
    appr = os.path.join(folder, "승인.txt")
    if not os.path.exists(appr) or "올려" not in open(appr, encoding="utf-8").read():
        raise SystemExit("승인.txt가 없어서 게시하지 않아요 (절대 규칙 1).")

    env = load_env()

    # 3) 인스타그램 (캐러셀 또는 릴스)
    if "instagram" in channels and "instagram" not in done:
        tok = env[C["ig_tok"]]
        if ig.get("video"):  # 릴스
            prm = {"media_type": "REELS", "video_url": q(ig["video"]), "caption": ig["caption"], "share_to_feed": "true"}
            if ig.get("thumb_offset"): prm["thumb_offset"] = str(ig["thumb_offset"])
            r = call("POST", f"{IG_API}/{IG_ID}/media", prm, tok)
            wait_ready(IG_API, r["id"], tok, "status_code", tries=100)
        else:
            kids = []
            for n in ig["images"]:
                r = call("POST", f"{IG_API}/{IG_ID}/media", {"image_url": q(n), "is_carousel_item": "true"}, tok)
                kids.append(r["id"])
            for k in kids: wait_ready(IG_API, k, tok, "status_code")
            r = call("POST", f"{IG_API}/{IG_ID}/media",
                     {"media_type": "CAROUSEL", "children": ",".join(kids), "caption": ig["caption"]}, tok)
            wait_ready(IG_API, r["id"], tok, "status_code")
        pub = call("POST", f"{IG_API}/{IG_ID}/media_publish", {"creation_id": r["id"]}, tok)
        link = call("GET", f"{IG_API}/{pub['id']}", {"fields": "permalink"}, tok).get("permalink", pub["id"])
        done["instagram"] = link
        json.dump(done, open(done_path, "w"), ensure_ascii=False, indent=1)
        print("인스타그램 게시 완료:", link)

    # 4) 스레드
    if "threads" in channels and "threads" not in done:
        tok = env[C["th_tok"]]
        p = {"text": th["text"]}
        if th.get("topic"): p["topic_tag"] = th["topic"]  # 주제 태그 1개 (노출 경로)
        if len(th_imgs) >= 2:  # 여러 장이면 캐러셀
            kids = [call("POST", f"{TH_API}/me/threads",
                         {"media_type": "IMAGE", "image_url": q(n), "is_carousel_item": "true"}, tok)["id"]
                    for n in th_imgs]
            for k in kids: wait_ready(TH_API, k, tok, "status")
            p.update(media_type="CAROUSEL", children=",".join(kids))
        elif th.get("video"): p.update(media_type="VIDEO", video_url=q(th["video"]))
        elif th_imgs: p.update(media_type="IMAGE", image_url=q(th_imgs[0]))
        else: p["media_type"] = "TEXT"
        r = call("POST", f"{TH_API}/me/threads", p, tok)
        wait_ready(TH_API, r["id"], tok, "status", tries=100)
        pub = call("POST", f"{TH_API}/me/threads_publish", {"creation_id": r["id"]}, tok)
        link = call("GET", f"{TH_API}/{pub['id']}", {"fields": "permalink"}, tok).get("permalink", pub["id"])
        done["threads"] = link
        json.dump(done, open(done_path, "w"), ensure_ascii=False, indent=1)
        print("스레드 게시 완료:", link)


if __name__ == "__main__":
    main()
