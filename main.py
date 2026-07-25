import logging
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from fsapi_client import FSAPIClient, FSAPIError
from calendar_sync import CalendarSyncService
from scheduler import RadioScheduler

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("radio-runner")

# Global Service Instances
fsapi_client = FSAPIClient(host=config.RADIO_IP, pin=config.RADIO_PIN, port=config.RADIO_PORT)
calendar_service = CalendarSyncService(
    calendar_url=config.CALENDAR_URL,
    keyword=config.CALENDAR_KEYWORD,
    lookahead_hours=config.LOOKAHEAD_HOURS
)
async_scheduler = AsyncIOScheduler()
radio_scheduler = RadioScheduler(async_scheduler, fsapi_client, calendar_service)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start scheduler and run initial sync
    logger.info("Starting Radio Runner service...")
    async_scheduler.start()

    # Add periodic calendar sync job (runs at :15 seconds past the minute to avoid top-of-minute alarm races)
    async_scheduler.add_job(
        radio_scheduler.sync_and_schedule,
        trigger="cron",
        minute=f"*/{config.SYNC_INTERVAL_MINUTES}",
        second=15,
        id="periodic_calendar_sync",
        replace_existing=True
    )

    # Trigger initial sync
    try:
        await radio_scheduler.sync_and_schedule()
    except Exception as e:
        logger.error(f"Initial calendar sync failed: {e}")

    yield

    # Shutdown
    logger.info("Shutting down Radio Runner service...")
    async_scheduler.shutdown()

app = FastAPI(
    title="Radio Runner API",
    description="Minimal server to control Roberts Revival iStream 2 radio via Frontier Silicon FSAPI & Calendar Schedule",
    version="1.0.0",
    lifespan=lifespan
)

# Response Models
class StatusResponse(BaseModel):
    radio: Dict[str, Any]
    calendar: Dict[str, Any]

class CommandResponse(BaseModel):
    success: bool
    message: str

INDEX_HTML_PATH = Path(__file__).parent / "index.html"
SW_JS_PATH = Path(__file__).parent / "sw.js"
SVG_ICON_CONTENT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <linearGradient id="bg-grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a"/>
      <stop offset="50%" stop-color="#1e1b4b"/>
      <stop offset="100%" stop-color="#090d16"/>
    </linearGradient>
    <linearGradient id="wave-grad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#06b6d4"/>
      <stop offset="50%" stop-color="#3b82f6"/>
      <stop offset="100%" stop-color="#8b5cf6"/>
    </linearGradient>
    <radialGradient id="knob-grad" cx="35%" cy="35%" r="65%">
      <stop offset="0%" stop-color="#e2e8f0"/>
      <stop offset="50%" stop-color="#94a3b8"/>
      <stop offset="100%" stop-color="#334155"/>
    </radialGradient>
    <filter id="neon-glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="8" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
    <linearGradient id="glass-sheen" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.15"/>
      <stop offset="40%" stop-color="#ffffff" stop-opacity="0.05"/>
      <stop offset="40.1%" stop-color="#ffffff" stop-opacity="0"/>
      <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect width="512" height="512" fill="url(#bg-grad)"/>
  <circle cx="256" cy="220" r="150" fill="#06b6d4" opacity="0.12" filter="url(#neon-glow)"/>
  <g fill="none" stroke="url(#wave-grad)" opacity="0.85" filter="url(#neon-glow)">
    <path d="M 126 290 A 150 150 0 1 1 386 290" stroke-width="6" stroke-linecap="round"/>
    <path d="M 166 274 A 110 110 0 1 1 346 274" stroke-width="8" stroke-linecap="round"/>
    <path d="M 206 258 A 70 70 0 1 1 306 258" stroke-width="10" stroke-linecap="round"/>
  </g>
  <g stroke="url(#wave-grad)" fill="none" stroke-linecap="round" filter="url(#neon-glow)">
    <path d="M 96 230 Q 136 180 176 230 T 256 230 T 336 230 T 416 230" stroke-width="5" opacity="0.9"/>
    <path d="M 96 230 Q 136 280 176 230 T 256 230 T 336 230 T 416 230" stroke-width="3" opacity="0.6"/>
  </g>
  <circle cx="256" cy="360" r="60" fill="#0f172a" stroke="url(#wave-grad)" stroke-width="4" filter="url(#neon-glow)"/>
  <circle cx="256" cy="360" r="50" fill="url(#knob-grad)"/>
  <circle cx="256" cy="324" r="5" fill="#06b6d4" filter="url(#neon-glow)"/>
  <rect width="512" height="512" fill="url(#glass-sheen)"/>
