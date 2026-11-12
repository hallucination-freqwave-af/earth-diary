"""一日一回、二段階で動く。

  python -m earth_diary.main write   # 夜7時：データ → 気分 → 日記 → 映像 → 保存（投稿はしない）
  python -m earth_diary.main post    # 又七が承認したら：保存した日記をXに投稿

書く段階は、投稿する中身を outbox/post.json に置く。投稿の段階はそれを読むだけ。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

from .fetch import collect
from .mood import decide, raw_mood
from .video import CREDIT_EARTH, CREDIT_SUN, make_video
from .write import compose, is_grave, verdict_lines, write_diary

ROOT = Path(__file__).resolve().parent.parent
TAG = "#EarthDiary"  # 目次としてのタグ。押すと過去の日記が並ぶ
OUTBOX = ROOT / "outbox"
JST = dt.timezone(dt.timedelta(hours=9))


def load_history() -> list[dict]:
    p = ROOT / "data" / "history.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def save_history(history: list[dict]) -> None:
    (ROOT / "data" / "history.json").write_text(
        json.dumps(history[-400:], ensure_ascii=False, indent=1), encoding="utf-8")


def recent_diaries(before: str, days: int = 3) -> list[str]:
    """before の日より前の日記から、関西弁の本文だけを古い順に取り出す。"""
    files = sorted(p for p in (ROOT / "diary").glob("*.md") if p.stem < before)[-days:]
    out = []
    for p in files:
        blocks = p.read_text(encoding="utf-8").split("\n\n")[1:]  # 1段目は見出し
        ja = []
        for b in blocks:  # 英語（ASCIIで始まる段）か判定欄が来たら関西弁はおしまい
            if not b.strip() or b.lstrip()[0].isascii() or b.startswith("──"):
                break
            ja.append(b)
        if ja:
            out.append("\n\n".join(ja))
    return out


def write(now: dt.datetime | None = None, data: dict | None = None, **video_kwargs) -> dict:
    """夜7時に、今日一日（直近24時間）の日記を書く。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(JST).date()
    weekday = "月火水木金土日"[today.weekday()]
    label = f"{today.year}年{today.month}月{today.day}日（{weekday}）"
    stamp = today.isoformat()

    data = data or collect(now)
    history = [h for h in load_history() if h.get("date") != stamp]
    mood = decide(data, history)
    diary = write_diary(data, mood, recent_diaries(stamp))
    # 人に被害が出たかもしれない日は、気分の判定を出さず、太陽も割り込ませない
    grave = is_grave(data)
    shown = "静かに（被害の恐れのある地震）" if grave else mood
    text = compose(label, diary, data, shown)

    OUTBOX.mkdir(exist_ok=True)
    video_mood = "達観" if grave else mood
    video = make_video(video_mood, OUTBOX / "video.mp4", now=now, **video_kwargs)
    credits = CREDIT_EARTH + (" / " + CREDIT_SUN if video and video_mood in ("正直", "うるさい") else "")
    if video:
        text += f"\n映像：{credits}"

    # 保存（リポジトリが日記の保管庫）
    (ROOT / "diary" / f"{stamp}.md").write_text(text + "\n", encoding="utf-8")
    (ROOT / "data" / f"{stamp}.json").write_text(
        json.dumps({"mood": mood, **data}, ensure_ascii=False, indent=1), encoding="utf-8")
    history.append({"date": stamp, "mood": mood, "raw": raw_mood(data)})
    save_history(history)

    # 投稿の段階に渡す中身
    parts = [f"地球日記 {label}\n\n{diary['ja']}", diary["en"], verdict_lines(data, shown) + f"\n\n{TAG}"]
    payload = {"date": stamp, "text": f"{text}\n\n{TAG}", "parts": parts, "video": "video.mp4" if video else None,
               "grave": grave}
    (OUTBOX / "post.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    # 承認のメール（Issue）の中身。メールの中で全文が読めるように
    warn = "⚠️ 被害の恐れのある地震がある日です。言葉を確かめてから返信してください。\n\n" if grave else ""
    (OUTBOX / "issue_title.txt").write_text(f"地球日記 {label}", encoding="utf-8")
    (OUTBOX / "issue.md").write_text(
        f"{warn}{text}\n\n動画：{'あり' if video else 'なし（文字だけで投稿）'}\n\n"
        "---\nこのメールに **ok** とだけ返信したら、Xに投稿します。返信しなければ投稿しません。\n",
        encoding="utf-8")

    # 承認画面で読めるように、Actionsのまとめ欄にも書く
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        head = "⚠️ 被害の恐れのある地震がある日です。言葉を確かめてから承認してください。\n\n" if grave else ""
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"{head}```\n{text}\n```\n\n動画：{'あり（Artifactsの earth-diary から見られます）' if video else 'なし（文字だけで投稿）'}\n")
    print(text)
    return payload


def post_outbox() -> list[str]:
    from .post import post

    payload = json.loads((OUTBOX / "post.json").read_text(encoding="utf-8"))
    video = OUTBOX / payload["video"] if payload.get("video") else None
    ids = post(payload["text"], payload["parts"], video)
    print(f"[post] {ids}")
    return ids


OK_WORDS = {"ok", "okay", "おk", "おけ", "おっけー", "おっけい", "承認", "はい", "👍"}


def is_ok(comment: str) -> bool:
    """返信の一行目が ok かどうか。メールの引用（> で始まる行）や署名は見ない。"""
    for line in comment.splitlines():
        line = line.strip()
        if not line or line.startswith(">"):
            continue
        return line.strip("。.!！ ").lower() in OK_WORDS
    return False


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "write"
    if stage == "post":
        post_outbox()
    elif stage == "ok":  # 返事が ok なら ok=true を出す
        ok = is_ok(os.environ.get("COMMENT", ""))
        print(f"ok={'true' if ok else 'false'}")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
                fh.write(f"ok={'true' if ok else 'false'}\n")
    else:
        write()
