"""Web-Oberfläche + JSON-API + abonnierbarer iCal-Feed."""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .. import __version__
from ..agent import Agent

STATIC = Path(__file__).parent / "static"


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def create_app(agent: Agent) -> Starlette:
    cfg = agent.config
    venue_meta = {v.id: {"id": v.id, "name": v.name, "city": v.city, "type": v.type, "url": v.url}
                  for v in cfg.venues if v.enabled}

    def query_events(req: Request) -> list[dict]:
        p = req.query_params
        start = date.fromisoformat(p["from"]) if p.get("from") else date.today()
        end = date.fromisoformat(p["to"]) if p.get("to") else None
        venues = [v for v in p.get("venues", "").split(",") if v] or None
        if p.get("city"):
            city_ids = [v for v, m in venue_meta.items() if m["city"].lower() == p["city"].lower()]
            venues = [v for v in (venues or city_ids) if v in city_ids]
        evs = agent.store.events(start=start, end=end, venues=venues, q=p.get("q") or None,
                                 new_days=int(p["new"]) if p.get("new") else None)
        if p.get("raw") != "1":
            evs = agent.filtered_events(evs)
        return [e for e in evs if e["venue_id"] in venue_meta]

    async def index(req):
        return FileResponse(STATIC / "index.html")

    async def api_events(req):
        evs = query_events(req)
        cutoff = (datetime.now() - timedelta(days=cfg.settings.new_badge_days)).isoformat()
        for e in evs:
            e["is_new"] = e["first_seen"] >= cutoff
            e["venue"] = venue_meta[e["venue_id"]]["name"]
            e["city"] = venue_meta[e["venue_id"]]["city"]
        return JSONResponse(evs)

    async def api_venues(req):
        runs, counts = agent.store.runs(), agent.store.counts()
        out = []
        for vid, m in venue_meta.items():
            out.append({**m, "upcoming": counts.get(vid, 0), "run": runs.get(vid)})
        return JSONResponse({"venues": out, "interval_hours": cfg.settings.interval_hours,
                             "new_badge_days": cfg.settings.new_badge_days, "version": __version__})

    async def api_run(req):
        threading.Thread(target=agent.run, daemon=True).start()
        return JSONResponse({"started": True})

    async def ics(req):
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//KonzertAgent//DE",
                 "X-WR-CALNAME:Konzerte", "X-WR-TIMEZONE:Europe/Zurich", "CALSCALE:GREGORIAN"]
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        for e in query_events(req):
            d = date.fromisoformat(e["date"])
            lines += ["BEGIN:VEVENT", f"UID:{e['uid']}@konzert-agent", f"DTSTAMP:{stamp}"]
            if e["time"] and not e["end_date"]:
                hh, mm = e["time"].split(":")
                start = datetime(d.year, d.month, d.day, int(hh), int(mm))
                lines += [f"DTSTART;TZID=Europe/Zurich:{start:%Y%m%dT%H%M%S}",
                          f"DTEND;TZID=Europe/Zurich:{start + timedelta(hours=3):%Y%m%dT%H%M%S}"]
            else:
                end = date.fromisoformat(e["end_date"]) if e["end_date"] else d
                lines += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{end + timedelta(days=1):%Y%m%d}"]
            summary = e["title"] + (" (ABGESAGT)" if e["cancelled"] else "")
            venue = venue_meta[e["venue_id"]]
            lines += [f"SUMMARY:{_ics_escape(summary)}",
                      f"LOCATION:{_ics_escape(venue['name'] + (', ' + venue['city'] if venue['city'] else ''))}",
                      f"URL:{e['url']}", f"DESCRIPTION:{_ics_escape(e['url'])}", "END:VEVENT"]
        lines.append("END:VCALENDAR")
        # Zeilen > 75 Oktette falten
        folded = []
        for line in lines:
            while len(line.encode()) > 74:
                cut = 74
                while len(line[:cut].encode()) > 74:
                    cut -= 1
                folded.append(line[:cut]); line = " " + line[cut:]
            folded.append(line)
        return Response("\r\n".join(folded) + "\r\n", media_type="text/calendar; charset=utf-8")

    async def health(req):
        return JSONResponse({"ok": True, "version": __version__})

    return Starlette(routes=[
        Route("/", index),
        Route("/api/events", api_events),
        Route("/api/venues", api_venues),
        Route("/api/run", api_run, methods=["POST"]),
        Route("/calendar.ics", ics),
        Route("/health", health),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ])
