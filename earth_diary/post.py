"""Xに投稿する（公式API・OAuth 1.0a ユーザー認証）。

必要な環境変数:
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET

動画のアップロードに失敗した日は、文字だけで投稿する。
長文が通らなかった日は、スレッド（関西弁→英語→判定）に分けて投稿する。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests
from requests_oauthlib import OAuth1

API = "https://api.x.com/2"
CHUNK = 4 * 1024 * 1024


def _auth() -> OAuth1:
    return OAuth1(os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
                  os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_SECRET"])


def upload_video(path: Path, auth: OAuth1) -> str:
    size = path.stat().st_size
    r = requests.post(f"{API}/media/upload/initialize", auth=auth, timeout=60, json={
        "media_type": "video/mp4", "total_bytes": size, "media_category": "tweet_video"})
    r.raise_for_status()
    media_id = r.json()["data"]["id"]

    with path.open("rb") as fh:
        i = 0
        while chunk := fh.read(CHUNK):
            r = requests.post(f"{API}/media/upload/{media_id}/append", auth=auth, timeout=120,
                              data={"segment_index": i}, files={"media": chunk})
            r.raise_for_status()
            i += 1

    r = requests.post(f"{API}/media/upload/{media_id}/finalize", auth=auth, timeout=60)
    r.raise_for_status()
    info = r.json()["data"].get("processing_info")
    while info and info.get("state") in ("pending", "in_progress"):
        time.sleep(info.get("check_after_secs", 5))
        r = requests.get(f"{API}/media/upload", auth=auth, timeout=60,
                         params={"command": "STATUS", "media_id": media_id})
        r.raise_for_status()
        info = r.json()["data"].get("processing_info")
    if info and info.get("state") == "failed":
        raise RuntimeError(f"video processing failed: {info}")
    return media_id


def _tweet(text: str, auth: OAuth1, media_id: str | None = None, reply_to: str | None = None) -> str:
    body: dict = {"text": text}
    if media_id:
        body["media"] = {"media_ids": [media_id]}
    if reply_to:
        body["reply"] = {"in_reply_to_tweet_id": reply_to}
    r = requests.post(f"{API}/tweets", auth=auth, json=body, timeout=60)
    if r.status_code >= 400:
        raise requests.HTTPError(f"{r.status_code} {r.text}", response=r)
    return r.json()["data"]["id"]


def post(full_text: str, parts: list[str], video: Path | None) -> list[str]:
    """full_text を一つで投稿。無理なら parts をスレッドで。投稿IDを返す。"""
    auth = _auth()
    media_id = None
    if video is not None:
        try:
            media_id = upload_video(video, auth)
        except Exception as e:
            print(f"[post] 動画アップロード失敗、文字だけで続行: {e}")

    try:
        return [_tweet(full_text, auth, media_id)]
    except requests.HTTPError as e:
        print(f"[post] 一つの投稿では通らんかった、スレッドに分ける: {e}")

    ids = []
    for i, part in enumerate(parts):
        ids.append(_tweet(part, auth, media_id if i == 0 else None, ids[-1] if ids else None))
    return ids
