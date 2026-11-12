"""その日の気分をデータで決める。

  めっちゃ静か / 達観 / 正直 / うるさい / 悟った

悟った日だけは、めっちゃ静かな日が続いた後にしか来ない。
"""
from __future__ import annotations

from .fetch import flare_value

QUIET, TATSUKAN, SHOJIKI, URUSAI, SATORI = "めっちゃ静か", "達観", "正直", "うるさい", "悟った"
MOOD_EN = {QUIET: "very quiet", TATSUKAN: "detached", SHOJIKI: "honest",
           URUSAI: "noisy", SATORI: "enlightened"}

SATORI_AFTER_QUIET_DAYS = 3   # 静かな日がこれだけ続いた翌日だけ候補になる
SATORI_COOLDOWN_DAYS = 21     # 一度来たらしばらく来ない


def _v(d, *keys):
    for k in keys:
        if d is None:
            return None
        d = d.get(k)
    return d


def raw_mood(data: dict) -> str:
    kp = _v(data, "kp", "kp_max") or 0
    flare = flare_value(_v(data, "flares", "max_class"))
    max_mag = _v(data, "quakes", "max_mag") or 0
    m5 = _v(data, "quakes", "m5_count") or 0
    wind = _v(data, "wind", "wind_max") or 0

    # M5以上の地震は世界全体で一日4〜5回がふつう。それを基準に、多い日だけ反応する
    if kp >= 6 or flare >= 4.0 or max_mag >= 7.0 or wind >= 800 or (kp >= 5 and m5 >= 8):
        return URUSAI
    if kp >= 4 or flare >= 3.5 or max_mag >= 6.0 or m5 >= 10 or wind >= 650:
        return SHOJIKI
    if kp <= 2.34 and flare < 3.0 and max_mag < 5.5 and m5 <= 2:
        return QUIET
    return TATSUKAN


def decide(data: dict, history: list[dict]) -> str:
    """history は古い順の [{"date":..., "mood":..., "raw":...}]。"""
    mood = raw_mood(data)
    if mood != QUIET:
        return mood
    recent_raw = [h.get("raw") for h in history[-SATORI_AFTER_QUIET_DAYS:]]
    recent_moods = [h.get("mood") for h in history[-SATORI_COOLDOWN_DAYS:]]
    if (len(recent_raw) == SATORI_AFTER_QUIET_DAYS
            and all(r == QUIET for r in recent_raw)
            and SATORI not in recent_moods):
        return SATORI
    return QUIET
