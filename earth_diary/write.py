"""データと気分から、地球の日記を書く。"""
from __future__ import annotations

import json
import os
import random
import re
from pathlib import Path

from .mood import MOOD_EN

PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "earth.md"
MODEL = os.environ.get("EARTH_MODEL", "claude-sonnet-5-5")


HUMAN_STANCES = [("無視", 5), ("皮膚の上", 3), ("文句", 2)]


def human_stance(mood: str, seed: str) -> str:
    """人間との距離を日ごとにシャッフル。悟った日は人間を見ない。"""
    if mood == "悟った":
        return "無視"
    if mood == "被害の恐れ":
        return "皮膚の上"
    rng = random.Random(seed)
    names, weights = zip(*HUMAN_STANCES)
    return rng.choices(names, weights=weights)[0]


def facts_for_prompt(data: dict, mood: str, stance: str = "無視") -> str:
    q, f, k, w, m = (data.get(x) for x in ("quakes", "flares", "kp", "wind", "moon"))
    lines = [f"気分: {mood}", f"人間との距離: {stance}"]
    if q:
        lines.append(f"地震: {q['count']}回 / M5以上 {q['m5_count']}回 / 最大 M{q['max_mag']}")
        for e in q["top"]:
            lines.append(f"  - M{e['mag']} {e['place']}")
        for e in q["near_japan"]:
            lines.append(f"  - 日本の近く: M{e['mag']} {e['place']}")
    else:
        lines.append("地震: 測れんかった")
    # フレアとKpは記号を渡さず、強さの言葉にして渡す（本文で地震のMと混ざらないように）
    if f and f["max_class"]:
        size = {"X": "大きい", "M": "中くらい", "C": "小さい"}.get(f["max_class"][0].upper(), "ごく小さい")
        lines.append(f"太陽フレア: いちばん強いのが{size}（{f['count']}回）")
    else:
        lines.append("太陽フレア: 目立つものなし" if f else "太陽フレア: 測れんかった")
    if k and k["kp_max"] is not None:
        kp = k["kp_max"]
        level = "激しい嵐" if kp >= 7 else "嵐" if kp >= 5 else "ややざわつく" if kp >= 4 else "静か"
        lines.append(f"地磁気: {level}")
    else:
        lines.append("地磁気: 測れんかった")
    lines.append(f"太陽風: 最大 秒速{w['wind_max']}km" if w and w["wind_max"] else "太陽風: 測れんかった")
    co2, ice, hz = data.get("co2"), data.get("seaice"), data.get("hazards")
    if co2 and co2.get("ppm"):
        yc = co2.get("year_change")
        lines.append(f"息（CO2）: {co2['ppm']}ppm" + (f"、一年前より {yc:+}ppm" if yc is not None else ""))
    if ice:
        for pole, ja in (("north", "北極"), ("south", "南極")):
            e = ice.get(pole) or {}
            if e.get("extent"):
                bits = [f"{e['extent']}百万km²"]
                if e.get("change_5d") is not None:
                    bits.append(f"5日で {e['change_5d']:+}")
                if e.get("vs_normal") is not None:
                    bits.append(f"昔の平年より {e['vs_normal']:+}")
                lines.append(f"海氷（{ja}）: " + "、".join(bits))
    if hz is not None:
        if hz.get("events"):
            lines.append(f"ほかの出来事: {hz['count']}件")
            for e in hz["events"]:
                where = e["country"] or e["name"]
                lines.append(f"  - {e['kind_ja']} {where}（警報 {e['alert'] or '不明'}）{e['severity']}")
        else:
            lines.append("ほかの出来事: なし")
    if m:
        lines.append(f"月: {m['ja']}（月齢{m['age']}）")
    return "\n".join(lines)


def _template(mood: str) -> dict:
    """APIキーなしで動かす時の仮の日記（テスト用）。"""
    return {"ja": f"（テスト）今日の気分は{mood}。", "en": f"(test) Today I felt {MOOD_EN.get(mood, mood)}."}


def grave_list(data: dict) -> list[str]:
    """人に被害が出たかもしれない出来事（地震・台風・洪水など）。"""
    out = [f"地震 M{e['mag']} {e['place']}" for e in (data.get("quakes") or {}).get("grave") or []]
    out += [f"{e['kind_ja']} {e['country'] or e['name']}" for e in (data.get("hazards") or {}).get("grave") or []]
    return out


def is_grave(data: dict) -> bool:
    return bool(grave_list(data))


def _region(place: str) -> str:
    return place.split(",")[-1].strip().removesuffix(" region").strip().lower()


