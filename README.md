# Radio Runner 📻

A lightweight, secure home server to control a **Roberts Revival iStream 2** (or any Frontier Silicon FSAPI internet radio) via HTTP REST endpoints and iCal calendar subscriptions.

---

## 🌟 Features

* **REST API Control:** Simple, lightweight HTTP endpoints to inspect status, toggle power, set volume, switch sources, and manage sleep timers.
* **Calendar-Driven Radio Alarms:** Consumes `.ics` webcal subscriptions (iCloud, Google Calendar, Outlook, etc.).
* **Event Duration Control:** Radio turns **ON** at event start time and **OFF (standby)** at event end time.
* **Smart Recurrence & Override Handling:** Parses recurring events, modified single instances, and cancellations accurately via `recurring-ical-events`.
* **Dynamic Event Overrides:** Optionally specify custom source, volume, or sleep timer directly in calendar event titles or descriptions (e.g., `Wake Up [DAB, vol=14, sleep=30]`).
* **Wipe & Re-schedule Strategy:** Periodic sync (every 15 min by default) ensures schedule updates are reflected seamlessly without orphaned jobs.

---

## 🚀 Quick Start

### 1. Requirements & Installation

```bash
git clone https://github.com/TSFoster/radio-runner.git
cd radio-runner

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Copy `.env.example` to `.env` and adjust your settings:

```bash
cp .env.example .env
```

Edit `.env`:

```env
RADIO_IP=192.168.68.71
RADIO_PIN=1234
RADIO_PORT=80
CALENDAR_URL=https://calendar.google.com/calendar/ical/.../basic.ics
SYNC_INTERVAL_MINUTES=15
LOOKAHEAD_HOURS=48
DEFAULT_SOURCE=DAB
DEFAULT_VOLUME=12
SERVER_PORT=8000
```

### 3. Run the Server

```bash
python main.py
```
Or with `uvicorn`:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Interactive OpenAPI documentation is available at: **`http://<SERVER_IP>:8000/docs`**

---

## 📅 Calendar Event Options

* **Radio ON:** Occurs at `event.start_time`.
* **Radio OFF:** Occurs at `event.end_time`.
* **Event Overrides:** You can customize settings per event by placing parameters in the title or description:
  * `Radio Alarm [DAB, vol=15]` -> Sets mode to DAB and volume to 15.
  * `Radio Sleep [FM, vol=8, sleep=45]` -> Sets mode to FM, volume 8, and sleep timer for 45 mins.

---

## 🌐 REST API Endpoints

The server exposes a clean HTTP REST API for controlling the radio and managing calendar sync.

| HTTP Method | Endpoint | Description | Query Parameters / Example |
| :--- | :--- | :--- | :--- |
| **`GET`** | `/api/v1/status` | Get radio state & upcoming scheduled alarms | |
| **`GET`** | `/api/v1/radio/modes` | List supported radio source modes & aliases | |
| **`POST`** | `/api/v1/radio/on` | Turn radio ON (with optional parameters) | `?source=DAB&volume=14&sleep=30` |
| **`POST`** | `/api/v1/radio/off` | Turn radio OFF (standby) | |
| **`POST`** | `/api/v1/radio/source` | Switch active input mode | `?source=FM` |
| **`POST`** | `/api/v1/radio/volume` | Set volume level (0–32) | `?volume=12` |
| **`POST`** | `/api/v1/radio/sleep` | Set sleep timer in minutes | `?minutes=30` |
| **`POST`** | `/api/v1/sync` | Force an immediate calendar fetch & re-schedule | |

> [!NOTE]
> **iOS Shortcuts Footnote:** All `POST` endpoints can be triggered directly from an iPhone using the standard **"Get Contents of URL"** action in Apple Shortcuts (set Method to `POST` and pass query parameters or JSON body).

---

## 🐳 Docker Deployment

You can easily run Radio Runner inside a lightweight Docker container.

### Option A: Using Docker Compose (Recommended)

1. Create and edit your `.env` file:
   ```bash
   cp .env.example .env
   ```
2. Start the container in detached mode:
   ```bash
   docker compose up -d
   ```

### Option B: Using Docker CLI

1. Build the Docker image:
   ```bash
   docker build -t radio-runner .
   ```
2. Run the container with your `.env` file mounted:
   ```bash
   docker run -d \
     --name radio-runner \
     --restart unless-stopped \
     --env-file .env \
     -p 8000:8000 \
     radio-runner
   ```

---

## 🛠 Running as a Daemon Service (systemd)

Create `/etc/systemd/system/radio-runner.service`:

```ini
[Unit]
Description=Radio Runner FSAPI & Calendar Service
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/radio-runner
ExecStart=/usr/bin/python3 /home/pi/radio-runner/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable --now radio-runner
```
