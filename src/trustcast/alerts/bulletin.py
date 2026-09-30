"""Deterministic impact bulletins (English and Hindi) with number validation.

Template-first: every sentence is a fixed template filled from the district payload. No language
model is used. ``validate`` extracts every number from the generated text and checks that it matches
a number in the payload-derived ``numbers`` dict (as formatted), so a bulletin can never state a
number the system did not produce. An optional LLM polish step is intentionally not implemented; if
added it must pass the same validation.
"""

from __future__ import annotations

import re

from trustcast import DISCLAIMER
from trustcast.blend.explain import SOURCE_LABELS

DISCLAIMER_HI = "निर्णय-सहायता उपकरण। यह आधिकारिक चेतावनी नहीं है।"
REGIME_HI = {
    "monsoon_active": "सक्रिय मानसून",
    "monsoon_break": "मानसून विराम",
    "monsoon_normal": "सामान्य मानसून",
    "heavy_rain_risk": "भारी वर्षा का जोखिम",
    "dry": "शुष्क",
    "wet_spell": "वर्षा का दौर",
    "heat": "लू / अत्यधिक गर्मी",
}
_NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def _level_en(p: float | None) -> str:
    if p is None:
        return "not available"
    return "high" if p >= 0.6 else "moderate" if p >= 0.3 else "low"


def _level_hi(p: float | None) -> str:
    if p is None:
        return "उपलब्ध नहीं"
    return "अधिक" if p >= 0.6 else "मध्यम" if p >= 0.3 else "कम"


def bulletin_numbers(d: dict, variable: str) -> dict[str, float]:
    """The numbers a bulletin may state, rounded exactly as printed."""
    nums: dict[str, float] = {}
    for ld in d["leads"][:3]:
        k = ld["lead_day"]
        nums[f"day{k}"] = float(k)
        if ld["value"] is not None:
            nums[f"value{k}"] = round(ld["value"], 1)
        if ld.get("lo90") is not None and ld.get("hi90") is not None:
            nums[f"lo{k}"], nums[f"hi{k}"] = round(ld["lo90"], 1), round(ld["hi90"], 1)
        key = "64.5" if variable == "precip" else "40.0"
        p = ld["probabilities"].get(key)
        if p is not None:
            nums[f"p{k}"] = float(round(100 * p))
        top = max(ld["weights"].items(), key=lambda kv: kv[1])
        nums[f"w{k}"] = float(round(100 * top[1]))
    nums["threshold"] = 64.5 if variable == "precip" else 40.0
    nums["ninety"] = 90.0
    return nums


def render(d: dict, variable: str, lang: str, override: dict | None = None) -> str:
    """Bulletin text for a district payload (see products.district_summaries)."""
    unit = "mm" if variable == "precip" else "°C"
    lines = []
    name = f"{d['district']} ({d['state']})"
    if lang == "en":
        what = "rainfall" if variable == "precip" else "maximum temperature"
        event = "heavy rain (>= 64.5 mm)" if variable == "precip" else "temperature >= 40.0 °C"
        lines.append(f"TRUSTCAST district outlook: {name}.")
        for ld in d["leads"][:3]:
            if ld["value"] is None:
                lines.append(f"Day {ld['lead_day']} ({ld['valid_day']}): no forecast available.")
                continue
            key = "64.5" if variable == "precip" else "40.0"
            p = ld["probabilities"].get(key)
            top = max(ld["weights"].items(), key=lambda kv: kv[1])
            s = f"Day {ld['lead_day']} ({ld['valid_day']}): expected {what} {ld['value']:.1f} {unit}"
            if ld.get("lo90") is not None and ld.get("hi90") is not None:
                s += f" (90 % range {ld['lo90']:.1f} to {ld['hi90']:.1f} {unit})"
            s += "."
            if p is not None:
                s += f" Chance of {event}: {round(100 * p):d} % ({_level_en(p)})."
            s += f" Most trusted model: {SOURCE_LABELS.get(top[0], top[0])} ({round(100 * top[1]):d} %)."
            if ld["defer"]:
                s += " Low confidence: forecaster review advised."
            lines.append(s)
        if override:
            lines.append(f"Forecaster override on {override['valid_day']}: {override['reason']}")
        lines.append(DISCLAIMER)
    else:
        what = "वर्षा" if variable == "precip" else "अधिकतम तापमान"
        event = (
            "भारी वर्षा (64.5 मिमी या अधिक)" if variable == "precip" else "तापमान 40.0 °C या अधिक"
        )
        unit_hi = "मिमी" if variable == "precip" else "°C"
        lines.append(f"TRUSTCAST ज़िला पूर्वानुमान: {name}।")
        for ld in d["leads"][:3]:
            if ld["value"] is None:
                lines.append(f"दिन {ld['lead_day']} ({ld['valid_day']}): पूर्वानुमान उपलब्ध नहीं।")
                continue
            key = "64.5" if variable == "precip" else "40.0"
            p = ld["probabilities"].get(key)
            top = max(ld["weights"].items(), key=lambda kv: kv[1])
            s = f"दिन {ld['lead_day']} ({ld['valid_day']}): अनुमानित {what} {ld['value']:.1f} {unit_hi}"
            if ld.get("lo90") is not None and ld.get("hi90") is not None:
                s += f" (90 % सीमा {ld['lo90']:.1f} से {ld['hi90']:.1f} {unit_hi})"
            s += "।"
            if p is not None:
                s += f" {event} की संभावना: {round(100 * p):d} % ({_level_hi(p)})।"
            s += f" सबसे भरोसेमंद मॉडल: {SOURCE_LABELS.get(top[0], top[0])} ({round(100 * top[1]):d} %)।"
            if ld["defer"]:
                s += " कम विश्वसनीयता: पूर्वानुमानकर्ता समीक्षा आवश्यक।"
            lines.append(s)
        if override:
            lines.append(f"पूर्वानुमानकर्ता संशोधन ({override['valid_day']}): {override['reason']}")
        lines.append(DISCLAIMER_HI)
    return "\n".join(lines)


def validate(text: str, numbers: dict[str, float], ignore: tuple[str, ...] = ()) -> list[str]:
    """Numbers in ``text`` that do not appear in ``numbers`` (dates and model names excluded)."""
    allowed = {round(v, 1) for v in numbers.values()}
    cleaned = re.sub(r"\d{4}-\d{2}-\d{2}", " ", text)  # ISO dates
    for label in SOURCE_LABELS.values():
        cleaned = cleaned.replace(label, " ")
    for token in ignore:
        cleaned = cleaned.replace(token, " ")
    errors = []
    for m in _NUM.finditer(cleaned):
        if round(float(m.group()), 1) not in allowed:
            errors.append(m.group())
    return errors
