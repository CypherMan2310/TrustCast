"""CAP 1.2 export of district alerts (OASIS Common Alerting Protocol).

TRUSTCAST is decision support, not an issuing authority, so every message is ``status=Draft``
(a preliminary product, not actionable as issued), ``scope=Restricted`` to forecaster review, and
the sender is the TRUSTCAST prototype, never IMD or NDMA. The disclaimer is in the description.
"""

from __future__ import annotations

import datetime as dt
import uuid
import xml.etree.ElementTree as ET

from trustcast import DISCLAIMER

NS = "urn:oasis:names:tc:emergency:cap:1.2"
LEVELS = {
    "yellow": ("Moderate", "Possible"),
    "orange": ("Severe", "Likely"),
    "red": ("Extreme", "Likely"),
}
REQUIRED = ("identifier", "sender", "sent", "status", "msgType", "scope")


def alert_level(prob: float | None) -> str:
    """Alert level from event probability (decision-support rule, documented in the API)."""
    if prob is None:
        return "none"
    return (
        "red" if prob >= 0.7 else "orange" if prob >= 0.4 else "yellow" if prob >= 0.2 else "none"
    )


def build_cap(
    district: str,
    state: str,
    event: str,
    level: str,
    prob: float,
    onset: dt.datetime,
    expires: dt.datetime,
    polygon: list[tuple[float, float]] | None,
    headline: str,
    description: str,
) -> str:
    """CAP 1.2 XML string for one district alert."""
    ET.register_namespace("", NS)
    alert = ET.Element(f"{{{NS}}}alert")

    def sub(parent, tag, text):
        e = ET.SubElement(parent, f"{{{NS}}}{tag}")
        e.text = text
        return e

    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    sub(alert, "identifier", f"trustcast-{uuid.uuid4()}")
    sub(alert, "sender", "trustcast-prototype@localhost")
    sub(alert, "sent", now.isoformat())
    sub(alert, "status", "Draft")
    sub(alert, "msgType", "Alert")
    sub(alert, "scope", "Restricted")
    sub(alert, "restriction", "Forecaster review only. " + DISCLAIMER)
    info = ET.SubElement(alert, f"{{{NS}}}info")
    sub(info, "language", "en-IN")
    sub(info, "category", "Met")
    sub(info, "event", event)
    sub(info, "urgency", "Expected")
    severity, certainty = LEVELS.get(level, ("Minor", "Unlikely"))
    sub(info, "severity", severity)
    sub(info, "certainty", certainty)
    sub(info, "onset", onset.replace(microsecond=0).isoformat())
    sub(info, "expires", expires.replace(microsecond=0).isoformat())
    sub(info, "senderName", "TRUSTCAST decision-support prototype (not an official warning)")
    sub(info, "headline", headline)
    sub(info, "description", f"{description} Probability {round(100 * prob):d} %. {DISCLAIMER}")
    param = ET.SubElement(info, f"{{{NS}}}parameter")
    sub(param, "valueName", "TRUSTCAST_level")
    sub(param, "value", level)
    area = ET.SubElement(info, f"{{{NS}}}area")
    sub(area, "areaDesc", f"{district}, {state}")
    if polygon:
        pts = list(polygon)
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        sub(area, "polygon", " ".join(f"{lat:.4f},{lon:.4f}" for lat, lon in pts))
    return ET.tostring(alert, encoding="unicode", xml_declaration=True)


def check_cap(xml_text: str) -> list[str]:
    """Structural checks: well-formed, CAP 1.2 namespace, required elements, Draft status."""
    try:
        root = ET.fromstring(
            xml_text.split("?>", 1)[-1] if xml_text.startswith("<?xml") else xml_text
        )
    except ET.ParseError as e:
        return [f"not well-formed: {e}"]
    problems = []
    if root.tag != f"{{{NS}}}alert":
        problems.append("root is not a CAP 1.2 alert")
    for tag in REQUIRED:
        if root.find(f"{{{NS}}}{tag}") is None:
            problems.append(f"missing {tag}")
    if (root.findtext(f"{{{NS}}}status") or "") != "Draft":
        problems.append("status must be Draft for decision-support output")
    if root.find(f"{{{NS}}}info/{{{NS}}}area/{{{NS}}}areaDesc") is None:
        problems.append("missing info/area/areaDesc")
    return problems
