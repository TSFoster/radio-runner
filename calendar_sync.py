import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import httpx
import icalendar
import recurring_ical_events

from fsapi_client import SUPPORTED_MODES

logger = logging.getLogger("radio-runner.calendar")

@dataclass
class RadioAlarmEvent:
    uid: str
    summary: str
    start_time: datetime
    end_time: datetime
    source: Optional[str] = None
    volume: Optional[int] = None
    sleep: Optional[int] = None

class CalendarSyncService:
    def __init__(self, calendar_url: str, keyword: str = "", lookahead_hours: int = 48):
        self.calendar_url = calendar_url
        self.keyword = keyword.strip().lower()
        self.lookahead_hours = lookahead_hours

    async def fetch_ics_content(self) -> str:
        """Fetches the raw .ics content from the HTTP/webcal subscription URL."""
        url = self.calendar_url
        if url.startswith("webcal://"):
            url = "http://" + url[9:]

        if not url:
            logger.warning("No CALENDAR_URL configured.")
            return ""

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            logger.info(f"Fetching calendar from {url}...")
            response = await client.get(url, headers={"User-Agent": "RadioRunner/1.0"})
            response.raise_for_status()
            return response.text

    def parse_event_overrides(self, summary: str, description: str) -> Dict[str, Any]:
        """
        Extracts optional override parameters (source, volume, sleep) from event summary or description.
        Examples:
          "Wake Up Radio [DAB, vol=15]"
          "Radio Alarm (FM, volume=10, sleep=30)"
        """
        combined = f"{summary} {description}"
        result = {}

        # Volume check (e.g. vol=15 or volume=15 or v15)
        vol_match = re.search(r'\b(?:vol(?:ume)?|v)\s*=\s*(\d+)\b', combined, re.IGNORECASE)
        if vol_match:
            result["volume"] = int(vol_match.group(1))

        # Sleep check (e.g. sleep=30)
        sleep_match = re.search(r'\bsleep\s*=\s*(\d+)\b', combined, re.IGNORECASE)
        if sleep_match:
            result["sleep"] = int(sleep_match.group(1))

        # Source check (e.g. source=DAB, or standalone mode keywords DAB, FM, Spotify, etc.)
        source_match = re.search(r'\b(?:source|mode)\s*=\s*([a-zA-Z0-9_\s]+)\b', combined, re.IGNORECASE)
        if source_match:
            result["source"] = source_match.group(1).strip()
        else:
            # Check for known mode names / aliases (sorted by length descending to match "INTERNET RADIO" before "IR")
            sorted_modes = sorted(SUPPORTED_MODES.keys(), key=len, reverse=True)
            for mode in sorted_modes:
                if re.search(r'\b' + re.escape(mode) + r'\b', combined, re.IGNORECASE):
                    result["source"] = mode
                    break

        return result

    async def get_upcoming_alarms(self) -> List[RadioAlarmEvent]:
        raw_ics = await self.fetch_ics_content()
        if not raw_ics:
            return []

        try:
            cal = icalendar.Calendar.from_ical(raw_ics)
        except Exception as e:
            logger.error(f"Failed to parse calendar .ics data: {e}")
            return []

        now = datetime.now(timezone.utc)
        lookahead_end = now + timedelta(hours=self.lookahead_hours)

        # Use recurring_ical_events to expand all RRULEs, EXDATEs, and RECURRENCE-IDs
        events_in_range = recurring_ical_events.of(cal).between(now, lookahead_end)

        alarms: List[RadioAlarmEvent] = []

        for event in events_in_range:
            summary = str(event.get("SUMMARY", "")).strip()
            description = str(event.get("DESCRIPTION", "")).strip()

            # Filter by keyword if specified in config
            if self.keyword and self.keyword not in summary.lower() and self.keyword not in description.lower():
                continue

            # Extract start and end datetimes
            dtstart = event.get("DTSTART").dt
            dtend = event.get("DTEND").dt

            # Convert date to datetime if all-day event
            if isinstance(dtstart, datetime) is False:
                dtstart = datetime.combine(dtstart, datetime.min.time(), tzinfo=timezone.utc)
            if isinstance(dtend, datetime) is False:
                dtend = datetime.combine(dtend, datetime.min.time(), tzinfo=timezone.utc)

            # Ensure timezone awareness (convert naïve to UTC)
            if dtstart.tzinfo is None:
                dtstart = dtstart.replace(tzinfo=timezone.utc)
            else:
                dtstart = dtstart.astimezone(timezone.utc)

            if dtend.tzinfo is None:
                dtend = dtend.replace(tzinfo=timezone.utc)
            else:
                dtend = dtend.astimezone(timezone.utc)

            # Ignore past end events
            if dtend <= now:
                continue

            uid = str(event.get("UID", f"{dtstart.isoformat()}-{summary}"))
            overrides = self.parse_event_overrides(summary, description)

            alarm_event = RadioAlarmEvent(
                uid=uid,
                summary=summary,
                start_time=dtstart,
                end_time=dtend,
                source=overrides.get("source"),
                volume=overrides.get("volume"),
                sleep=overrides.get("sleep")
            )
            alarms.append(alarm_event)

        # Sort chronologically by start_time
        alarms.sort(key=lambda x: x.start_time)
        logger.info(f"Found {len(alarms)} upcoming radio alarm events in the next {self.lookahead_hours}h.")
        return alarms
