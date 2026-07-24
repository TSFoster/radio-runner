import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

import config
from fsapi_client import FSAPIClient, FSAPIError
from calendar_sync import CalendarSyncService, RadioAlarmEvent

logger = logging.getLogger("radio-runner.scheduler")

async def execute_radio_on(fsapi_client: FSAPIClient, source: Optional[str], volume: Optional[int], sleep: Optional[int]):
    """Job callback to turn the radio ON with specified settings."""
    logger.info(f"⏰ EXECUTING ALARM: Turning radio ON (source={source}, volume={volume}, sleep={sleep})")
    try:
        await fsapi_client.set_power(True)
        
        target_source = source or config.DEFAULT_SOURCE
        if target_source:
            await fsapi_client.set_mode(target_source)
            
        target_volume = volume if volume is not None else config.DEFAULT_VOLUME
        if target_volume is not None:
            await fsapi_client.set_volume(target_volume)
            
        if sleep and sleep > 0:
            await fsapi_client.set_sleep(sleep)
            
        logger.info("⏰ Alarm ON trigger completed successfully.")
    except Exception as e:
        logger.error(f"Failed to execute radio ON alarm: {e}")

async def execute_radio_off(fsapi_client: FSAPIClient):
    """Job callback to turn the radio OFF."""
    logger.info("⏰ EXECUTING ALARM: Turning radio OFF (standby)")
    try:
        await fsapi_client.set_power(False)
        logger.info("⏰ Alarm OFF trigger completed successfully.")
    except Exception as e:
        logger.error(f"Failed to execute radio OFF alarm: {e}")

class RadioScheduler:
    def __init__(self, scheduler: AsyncIOScheduler, fsapi_client: FSAPIClient, calendar_service: CalendarSyncService):
        self.scheduler = scheduler
        self.fsapi_client = fsapi_client
        self.calendar_service = calendar_service
        self.last_sync_time: Optional[datetime] = None
        self.next_alarms_summary: List[Dict[str, Any]] = []

    def clear_alarm_jobs(self):
        """Clears dynamically scheduled alarm jobs, preserving any job scheduled within the next 30 seconds."""
        now = datetime.now(timezone.utc)
        for job in list(self.scheduler.get_jobs()):
            if job.id.startswith("alarm_on_") or job.id.startswith("alarm_off_"):
                # If a job is scheduled to fire within the next 30 seconds, preserve it to prevent race conditions
                if job.next_run_time and (job.next_run_time - now).total_seconds() < 30:
                    continue
                self.scheduler.remove_job(job.id)

    async def sync_and_schedule(self) -> int:
        """Fetches calendar events, parses new jobs, and updates scheduled alarms."""
        logger.info("Starting calendar sync & schedule update...")
        self.last_sync_time = datetime.now(timezone.utc)
        
        # 1. Fetch and parse calendar events FIRST (Network HTTP fetch + ICS parsing)
        # If this fails or throws an exception, existing jobs are preserved!
        events = await self.calendar_service.get_upcoming_alarms()
        now = datetime.now(timezone.utc)

        # 2. Clear old dynamic alarm jobs AFTER successful fetch (preserving any about to fire)
        self.clear_alarm_jobs()
        
        # 3. Batch add new alarm jobs
        scheduled_count = 0
        summary_list = []

        for event in events:
            # Schedule ON job if in the future
            if event.start_time > now:
                job_id = f"alarm_on_{event.uid}_{int(event.start_time.timestamp())}"
                self.scheduler.add_job(
                    execute_radio_on,
                    trigger=DateTrigger(run_date=event.start_time),
                    id=job_id,
                    args=[self.fsapi_client, event.source, event.volume, event.sleep],
                    misfire_grace_time=60,
                    replace_existing=True
                )
                scheduled_count += 1

            # Schedule OFF job if end_time is in the future
            if event.end_time > now:
                job_id = f"alarm_off_{event.uid}_{int(event.end_time.timestamp())}"
                self.scheduler.add_job(
                    execute_radio_off,
                    trigger=DateTrigger(run_date=event.end_time),
                    id=job_id,
                    args=[self.fsapi_client],
                    misfire_grace_time=60,
                    replace_existing=True
                )
                scheduled_count += 1

            summary_list.append({
                "summary": event.summary,
                "start": event.start_time.isoformat(),
                "end": event.end_time.isoformat(),
                "source": event.source or config.DEFAULT_SOURCE,
                "volume": event.volume if event.volume is not None else config.DEFAULT_VOLUME,
                "sleep": event.sleep
            })

        self.next_alarms_summary = summary_list
        logger.info(f"Sync complete. Scheduled {scheduled_count} alarm trigger jobs across {len(events)} events.")
        return len(events)