def same_as_yesterday(data: dict, prev: dict | None) -> bool:
    """昨日とほぼ同じ一日か。気分・揺れた場所・強さ・太陽のざわつきが揃っていたら同じとみなす。"""
    from .mood import raw_mood
    if not prev or is_grave(data):
        return False
    q, pq = data.get("quakes") or {}, prev.get("quakes") or {}
    if not q.get("top") or not pq.get("top"):
        return False
    if raw_mood(data) != raw_mood(prev):
        return False
    regions = [_region(e["place"]) for e in q["top"][:3]]
    pregions = [_region(e["place"]) for e in pq["top"][:3]]
    places_alike = regions[0] == pregions[0] or len(set(regions) & set(pregions)) >= 2
    mag_alike = abs((q.get("max_mag") or 0) - (pq.get("max_mag") or 0)) < 0.6
    m5_alike = abs((q.get("m5_count") or 0) - (pq.get("m5_count") or 0)) <= 2
    kp, pkp = (data.get("kp") or {}).get("kp_max") or 0, (prev.get("kp") or {}).get("kp_max") or 0
    return places_alike and mag_alike and m5_alike and (kp >= 4) == (pkp >= 4)


def recent_for_prompt(recent: list[str]) -> str:
    """直近の日記（関西弁の本文）を、書き手に見せる形にする。古い順。"""
    if not recent:
        return ""
    blocks = [f"[{i}日前]\n{t.strip()}" for i, t in zip(range(len(recent), 0, -1), recent)]
    return ("\n\nここ数日、自分が書いた日記（これと同じ言い回し・比喩・締めは使わない）:\n"
            + "\n\n".join(blocks))


def write_diary(data: dict, mood: str, recent: list[str] | None = None, same: bool = False) -> dict:
    grave = is_grave(data)
    facts = facts_for_prompt(data, mood, human_stance("被害の恐れ" if grave else mood, data.get("utc", "")))
    if same and mood != "悟った":
        facts = "昨日とほぼ同じ: はい\n" + facts
    if grave:
        places = "、".join(grave_list(data))
        facts = "被害の恐れ: あり（" + places + "）\n" + facts
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _template(mood)

    import anthropic

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=3000,
        system=PROMPT.read_text(encoding="utf-8"),
        messages=[{"role": "user",
                   "content": f"今日一日（直近24時間）のデータ:\n{facts}{recent_for_prompt(recent or [])}"}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    return parse_diary(text)


def parse_diary(text: str) -> dict:
    """<ja>…</ja><en>…</en> を取り出す。昔のJSON形式で返ってきても読む。"""
    ja = re.search(r"<ja>(.*?)</ja>", text, re.S)
    en = re.search(r"<en>(.*?)</en>", text, re.S)
    if ja and en:
        return {"ja": ja.group(1).strip(), "en": en.group(1).strip()}
    try:
        body = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        out = json.loads(body, strict=False)  # 文字列の中の生の改行も許す
        return {"ja": out["ja"].strip(), "en": out["en"].strip()}
    except Exception:
        raise ValueError(f"日記の形式が読めんかった:\n{text}")


def verdict_lines(data: dict, mood: str) -> str:
    """投稿の下に付ける判定とデータ。"""
    q, f, k, w = (data.get(x) for x in ("quakes", "flares", "kp", "wind"))
    sun = []
    if f and f["max_class"]:
        sun.append(f"最大フレア {f['max_class']}")
    if k and k["kp_max"] is not None:
        sun.append(f"Kp {k['kp_max']:g}")
    if w and w["wind_max"]:
        sun.append(f"太陽風 {w['wind_max']}km/s")
    quake = f"{q['count']}回／最大M{q['max_mag']} {q['top'][0]['place']}" if q and q["top"] else "測れんかった"
    lines = ["──", f"判定：{mood}", f"太陽：{'／'.join(sun) if sun else '測れんかった'}", f"地震：{quake}"]
    co2, ice, hz = data.get("co2"), data.get("seaice"), data.get("hazards")
    if co2 and co2.get("ppm"):
        lines.append(f"息：CO2 {co2['ppm']}ppm")
    if ice:
        n, s_ = (ice.get("north") or {}).get("extent"), (ice.get("south") or {}).get("extent")
        if n or s_:
            lines.append(f"氷：北 {n}／南 {s_} 百万km²")
    if hz and hz.get("events"):
        lines.append("ほか：" + "、".join(f"{e['kind_ja']}（{e['country'] or e['name']}）" for e in hz["events"][:3]))
    return "\n".join(lines)


def compose(date_label: str, diary: dict, data: dict, mood: str) -> str:
    """関西弁 → 英語 → 判定 の順。"""
    return f"地球日記 {date_label}\n\n{diary['ja']}\n\n{diary['en']}\n\n{verdict_lines(data, mood)}"
