"""地球の今日一日のデータを集める。

取れなかった項目は None のまま返す。日記の側で「測られへんかった」と書けばええ。
"""
from __future__ import annotations

import datetime as dt
import requests

from .moon import moon_phase

UA = {"User-Agent": "earth-diary (https://github.com/) daily bot"}
TIMEOUT = 30

USGS_DAY = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
SWPC_KP = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
SWPC_FLARES = "https://services.swpc.noaa.gov/json/goes/primary/xray-flares-7-day.json"
SWPC_WIND = "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json"


def _get(url):
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _parse_time(s: str) -> dt.datetime:
    s = s.replace("Z", "").replace("T", " ")
    s = s.split(".")[0]
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)


# ---------- 地震 ----------
def is_grave_quake(e: dict) -> bool:
    """人に被害が出ているかもしれない地震。迷ったら静かな方に倒す。

    USGSの被害推定（PAGER）は後から付くことがあるので、
    推定がまだない時のために地震そのものの情報でも先回りする。
    """
    if e.get("alert") in ("yellow", "orange", "red"):
        return True
    if e["mag"] >= 7.0:
        return True
    depth = e.get("depth")
    if e["mag"] >= 6.0 and depth is not None and depth <= 70:
        return True
    if (e.get("mmi") or 0) >= 6 or (e.get("cdi") or 0) >= 6:   # 震度でいうとおおむね5強以上
        return True
    if (e.get("felt") or 0) >= 1000:                            # 揺れを感じた報告が多い
        return True
    if e.get("tsunami") == 1 and e["mag"] >= 6.0:
        return True
    return False


def summarize_quakes(geojson: dict) -> dict:
    feats = geojson.get("features", [])
    mags = []
    events = []
    for f in feats:
        p = f.get("properties", {})
        m = p.get("mag")
        if m is None:
            continue
        mags.append(m)
        coords = (f.get("geometry") or {}).get("coordinates") or [None, None, None]
        events.append({"mag": round(m, 1), "place": p.get("place") or "", "time": p.get("time"),
                       "alert": p.get("alert"), "depth": coords[2] if len(coords) > 2 else None,
                       "mmi": p.get("mmi"), "cdi": p.get("cdi"), "felt": p.get("felt"),
                       "tsunami": p.get("tsunami")})
    events.sort(key=lambda e: e["mag"], reverse=True)
    near_japan = [e for e in events if "Japan" in e["place"] and e["mag"] >= 4.0]
    grave = [e for e in events if is_grave_quake(e)]
    return {
        "grave": grave[:3],
        "count": len(mags),
        "m5_count": sum(1 for m in mags if m >= 5.0),
        "max_mag": max(mags) if mags else None,
        "top": events[:3],
        "near_japan": near_japan[:3],
    }


def fetch_quakes():
    return summarize_quakes(_get(USGS_DAY))


# ---------- 太陽フレア ----------
FLARE_ORDER = {"A": 0, "B": 1, "C": 2, "M": 3, "X": 4}


def flare_value(cls: str | None) -> float:
    """'M2.3' -> 3.23 のように比べやすい数にする。"""
    if not cls:
        return -1
    letter = cls[0].upper()
    try:
        num = float(cls[1:])
    except ValueError:
        num = 1.0
    return FLARE_ORDER.get(letter, -1) + min(num, 9.9) / 10


def summarize_flares(items: list, now: dt.datetime) -> dict:
    since = now - dt.timedelta(hours=24)
    recent = []
    for it in items:
        cls = it.get("max_class") or it.get("current_class")
        t = it.get("max_time") or it.get("begin_time")
        if not cls or not t:
            continue
        try:
            if _parse_time(t) >= since:
                recent.append(cls)
        except ValueError:
            continue
    biggest = max(recent, key=flare_value) if recent else None
    return {"count": len(recent), "max_class": biggest}


def fetch_flares(now):
    return summarize_flares(_get(SWPC_FLARES), now)


# ---------- 地磁気 Kp ----------
def summarize_kp(rows, now: dt.datetime) -> dict:
    """配列形式（先頭が見出し行）とオブジェクト形式の両方を受ける。"""
    since = now - dt.timedelta(hours=24)
    vals = []
    for row in rows:
        if isinstance(row, dict):
            t, kp = row.get("time_tag"), row.get("Kp", row.get("kp_index"))
        else:
            if row and row[0] == "time_tag":
                continue
            t, kp = row[0], row[1]
        try:
            if _parse_time(t) >= since:
                vals.append(float(kp))
        except (TypeError, ValueError):
            continue
    return {"kp_max": max(vals) if vals else None}


def fetch_kp(now):
    return summarize_kp(_get(SWPC_KP), now)


# ---------- 太陽風 ----------
def summarize_wind(rows) -> dict:
    speeds = []
    for row in rows:
        if not row or row[0] == "time_tag":
            continue
        try:
            speeds.append(float(row[2]))
        except (TypeError, ValueError, IndexError):
            continue
    return {"wind_max": round(max(speeds)) if speeds else None}


def fetch_wind():
    return summarize_wind(_get(SWPC_WIND))


# ---------- まとめ ----------
def collect(now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    data = {"utc": now.strftime("%Y-%m-%d %H:%M"), "errors": []}
    steps = {
        "quakes": fetch_quakes,
        "flares": lambda: fetch_flares(now),
        "kp": lambda: fetch_kp(now),
        "wind": fetch_wind,
    }
    for key, fn in steps.items():
        try:
            data[key] = fn()
        except Exception as e:  # 取れんかった日は取れんかったと記録する
            data[key] = None
            data["errors"].append(f"{key}: {e}")
    data["moon"] = moon_phase(now)
    return data