</svg>"""

@app.get("/", response_class=FileResponse)
async def read_root():
    """Serves the main web dashboard user interface."""
    if not INDEX_HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="index.html file not found")
    return FileResponse(
        INDEX_HTML_PATH,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, must-revalidate"}
    )

@app.get("/sw.js", response_class=FileResponse)
async def read_sw():
    """Serves the PWA Service Worker."""
    if not SW_JS_PATH.exists():
        raise HTTPException(status_code=404, detail="sw.js file not found")
    return FileResponse(
        SW_JS_PATH,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, must-revalidate"}
    )

@app.get("/icon.svg", response_class=Response)
@app.get("/favicon.ico", response_class=Response)
async def get_icon():
    """Serves the SVG app icon and favicon."""
    return Response(
        content=SVG_ICON_CONTENT,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"}
    )

@app.get("/manifest.json")
async def read_manifest():
    """Serves the Web App Manifest for homescreen installation."""
    return {
        "name": "Radio Runner",
        "short_name": "Radio",
        "description": "Radio Runner Smart Receiver Dashboard",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#090d16",
        "theme_color": "#090d16",
        "icons": [
            {
                "src": "/icon.svg",
                "sizes": "512x512",
                "type": "image/svg+xml",
                "purpose": "any maskable"
            }
        ]
    }

@app.get("/api/v1/status", response_model=StatusResponse)
async def get_status():
    """Returns status of the radio (power, mode, volume, sleep) and upcoming scheduled alarms."""
    radio_status = await fsapi_client.get_status()
    calendar_status = {
        "calendar_url_configured": bool(config.CALENDAR_URL),
        "last_sync_utc": radio_scheduler.last_sync_time.isoformat() if radio_scheduler.last_sync_time else None,
        "upcoming_alarms_count": len(radio_scheduler.next_alarms_summary),
        "upcoming_alarms": radio_scheduler.next_alarms_summary
    }
    return StatusResponse(radio=radio_status, calendar=calendar_status)

@app.get("/api/v1/radio/modes")
async def get_supported_modes():
    """Returns the dictionary of supported radio source modes and their aliases."""
    from fsapi_client import SUPPORTED_MODES
    return {
        "supported_modes": SUPPORTED_MODES,
        "primary_options": ["DAB", "FM", "INTERNET RADIO", "SPOTIFY", "MUSIC PLAYER", "AUX", "BLUETOOTH"]
    }

@app.get("/api/v1/radio/presets")
async def get_presets():
    """Returns the list of saved presets for the active mode."""
    try:
        presets = await fsapi_client.get_presets()
        return {"presets": presets}
    except FSAPIError as e:
        raise HTTPException(status_code=502, detail=f"Radio API error: {str(e)}")

@app.post("/api/v1/sync", response_model=CommandResponse)
async def force_sync():
    """Forces an immediate re-fetch of the calendar feed and updates alarm schedules."""
    try:
        events_count = await radio_scheduler.sync_and_schedule()
        return CommandResponse(
            success=True,
            message=f"Calendar synced successfully. Scheduled alarms for {events_count} events."
        )
    except Exception as e:
        logger.error(f"Manual sync failed: {e}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")

@app.post("/api/v1/radio/on", response_model=CommandResponse)
async def turn_on(
    source: Optional[str] = Query(None, description="Source mode (e.g. DAB, FM, Internet Radio)"),
    preset: Optional[int] = Query(None, ge=1, le=20, description="Preset station number (1-20)"),
    volume: Optional[int] = Query(None, ge=0, le=32, description="Volume level (0-32)"),
    sleep: Optional[int] = Query(None, ge=0, description="Sleep timer in minutes")
):
    """
    Turns the radio ON. Optionally sets source mode, preset station, volume, and sleep timer.
    """
    try:
        await fsapi_client.set_power(True)
        
        details = []
        if source:
            await fsapi_client.set_mode(source)
            details.append(f"source='{source}'")
        if preset is not None:
            await fsapi_client.select_preset(preset)
            details.append(f"preset={preset}")
        if volume is not None:
            await fsapi_client.set_volume(volume)
            details.append(f"volume={volume}")
        if sleep and sleep > 0:
            await fsapi_client.set_sleep(sleep)
            details.append(f"sleep={sleep}m")

        detail_str = f" ({', '.join(details)})" if details else ""
        return CommandResponse(success=True, message=f"Radio turned ON{detail_str}")
    except FSAPIError as e:
        raise HTTPException(status_code=502, detail=f"Radio API error: {str(e)}")

@app.post("/api/v1/radio/off", response_model=CommandResponse)
async def turn_off():
    """Turns the radio OFF (standby)."""
    try:
        await fsapi_client.set_power(False)
        return CommandResponse(success=True, message="Radio turned OFF (Standby)")
    except FSAPIError as e:
        raise HTTPException(status_code=502, detail=f"Radio API error: {str(e)}")

@app.post("/api/v1/radio/source", response_model=CommandResponse)
async def set_source(
    source: str = Query(..., description="Source mode (e.g. DAB, FM, Internet Radio)")
):
    """Sets the active radio source mode."""
    try:
        await fsapi_client.set_mode(source)
        return CommandResponse(success=True, message=f"Source set to '{source}'")
    except FSAPIError as e:
        raise HTTPException(status_code=502, detail=f"Radio API error: {str(e)}")

@app.post("/api/v1/radio/preset", response_model=CommandResponse)
async def select_preset(
    preset: int = Query(..., ge=1, le=20, description="Preset station number (1-20)")
):
    """Selects a saved preset station."""
    try:
        await fsapi_client.select_preset(preset)
        return CommandResponse(success=True, message=f"Selected preset {preset}")
    except FSAPIError as e:
        raise HTTPException(status_code=502, detail=f"Radio API error: {str(e)}")

@app.post("/api/v1/radio/volume", response_model=CommandResponse)
async def set_volume(
    volume: int = Query(..., ge=0, le=32, description="Volume level (0-32)")
):
    """Sets the radio volume level."""
    try:
        await fsapi_client.set_volume(volume)
        return CommandResponse(success=True, message=f"Volume set to {volume}")
    except FSAPIError as e:
        raise HTTPException(status_code=502, detail=f"Radio API error: {str(e)}")

@app.post("/api/v1/radio/volume/up", response_model=CommandResponse)
async def volume_up(
    amount: int = Query(1, ge=1, description="Amount to increase volume by")
):
    """Increases the radio volume based on current volume (default amount: 1)."""
    try:
        new_volume = await fsapi_client.volume_up(amount)
        return CommandResponse(success=True, message=f"Volume increased to {new_volume}")
    except FSAPIError as e:
        raise HTTPException(status_code=502, detail=f"Radio API error: {str(e)}")

@app.post("/api/v1/radio/volume/down", response_model=CommandResponse)
async def volume_down(
    amount: int = Query(1, ge=1, description="Amount to decrease volume by")
):
    """Decreases the radio volume based on current volume (default amount: 1)."""
    try:
        new_volume = await fsapi_client.volume_down(amount)
        return CommandResponse(success=True, message=f"Volume decreased to {new_volume}")
    except FSAPIError as e:
        raise HTTPException(status_code=502, detail=f"Radio API error: {str(e)}")

@app.post("/api/v1/radio/sleep", response_model=CommandResponse)
async def set_sleep(
    minutes: int = Query(..., ge=0, description="Sleep timer in minutes (0 to disable)")
):
    """Sets the sleep timer."""
    try:
        await fsapi_client.set_sleep(minutes)
        msg = f"Sleep timer set to {minutes} minutes" if minutes > 0 else "Sleep timer disabled"
        return CommandResponse(success=True, message=msg)
    except FSAPIError as e:
        raise HTTPException(status_code=502, detail=f"Radio API error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.SERVER_HOST, port=config.SERVER_PORT, reload=config.RELOAD)
