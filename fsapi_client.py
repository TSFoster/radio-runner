import logging
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any, Union, List
import httpx

logger = logging.getLogger("radio-runner.fsapi")

# Standard Frontier Silicon Mode Mapping and Convenient Aliases
SUPPORTED_MODES: Dict[str, int] = {
    "DAB": 3,
    "FM": 4,
    "INTERNET RADIO": 0,
    "IRADIO": 0,
    "IR": 0,
    "SPOTIFY": 1,
    "MUSIC PLAYER": 2,
    "USB": 2,
    "MEDIA": 2,
    "AUX": 5,
    "AUX IN": 5,
    "BLUETOOTH": 6,
    "BT": 6,
}

class FSAPIError(Exception):
    """Custom exception for FSAPI errors."""
    pass

class FSAPIClient:
    def __init__(self, host: str, pin: str = "1234", port: int = 80, timeout: float = 5.0):
        self.host = host
        self.pin = pin
        self.port = port
        self.timeout = timeout
        self.base_url = f"http://{host}:{port}/fsapi"
        self.sid: Optional[str] = None
        self._mode_map: Dict[str, int] = SUPPORTED_MODES.copy()

    async def _send_request(self, endpoint: str, params: Optional[dict] = None) -> ET.Element:
        """Sends an HTTP GET request to the FSAPI endpoint and parses the XML response."""
        if params is None:
            params = {}

        # Inject session ID if available and not creating a session
        if endpoint != "CREATE_SESSION":
            if not self.sid:
                await self.create_session()
            params["sid"] = self.sid

        params["pin"] = self.pin
        url = f"{self.base_url}/{endpoint}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error {e.response.status_code} requesting {url}")
                raise FSAPIError(f"HTTP {e.response.status_code}") from e
            except httpx.RequestError as e:
                logger.error(f"Connection error to radio at {url}: {e}")
                raise FSAPIError(f"Connection error to radio: {e}") from e

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as e:
            logger.error(f"Failed to parse XML response from {url}: {response.text}")
            raise FSAPIError("Invalid XML response from radio") from e

        status_node = root.find("status")
        status_text = status_node.text if status_node is not None else ""

        if status_text == "FS_TIMEOUT" or status_text == "FS_NODE_DOES_NOT_EXIST":
            # Session might have expired; retry once after recreating session
            if endpoint != "CREATE_SESSION":
                logger.warning(f"FSAPI status '{status_text}', attempting session re-creation...")
                await self.create_session()
                params["sid"] = self.sid
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.get(url, params=params)
                    root = ET.fromstring(resp.text)
                    status_node = root.find("status")
                    status_text = status_node.text if status_node is not None else ""

        if status_text != "FS_OK":
            raise FSAPIError(f"FSAPI returned status: {status_text}")

        return root

    async def create_session(self) -> str:
        """Registers a session with the radio and stores the session ID."""
        root = await self._send_request("CREATE_SESSION")
        sid_node = root.find("sessionId")
        if sid_node is None or not sid_node.text:
            raise FSAPIError("No sessionId returned by radio")
        self.sid = sid_node.text.strip()
        logger.info(f"FSAPI session registered: {self.sid}")
        return self.sid

    async def get_node_value(self, node: str) -> Optional[str]:
        """Gets a node's value from the radio."""
        root = await self._send_request(f"GET/{node}")
        value_node = root.find(".//value")
        if value_node is not None:
            # Check for typed children like <u8>, <u32>, <c8_array>
            if len(value_node) > 0:
                return value_node[0].text
            return value_node.text
        return None

    async def set_node_value(self, node: str, value: Union[str, int]) -> bool:
        """Sets a node's value on the radio."""
        root = await self._send_request(f"SET/{node}", params={"value": str(value)})
        status_node = root.find("status")
        return status_node is not None and status_node.text == "FS_OK"

    # --- High Level Control Methods ---

    async def get_power(self) -> bool:
        val = await self.get_node_value("netRemote.sys.power")
        return val == "1"

    async def set_power(self, on: bool) -> bool:
        val = 1 if on else 0
        return await self.set_node_value("netRemote.sys.power", val)

    async def get_volume(self) -> int:
        val = await self.get_node_value("netRemote.sys.audio.volume")
        return int(val) if val is not None else 0

    async def set_volume(self, volume: int) -> bool:
        # Constrain volume between 0 and 32
        clamped = max(0, min(32, volume))
        return await self.set_node_value("netRemote.sys.audio.volume", clamped)

    async def volume_up(self, amount: int = 1) -> int:
        """Increases volume by amount (default 1) based on current volume and returns the new volume level."""
        current = await self.get_volume()
        new_vol = max(0, min(32, current + amount))
        await self.set_volume(new_vol)
        return new_vol

    async def volume_down(self, amount: int = 1) -> int:
        """Decreases volume by amount (default 1) based on current volume and returns the new volume level."""
        current = await self.get_volume()
        new_vol = max(0, min(32, current - amount))
        await self.set_volume(new_vol)
        return new_vol

    async def get_sleep(self) -> int:
        val = await self.get_node_value("netRemote.sys.sleep")
        return int(val) if val is not None else 0

    async def set_sleep(self, minutes: int) -> bool:
        """Sets the sleep timer in minutes (0 to disable)."""
        return await self.set_node_value("netRemote.sys.sleep", minutes)

    async def get_mode(self) -> str:
        val = await self.get_node_value("netRemote.sys.mode")
        if val is None:
            return "UNKNOWN"
        mode_id = int(val)
        # Reverse map mode_id to name if known
        for name, mid in self._mode_map.items():
            if mid == mode_id:
                return name
        return f"MODE_{mode_id}"

    async def set_mode(self, mode: Union[str, int]) -> bool:
        """Sets the radio mode by integer ID or string name (e.g. 'DAB', 'FM', 'Internet Radio')."""
        if isinstance(mode, str):
            normalized = mode.strip().upper()
            if normalized in self._mode_map:
                mode_id = self._mode_map[normalized]
            else:
                # Try finding substring match
                matched_id = None
                for name, mid in self._mode_map.items():
                    if normalized in name or name in normalized:
                        matched_id = mid
                        break
                if matched_id is not None:
                    mode_id = matched_id
                else:
                    raise FSAPIError(f"Unknown mode name '{mode}'. Supported modes: {list(self._mode_map.keys())}")
        else:
            mode_id = int(mode)

        return await self.set_node_value("netRemote.sys.mode", mode_id)

    async def select_preset(self, preset_number: int) -> bool:
        """Selects a radio preset number (e.g. 1 to 20)."""
        # Some firmware requires enabling nav state before triggering selectPreset
        try:
            await self.set_node_value("netRemote.nav.state", 1)
        except Exception:
            pass

        success = await self.set_node_value("netRemote.nav.action.selectPreset", preset_number)

        try:
            await self.set_node_value("netRemote.nav.state", 0)
        except Exception:
            pass

        return success

    async def get_presets(self) -> List[Dict[str, Any]]:
        """Fetches the list of saved presets for the current mode."""
        try:
            root = await self._send_request("GET/netRemote.nav.presets")
            presets = []
            for item in root.findall(".//item"):
                item_id = item.get("id")
                # Look for name label node
                name_node = item.find(".//c8_array")
                name = name_node.text.strip() if name_node is not None and name_node.text else "Empty"
                preset_num = int(item_id) + 1 if item_id and item_id.isdigit() else item_id
                presets.append({
                    "preset": preset_num,
                    "name": name
                })
            return presets
        except Exception as e:
            logger.warning(f"Could not fetch presets from radio: {e}")
            return []

    async def get_status(self) -> Dict[str, Any]:
        """Fetches unified status of the radio."""
        try:
            power = await self.get_power()
            volume = await self.get_volume() if power else 0
            mode = await self.get_mode() if power else "STANDBY"
            sleep = await self.get_sleep() if power else 0
            return {
                "online": True,
                "power": power,
                "mode": mode,
                "volume": volume,
                "sleep_minutes": sleep
            }
        except FSAPIError as e:
            logger.warning(f"Radio status query failed: {e}")
            return {
                "online": False,
                "error": str(e)
            }
