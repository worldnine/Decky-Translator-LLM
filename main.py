# main.py
import asyncio
from asyncio.subprocess import PIPE
import os
import sys
import traceback
import subprocess
import signal
import time
from datetime import datetime
from pathlib import Path
import logging
import json
import base64
import tarfile

# IMPORTANT: Set up plugin directory FIRST
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

# Auto-extract dependencies archive if needed (for Decky Store installs)
# This must happen BEFORE importing third-party libraries
BIN_DIR = os.path.join(PLUGIN_DIR, "bin")
DEPENDENCIES_ARCHIVE = os.path.join(BIN_DIR, "plugin-dependencies.tar.gz")
EXTRACTION_MARKER = os.path.join(BIN_DIR, ".dependencies-extracted")
BIN_PY_MODULES_DIR = os.path.join(BIN_DIR, "py_modules")

def _should_extract_dependencies():
    """Check if dependencies archive needs to be extracted."""
    if not os.path.exists(DEPENDENCIES_ARCHIVE):
        return False  # No dependencies archive to extract

    # Check if extraction marker exists
    if not os.path.exists(EXTRACTION_MARKER):
        return True  # Never extracted successfully

    # Check if dependencies were updated (archive is newer than marker)
    archive_mtime = os.path.getmtime(DEPENDENCIES_ARCHIVE)
    marker_mtime = os.path.getmtime(EXTRACTION_MARKER)
    if archive_mtime > marker_mtime:
        return True  # Dependencies were updated, need to re-extract

    # Check if all expected directories exist (partial extraction detection)
    if not os.path.exists(BIN_PY_MODULES_DIR):
        return True  # Some directories missing, need to re-extract

    return False  # Already extracted and up-to-date

if _should_extract_dependencies():
    try:
        print(f"[Decky Translator] Extracting dependencies from {DEPENDENCIES_ARCHIVE}...")
        with tarfile.open(DEPENDENCIES_ARCHIVE, "r:gz") as tar:
            tar.extractall(path=BIN_DIR)
        # Create marker file to indicate successful extraction
        with open(EXTRACTION_MARKER, "w") as f:
            f.write(f"Extracted at {datetime.now().isoformat()}\n")
        print(f"[Decky Translator] Dependencies extracted successfully")
    except Exception as e:
        print(f"[Decky Translator] Failed to extract dependencies: {e}")
        # Remove marker if it exists, so we retry next time
        if os.path.exists(EXTRACTION_MARKER):
            os.remove(EXTRACTION_MARKER)

# Add py_modules to path
# Root py_modules always needed (contains providers/ source code)
# bin/py_modules needed for store installs (pip packages from remote_binary)
ROOT_PY_MODULES_DIR = os.path.join(PLUGIN_DIR, "py_modules")

if ROOT_PY_MODULES_DIR not in sys.path:
    sys.path.insert(0, ROOT_PY_MODULES_DIR)

if os.path.exists(BIN_PY_MODULES_DIR) and BIN_PY_MODULES_DIR not in sys.path:
    sys.path.insert(0, BIN_PY_MODULES_DIR)

# Now import third-party libraries (after sys.path is configured)
import decky_plugin
import urllib3
import requests

# Import provider system
from providers import ProviderManager, NetworkError, ApiKeyError
import pin_history
import translation_history
from migration import (
    normalize_gemini_setting,
    extract_prompt_from_content,
    migrate_llm_system_prompt,
    ensure_vision_common_file,
    migrate_old_game_prompt,
)

_processing_lock = False

# Get environment variable
settingsDir = os.environ.get("DECKY_PLUGIN_SETTINGS_DIR", "/home/deck/homebrew/settings/decky-translator-llm")
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Set up logging
logger = decky_plugin.logger

# Make sure we use the right paths
DECKY_PLUGIN_DIR = os.environ.get("DECKY_PLUGIN_DIR", decky_plugin.DECKY_PLUGIN_DIR)
DECKY_PLUGIN_LOG_DIR = os.environ.get("DECKY_PLUGIN_LOG_DIR", decky_plugin.DECKY_PLUGIN_LOG_DIR)
DECKY_HOME = os.environ.get("DECKY_HOME", decky_plugin.DECKY_HOME or "/home/deck")

# Set up paths
DEPSPATH = Path(DECKY_PLUGIN_DIR) / "bin"
if not DEPSPATH.exists():
    DEPSPATH = Path(DECKY_PLUGIN_DIR) / "backend/out"
GSTPLUGINSPATH = DEPSPATH / "gstreamer-1.0"

# Log configured paths for debugging
logger.debug(f"DECKY_PLUGIN_DIR: {DECKY_PLUGIN_DIR}")
logger.debug(f"DECKY_PLUGIN_LOG_DIR: {DECKY_PLUGIN_LOG_DIR}")
logger.debug(f"DECKY_HOME: {DECKY_HOME}")
logger.debug(f"Dependencies path: {DEPSPATH}")
logger.debug(f"GStreamer plugins path: {GSTPLUGINSPATH}")

# Ensure log directory exists
os.makedirs(DECKY_PLUGIN_LOG_DIR, exist_ok=True)

# Set up log files
std_out_file_path = Path(DECKY_PLUGIN_LOG_DIR) / "decky-translator-std-out.log"
std_out_file = open(std_out_file_path, "w")
std_err_file = open(Path(DECKY_PLUGIN_LOG_DIR) / "decky-translator-std-err.log", "w")
logger.debug(f"Standard output logs: {std_out_file_path}")

# Set up file logging
from logging.handlers import TimedRotatingFileHandler

log_file = Path(DECKY_PLUGIN_LOG_DIR) / "decky-translator.log"
log_file_handler = TimedRotatingFileHandler(log_file, when="midnight", backupCount=2)
log_file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.handlers.clear()
logger.addHandler(log_file_handler)
logger.setLevel(logging.INFO)
logger.info(f"Configured rotating log file: {log_file}")


import threading
import queue
import fcntl
import struct
import select


class HidrawButtonMonitor:
    """
    Monitors Steam Deck controller via /dev/hidraw for low-level button detection.
    Detects L4, L5, R4, R5, Steam, and QAM buttons that Steam normally intercepts.
    """

    # Device identification
    VALVE_VID = 0x28DE
    STEAMDECK_PID = 0x1205
    PACKET_SIZE = 64
    POLL_INTERVAL = 0.004  # 250Hz - matches controller report rate

    # HID ioctl command
    HIDIOCSFEATURE = lambda self, size: (0xC0000000 | (size << 16) | (ord('H') << 8) | 0x06)

    # HID commands for controller initialization
    ID_CLEAR_DIGITAL_MAPPINGS = 0x81
    ID_SET_SETTINGS_VALUES = 0x87
    SETTING_LEFT_TRACKPAD_MODE = 0x07
    SETTING_RIGHT_TRACKPAD_MODE = 0x08
    TRACKPAD_NONE = 0x07
    SETTING_STEAM_WATCHDOG_ENABLE = 0x2D

    # Button masks - ButtonsL (bytes 8-11, uint32 LE)
    BUTTONS_L = {
        'R2': 0x00000001,
        'L2': 0x00000002,
        'R1': 0x00000004,
        'L1': 0x00000008,
        'Y': 0x00000010,
        'B': 0x00000020,
        'X': 0x00000040,
        'A': 0x00000080,
        'DPAD_UP': 0x00000100,
        'DPAD_RIGHT': 0x00000200,
        'DPAD_LEFT': 0x00000400,
        'DPAD_DOWN': 0x00000800,
        'SELECT': 0x00001000,
        'STEAM': 0x00002000,
        'START': 0x00004000,
        'L5': 0x00008000,
        'R5': 0x00010000,
        'LEFT_PAD_TOUCH': 0x00020000,
        'RIGHT_PAD_TOUCH': 0x00040000,
        'LEFT_PAD_CLICK': 0x00080000,
        'RIGHT_PAD_CLICK': 0x00100000,
        'L3': 0x00400000,
        'R3': 0x04000000,
    }

    # Button masks - ButtonsH (bytes 12-15, uint32 LE)
    BUTTONS_H = {
        'L4': 0x00000200,
        'R4': 0x00000400,
        'QAM': 0x00040000,
    }

    def __init__(self):
        self.device_fd = None
        self.device_path = None
        self.running = False
        self.thread = None
        self.event_queue = queue.Queue(maxsize=100)
        self.current_buttons = set()
        self.last_buttons_l = 0
        self.last_buttons_h = 0
        self.error_count = 0
        self.initialized = False
        self.lock = threading.Lock()
        logger.debug("HidrawButtonMonitor initialized")

    def find_device(self):
        """Find the Steam Deck controller hidraw device.

        The Steam Deck controller exposes 3 hidraw interfaces:
        - Interface 0 (hidraw0): Not the gamepad interface
        - Interface 1 (hidraw1): Not the gamepad interface
        - Interface 2 (hidraw2): The gamepad interface with button data

        We need to find the one that actually provides gamepad data by checking
        which interface is 1.2 in the device path.
        """
        candidates = []

        for i in range(10):
            path = f'/dev/hidraw{i}'
            if os.path.exists(path):
                uevent_path = f'/sys/class/hidraw/hidraw{i}/device/uevent'
                try:
                    with open(uevent_path, 'r') as f:
                        content = f.read().upper()
                        # Check for Valve Steam Deck controller
                        if '28DE' in content and '1205' in content:
                            candidates.append((i, path))
                            logger.debug(f"Found Valve controller candidate at {path}")
                except Exception as e:
                    logger.debug(f"Cannot read uevent for hidraw{i}: {e}")

        if not candidates:
            logger.warning("Steam Deck controller hidraw device not found")
            return None

        # Try to find the correct interface by checking the symlink path
        # The gamepad interface is typically :1.2
        for i, path in candidates:
            try:
                link_target = os.readlink(f'/sys/class/hidraw/hidraw{i}')
                if ':1.2/' in link_target:
                    logger.info(f"Found Steam Deck gamepad interface at {path} (interface 1.2)")
                    return path
            except Exception as e:
                logger.debug(f"Cannot read symlink for hidraw{i}: {e}")

        # Fallback: try each candidate with a blocking read to see which has data
        for i, path in candidates:
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                try:
                    # Use select to check if data is available within 100ms
                    readable, _, _ = select.select([fd], [], [], 0.1)
                    if readable:
                        os.read(fd, 64)
                        os.close(fd)
                        logger.info(f"Found Steam Deck controller at {path} (has data)")
                        return path
                    os.close(fd)
                except Exception:
                    os.close(fd)
            except Exception as e:
                logger.debug(f"Cannot open {path}: {e}")

        # Last resort: return the highest numbered candidate (usually the gamepad)
        if candidates:
            path = candidates[-1][1]
            logger.info(f"Using Steam Deck controller at {path} (last candidate)")
            return path

        logger.warning("Steam Deck controller hidraw device not found")
        return None

    def send_feature_report(self, data):
        """Send a HID feature report to the device."""
        if self.device_fd is None:
            return False
        try:
            # Pad to 64 bytes
            buf = bytes(data) + bytes(64 - len(data))
            fcntl.ioctl(self.device_fd, self.HIDIOCSFEATURE(64), buf)
            return True
        except Exception as e:
            logger.error(f"Failed to send feature report: {e}")
            return False

    def initialize_device(self):
        """Open device and send initialization commands to enable full controller mode."""
        if self.device_path is None:
            self.device_path = self.find_device()
            if self.device_path is None:
                return False

        try:
            # Open device with read/write access
            self.device_fd = os.open(self.device_path, os.O_RDWR)
            logger.info(f"Opened {self.device_path} for hidraw monitoring")

            # Send initialization commands to enable full controller mode
            # Command 1: Clear digital mappings (disable lizard mode)
            if not self.send_feature_report([self.ID_CLEAR_DIGITAL_MAPPINGS]):
                logger.warning("Failed to send CLEAR_DIGITAL_MAPPINGS")

            # Command 2: Set settings to disable trackpad emulation
            settings_cmd = [
                self.ID_SET_SETTINGS_VALUES,
                3,  # Number of settings
                self.SETTING_LEFT_TRACKPAD_MODE, self.TRACKPAD_NONE,
                self.SETTING_RIGHT_TRACKPAD_MODE, self.TRACKPAD_NONE,
                self.SETTING_STEAM_WATCHDOG_ENABLE, 0,
            ]
            if not self.send_feature_report(settings_cmd):
                logger.warning("Failed to send SET_SETTINGS_VALUES")

            self.initialized = True
            logger.info("Steam Deck controller initialized for full button access")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize hidraw device: {e}")
            if self.device_fd is not None:
                try:
                    os.close(self.device_fd)
                except:
                    pass
                self.device_fd = None
            return False

    def start(self):
        """Start the background monitoring thread."""
        if self.running:
            logger.warning("HidrawButtonMonitor already running")
            return True

        if not self.initialize_device():
            logger.error("Failed to initialize device, cannot start monitor")
            return False

        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("HidrawButtonMonitor started")
        return True

    def stop(self):
        self.running = False

        if self.thread is not None:
            self.thread.join(timeout=2.0)
            self.thread = None

        if self.device_fd is not None:
            try:
                os.close(self.device_fd)
            except:
                pass
            self.device_fd = None

        self.initialized = False
        logger.info("HidrawButtonMonitor stopped")

    def _monitor_loop(self):
        """Background thread main loop - reads HID packets and generates events."""
        logger.info("HidrawButtonMonitor loop started")
        reconnect_delay = 2.0
        max_errors = 10

        while self.running:
            try:
                # Check if we need to reconnect
                if not self.initialized or self.device_fd is None:
                    logger.info("Attempting to reconnect to hidraw device")
                    if not self.initialize_device():
                        time.sleep(reconnect_delay)
                        continue

                # Wait for data with select (timeout to allow checking running flag)
                r, _, _ = select.select([self.device_fd], [], [], 0.1)
                if not r:
                    continue

                # Read packet
                data = os.read(self.device_fd, self.PACKET_SIZE)
                if len(data) >= 16:
                    self._process_packet(data)
                    self.error_count = 0

            except OSError as e:
                self.error_count += 1
                logger.warning(f"Hidraw read error ({self.error_count}): {e}")

                if self.error_count >= max_errors:
                    logger.error("Too many errors, closing device for reconnection")
                    self._close_device()
                    time.sleep(reconnect_delay)

            except Exception as e:
                logger.error(f"Unexpected error in hidraw monitor loop: {e}")
                self.error_count += 1
                time.sleep(0.1)

        logger.info("HidrawButtonMonitor loop ended")

    def _close_device(self):
        """Safely close the device for reconnection."""
        if self.device_fd is not None:
            try:
                os.close(self.device_fd)
            except:
                pass
            self.device_fd = None
        self.initialized = False
        self.device_path = None

    def _process_packet(self, data):
        """Parse HID packet and generate button events."""
        # Parse button states from packet
        buttons_l = struct.unpack('<I', data[8:12])[0]
        buttons_h = struct.unpack('<I', data[12:16])[0]

        # Check if button state changed
        if buttons_l == self.last_buttons_l and buttons_h == self.last_buttons_h:
            return

        timestamp = time.time()
        new_buttons = set()

        # Check ButtonsL
        for name, mask in self.BUTTONS_L.items():
            if buttons_l & mask:
                new_buttons.add(name)

        # Check ButtonsH
        for name, mask in self.BUTTONS_H.items():
            if buttons_h & mask:
                new_buttons.add(name)

        # Generate events for changed buttons
        with self.lock:
            # Buttons that were released
            for button in self.current_buttons - new_buttons:
                event = {
                    "button": button,
                    "pressed": False,
                    "timestamp": timestamp
                }
                try:
                    self.event_queue.put_nowait(event)
                except queue.Full:
                    # Queue full, discard oldest
                    try:
                        self.event_queue.get_nowait()
                        self.event_queue.put_nowait(event)
                    except:
                        pass

            # Buttons that were pressed
            for button in new_buttons - self.current_buttons:
                event = {
                    "button": button,
                    "pressed": True,
                    "timestamp": timestamp
                }
                try:
                    self.event_queue.put_nowait(event)
                except queue.Full:
                    try:
                        self.event_queue.get_nowait()
                        self.event_queue.put_nowait(event)
                    except:
                        pass

            self.current_buttons = new_buttons

        self.last_buttons_l = buttons_l
        self.last_buttons_h = buttons_h

    def get_events(self, max_events=10):
        """Get pending button events from the queue."""
        events = []
        with self.lock:
            for _ in range(max_events):
                try:
                    event = self.event_queue.get_nowait()
                    events.append(event)
                except queue.Empty:
                    break
        return events

    def get_button_state(self):
        """Get the current complete button state (all currently pressed buttons)."""
        with self.lock:
            return list(self.current_buttons)

    def get_status(self):
        """Get monitor status for diagnostics."""
        with self.lock:
            return {
                "running": self.running,
                "initialized": self.initialized,
                "device_path": self.device_path,
                "error_count": self.error_count,
                "queue_size": self.event_queue.qsize(),
                "current_buttons": list(self.current_buttons),
                "last_buttons_l": hex(self.last_buttons_l),
                "last_buttons_h": hex(self.last_buttons_h),
            }


for _p in [ROOT_PY_MODULES_DIR, BIN_PY_MODULES_DIR]:
    if os.path.exists(_p):
        if _p in sys.path:
            sys.path.remove(_p)
        sys.path.insert(0, _p)

try:
    import evdev
    EVDEV_AVAILABLE = True
except ImportError as e:
    EVDEV_AVAILABLE = False
    logger.warning(f"evdev import failed: {e}")
except Exception as e:
    EVDEV_AVAILABLE = False
    logger.warning(f"evdev import error ({type(e).__name__}): {e}")


class EvdevGamepadMonitor:
    """
    Monitors external gamepads (Xbox, PlayStation, etc.) via Linux evdev.
    Filters out Valve's built-in controller (handled by HidrawButtonMonitor).
    """

    SCAN_INTERVAL = 5.0      # seconds between device scans
    CACHE_CLEAR_INTERVAL = 60  # seconds before re-checking rejected devices

    BUTTON_MAP = {
        304: 'A',       # BTN_A / BTN_SOUTH
        305: 'B',       # BTN_B / BTN_EAST
        307: 'X',       # BTN_X / BTN_NORTH (note: 306 is BTN_C)
        308: 'Y',       # BTN_Y / BTN_WEST
        310: 'L1',      # BTN_TL
        311: 'R1',      # BTN_TR
        312: 'L2',      # BTN_TL2
        313: 'R2',      # BTN_TR2
        314: 'SELECT',  # BTN_SELECT
        315: 'START',   # BTN_START
        316: 'STEAM',   # BTN_MODE
        317: 'L3',      # BTN_THUMBL
        318: 'R3',      # BTN_THUMBR
    }

    VALVE_VENDOR = 0x28de

    def __init__(self):
        self.running = False
        self.thread = None
        self.devices = {}  # fd -> InputDevice
        self.device_paths = set()  # tracked device paths
        self._rejected_paths = set()  # paths we already checked and dismissed
        self._last_cache_clear = 0
        self.current_buttons = set()
        self.lock = threading.Lock()
        self.last_scan_time = 0
        logger.debug("EvdevGamepadMonitor initialized")

    def _is_gamepad(self, dev):
        """Check if device has gamepad capabilities (EV_KEY + EV_ABS)."""
        try:
            caps = dev.capabilities(verbose=False)
            has_keys = 1 in caps  # EV_KEY
            has_abs = 3 in caps   # EV_ABS
            return has_keys and has_abs
        except Exception:
            return False

    def _scan_devices(self):
        """Find new external gamepads, skip Valve and virtual devices."""
        if not EVDEV_AVAILABLE:
            return

        now = time.time()
        if now - self._last_cache_clear >= self.CACHE_CLEAR_INTERVAL:
            self._rejected_paths.clear()
            self._last_cache_clear = now

        try:
            for path in evdev.list_devices():
                if path in self.device_paths or path in self._rejected_paths:
                    continue

                try:
                    dev = evdev.InputDevice(path)
                except Exception:
                    self._rejected_paths.add(path)
                    continue

                # Skip virtual devices (empty phys)
                if not dev.phys:
                    dev.close()
                    self._rejected_paths.add(path)
                    continue

                # Skip Valve controllers
                if dev.info.vendor == self.VALVE_VENDOR:
                    dev.close()
                    self._rejected_paths.add(path)
                    continue

                if not self._is_gamepad(dev):
                    dev.close()
                    self._rejected_paths.add(path)
                    continue

                with self.lock:
                    self.devices[dev.fd] = dev
                    self.device_paths.add(path)
                logger.info(f"EvdevGamepadMonitor: found gamepad '{dev.name}' at {path}")

        except Exception as e:
            logger.debug(f"EvdevGamepadMonitor: scan error: {e}")

    def start(self):
        if self.running:
            return True
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("EvdevGamepadMonitor started")
        return True

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=2.0)
            self.thread = None

        with self.lock:
            for dev in self.devices.values():
                try:
                    dev.close()
                except Exception:
                    pass
            self.devices.clear()
            self.device_paths.clear()
            self._rejected_paths.clear()
            self.current_buttons.clear()

        logger.info("EvdevGamepadMonitor stopped")

    def _monitor_loop(self):
        logger.info("EvdevGamepadMonitor loop started")

        while self.running:
            now = time.time()
            if now - self.last_scan_time >= self.SCAN_INTERVAL:
                self._scan_devices()
                self.last_scan_time = now

            with self.lock:
                if not self.devices:
                    has_devices = False
                else:
                    has_devices = True
                    fds = list(self.devices.keys())

            if not has_devices:
                time.sleep(0.5)
                continue

            try:
                readable, _, _ = select.select(fds, [], [], 0.1)
            except (ValueError, OSError):
                # Bad fd, a device probably disconnected
                self._remove_stale_devices()
                continue

            for fd in readable:
                with self.lock:
                    dev = self.devices.get(fd)
                if dev is None:
                    continue

                try:
                    for event in dev.read():
                        if event.type == 1:  # EV_KEY
                            name = self.BUTTON_MAP.get(event.code)
                            if name is not None:
                                with self.lock:
                                    if event.value == 1:  # pressed
                                        self.current_buttons.add(name)
                                    elif event.value == 0:  # released
                                        self.current_buttons.discard(name)
                except OSError:
                    logger.info(f"EvdevGamepadMonitor: device disconnected (fd={fd})")
                    self._remove_device(fd)
                except Exception as e:
                    logger.debug(f"EvdevGamepadMonitor: read error fd={fd}: {e}")
                    self._remove_device(fd)

        logger.info("EvdevGamepadMonitor loop ended")

    def _remove_device(self, fd):
        with self.lock:
            dev = self.devices.pop(fd, None)
            if dev:
                self.device_paths.discard(dev.path)
                self._rejected_paths.discard(dev.path)
                try:
                    dev.close()
                except Exception:
                    pass

    def _remove_stale_devices(self):
        with self.lock:
            stale = []
            for fd, dev in self.devices.items():
                try:
                    os.fstat(fd)
                except OSError:
                    stale.append(fd)
            for fd in stale:
                dev = self.devices.pop(fd, None)
                if dev:
                    self.device_paths.discard(dev.path)
                    self._rejected_paths.discard(dev.path)
                    logger.info(f"EvdevGamepadMonitor: removed stale device '{dev.name}'")
                    try:
                        dev.close()
                    except Exception:
                        pass

    def get_button_state(self):
        with self.lock:
            return list(self.current_buttons)

    def get_status(self):
        with self.lock:
            device_names = [dev.name for dev in self.devices.values()]
            return {
                "running": self.running,
                "available": EVDEV_AVAILABLE,
                "device_count": len(self.devices),
                "devices": device_names,
                "current_buttons": list(self.current_buttons),
            }


class SettingsManager:
    def __init__(self, name, settings_directory):
        self.settings_path = os.path.join(settings_directory, f"{name}.json")
        self.settings = {}
        logger.debug(f"SettingsManager initialized with path: {self.settings_path}")

    def read(self):
        try:
            if os.path.exists(self.settings_path):
                with open(self.settings_path, 'r') as f:
                    self.settings = json.load(f)
                logger.debug(f"Settings loaded from {self.settings_path}")
            else:
                logger.warning(f"Settings file does not exist: {self.settings_path}")
        except Exception as e:
            logger.error(f"Failed to read settings: {str(e)}")
            logger.error(traceback.format_exc())
            self.settings = {}

    def set_setting(self, key, value):
        try:
            self.settings[key] = value
            os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
            with open(self.settings_path, 'w') as f:
                json.dump(self.settings, f, indent=4)
            logger.debug(f"Saved setting {key}={value}")
            return True
        except Exception as e:
            logger.error(f"Failed to save setting {key}: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def get_setting(self, key, default=None):
        value = self.settings.get(key, default)
        logger.debug(f"Getting setting {key}: {value}")
        return value


def get_cmd_output(cmd, log=True):
    if log:
        logger.debug(f"Executing command: {cmd}")

    try:
        output = subprocess.getoutput(cmd).strip()
        logger.debug(f"Command output: {output[:100]}{'...' if len(output) > 100 else ''}")
        return output
    except Exception as e:
        logger.error(f"Command execution failed: {str(e)}")
        logger.error(traceback.format_exc())
        return f"Error: {str(e)}"


class NotifySocketServer:
    """CLI→Plugin 通知用 Unix Domain Socket サーバー。
    CLIがスクリーンショットを撮った時にリアルタイムで通知を受け取る。"""

    SOCKET_PATH = "/tmp/decky-translator/notify.sock"
    MAX_MSG_SIZE = 4096

    def __init__(self, on_notification):
        """on_notification: callable(purpose: str, image_path: str)"""
        self.on_notification = on_notification
        self.running = False
        self.thread = None
        self.server_sock = None

    def start(self):
        if self.running:
            return True
        self.running = True
        self.thread = threading.Thread(target=self._serve_loop, daemon=True)
        self.thread.start()
        logger.info(f"NotifySocketServer started on {self.SOCKET_PATH}")
        return True

    def stop(self):
        self.running = False
        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
        if os.path.exists(self.SOCKET_PATH):
            try:
                os.unlink(self.SOCKET_PATH)
            except Exception:
                pass
        logger.info("NotifySocketServer stopped")

    def _serve_loop(self):
        import socket as _socket

        # 古いソケットファイルがあれば削除
        if os.path.exists(self.SOCKET_PATH):
            os.unlink(self.SOCKET_PATH)

        os.makedirs(os.path.dirname(self.SOCKET_PATH), exist_ok=True)

        self.server_sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        self.server_sock.bind(self.SOCKET_PATH)
        os.chmod(self.SOCKET_PATH, 0o660)
        self.server_sock.listen(5)
        self.server_sock.settimeout(1.0)

        while self.running:
            try:
                conn, _ = self.server_sock.accept()
            except _socket.timeout:
                continue
            except OSError:
                break
            try:
                data = conn.recv(self.MAX_MSG_SIZE)
                msg = json.loads(data.decode("utf-8").strip())
                if msg.get("type") in ("screenshot_taken", "agent_notification"):
                    self.on_notification(
                        msg.get("purpose", ""),
                        msg.get("image_path", ""),
                        msg.get("mode", "thumbnail"),
                    )
            except Exception as e:
                logger.debug(f"NotifySocket parse error: {e}")
            finally:
                conn.close()

        logger.info("NotifySocketServer loop ended")


def get_all_children(pid: int) -> list[str]:
    pids = []
    tmpPids = [str(pid)]
    try:
        while tmpPids:
            ppid = tmpPids.pop(0)
            cmd = ["ps", "--ppid", ppid, "-o", "pid="]
            with subprocess.Popen(cmd, stdout=subprocess.PIPE) as p:
                lines = p.stdout.readlines()

            for chldPid in lines:
                if isinstance(chldPid, bytes):
                    chldPid = chldPid.decode('utf-8')
                chldPid = chldPid.strip()
                if not chldPid:
                    continue
                pids.append(chldPid)
                tmpPids.append(chldPid)

        return pids
    except Exception as e:
        logger.error(f"Error finding child processes for pid {pid}: {e}")
        return pids


def get_base64_image(image_path):
    try:
        if not os.path.exists(image_path):
            logger.error(f"Image file does not exist: {image_path}")
            return ""

        file_size = os.path.getsize(image_path)
        if file_size > 10 * 1024 * 1024:
            logger.warning(f"Image file is very large ({file_size} bytes)")

        with open(image_path, "rb") as image_file:
            content = image_file.read()
            return base64.b64encode(content).decode('utf-8')
    except MemoryError:
        logger.error("Memory error encoding image, trying 1MB chunk")
        with open(image_path, "rb") as image_file:
            content = image_file.read(1024 * 1024)
            return base64.b64encode(content).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to convert image to base64: {e}")
        return ""


class Plugin:
    _filepath: str = None
    _screenshotPath: str = "/tmp/decky-translator"  # Temporary directory for screenshots (deleted after OCR)
    _settings = None
    _input_language: str = "auto"  # Default to auto-detect
    _target_language: str = "en"
    _input_mode: int = 0  # 0 = both touchpads, 1 = left touchpad, 2 = right touchpad
    _hold_time_translate: int = 1000  # Default to 1 second
    _hold_time_dismiss: int = 500  # Default to 0.5 seconds for dismissal
    _pause_game_on_overlay: bool = False  # Default to not pausing game on overlay
    _quick_toggle_enabled: bool = False  # Default to disabled for quick toggle

    # Hidraw button monitor
    _hidraw_monitor: HidrawButtonMonitor = None
    _evdev_monitor: EvdevGamepadMonitor = None

    # Agent CLI（デフォルト無効）
    _agent_enabled: bool = False
    _notify_server: NotifySocketServer = None

    # Provider system
    _provider_manager: ProviderManager = None

    # Gemini設定
    _gemini_base_url: str = ""
    _gemini_api_key: str = ""
    _gemini_model: str = ""
    _gemini_disable_thinking: bool = True
    _gemini_parallel: bool = True

    _vision_coordinate_mode: str = "pixel"

    # ゲーム別プロンプト（現在適用中）
    _current_game_vision_prompt: str = ""

    # Generic settings handlers
    async def get_setting(self, key, default=None):
        return self._settings.get_setting(key, default)

    def _effective_gemini_base_url(self) -> str:
        """設定未入力時は公式 Gemini エンドポイントを使う。"""
        return self._gemini_base_url or DEFAULT_GEMINI_BASE_URL

    async def set_setting(self, key, value):
        logger.debug(f"Setting {key} to: {value}")
        setting_key = key
        try:
            if key == "target_language":
                self._target_language = value
            elif key == "input_language":
                self._input_language = value
            elif key == "input_mode":
                self._input_mode = value
            elif key == "enabled":
                # No need to set an instance variable for this
                pass
            elif key in ("google_api_key", "google_vision_api_key", "google_translate_api_key"):
                logger.info(f"{key} は Gemini専用構成では未使用です")
            elif key == "hold_time_translate":
                self._hold_time_translate = value
            elif key == "hold_time_dismiss":
                self._hold_time_dismiss = value
            elif key in ("confidence_threshold", "rapidocr_confidence", "rapidocr_box_thresh", "rapidocr_unclip_ratio"):
                logger.info(f"{key} は Gemini専用構成では未使用です")
            elif key == "pause_game_on_overlay":
                self._pause_game_on_overlay = value
            elif key == "quick_toggle_enabled":
                self._quick_toggle_enabled = value
            elif key == "font_scale":
                pass  # frontend-only, just persist to settings file
            elif key == "grouping_power":
                pass  # frontend-only, just persist to settings file
            elif key == "hide_identical_translations":
                pass  # frontend-only, just persist to settings file
            elif key == "allow_label_growth":
                pass  # frontend-only, just persist to settings file
            elif key == "custom_recognition_settings":
                pass  # frontend-only, just persist to settings file
            elif key == "debug_mode":
                logger.setLevel(logging.DEBUG if value else logging.INFO)
            elif key == "agent_enabled":
                self._agent_enabled = bool(value)
                if value and not self._notify_server:
                    self._notify_server = NotifySocketServer(self._on_cli_notification)
                    self._notify_server.start()
                elif not value and self._notify_server:
                    self._notify_server.stop()
                    self._notify_server = None
                logger.info(f"Agent CLI {'有効' if value else '無効'}化")
            elif key in (
                "advanced_features_enabled",
                "pin_feature_enabled",
                "pin_shortcut_enabled",
                "pin_input_mode",
                "hold_time_pin",
                "translation_history_enabled_default",
                "pin_history_enabled_default",
            ):
                pass  # フロントエンド専用、永続化のみ
            elif key in ("gemini_base_url", "vision_llm_base_url", "text_llm_base_url", "llm_base_url"):
                self._gemini_base_url = value
                setting_key = "gemini_base_url"
                if self._provider_manager:
                    self._provider_manager.configure_vision(
                        base_url=self._effective_gemini_base_url(),
                    )
            elif key in ("gemini_api_key", "vision_llm_api_key", "text_llm_api_key", "llm_api_key"):
                self._gemini_api_key = value
                setting_key = "gemini_api_key"
                if self._provider_manager:
                    self._provider_manager.configure_vision(api_key=value)
            elif key in ("gemini_model", "vision_llm_model", "text_llm_model", "llm_model"):
                self._gemini_model = value
                setting_key = "gemini_model"
                if self._provider_manager:
                    self._provider_manager.configure_vision(model=value)
            elif key in ("gemini_disable_thinking", "vision_llm_disable_thinking", "text_llm_disable_thinking", "llm_disable_thinking"):
                self._gemini_disable_thinking = bool(value)
                setting_key = "gemini_disable_thinking"
                if self._provider_manager:
                    self._provider_manager.configure_vision(disable_thinking=bool(value))
            elif key in ("gemini_parallel", "vision_llm_parallel", "text_llm_parallel", "vision_parallel", "llm_parallel"):
                self._gemini_parallel = bool(value)
                setting_key = "gemini_parallel"
                if self._provider_manager:
                    self._provider_manager.configure_vision(parallel=bool(value))
            elif key == "llm_system_prompt":
                logger.warning("llm_system_prompt は廃止されました。Prompts タブから Gemini prompt を編集してください。")
            elif key in (
                "use_free_providers",
                "ocr_provider",
                "translation_provider",
                "vision_mode",
                "vision_assist_confidence_threshold",
                "vision_assist_send_all",
                "llm_image_rerecognition",
                "llm_image_send_all",
                "llm_image_confidence_threshold",
            ):
                logger.info(f"{key} は Gemini専用構成では未使用です")
            else:
                logger.warning(f"Unknown setting key: {key}")

            return self._settings.set_setting(setting_key, value)
        except Exception as e:
            logger.error(f"Error setting {key}: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    # プロンプトファイル機能

    def _ensure_vision_common_prompt_file(self):
        """vision-common.txt が存在しない場合、空ファイルを生成する。
        ファイルが存在すればその内容を読み込んで適用する。
        暗黙の意味論注入は行わない — ユーザーが明示的に書いた内容のみ適用。"""
        prompts_dir = self._get_prompts_dir()
        content = ensure_vision_common_file(prompts_dir)
        self._apply_common_vision_prompt(content)

    def _get_prompts_dir(self):
        """共通プロンプトファイルの保存ディレクトリを返す"""
        return os.path.join(settingsDir, "decky-translator-prompts")

    def _get_games_dir(self):
        """ゲーム別プロンプトファイルの保存ディレクトリを返す"""
        return os.path.join(settingsDir, "decky-translator-games")

    def _extract_prompt_from_content(self, content: str) -> str:
        """ファイル内容から1行目のメタ行を除去し、プロンプト部分のみ返す。"""
        return extract_prompt_from_content(content)

    def _apply_game_text_prompt(self, game_prompt: str):
        """旧互換。Gemini用ゲーム別 prompt と同じ内容を適用する。"""
        self._apply_game_vision_prompt(game_prompt)

    def _apply_game_vision_prompt(self, game_prompt: str):
        """ゲーム別 Gemini prompt をVision実装へ適用する"""
        self._current_game_vision_prompt = game_prompt
        if self._provider_manager:
            self._provider_manager.configure_vision(game_prompt=game_prompt)

    def _reload_common_prompts(self):
        """共通 Gemini prompt を再読み込みして適用する。"""
        prompts_dir = self._get_prompts_dir()
        vision_path = os.path.join(prompts_dir, "vision-common.txt")
        if os.path.exists(vision_path):
            with open(vision_path, 'r', encoding='utf-8-sig') as f:
                self._apply_common_vision_prompt(f.read().strip())

    def _apply_common_text_prompt(self, prompt: str):
        """旧互換。Gemini用共通 prompt と同じ内容を適用する。"""
        self._apply_common_vision_prompt(prompt)

    def _apply_common_vision_prompt(self, prompt: str):
        """共通 Gemini prompt をVision実装へ適用する"""
        if self._provider_manager:
            self._provider_manager.configure_vision(system_prompt=prompt)

    # --- 共通プロンプト API ---

    async def get_common_text_prompt(self):
        """旧互換。共通 Gemini prompt を返す。"""
        return await self.get_common_vision_prompt()

    async def save_common_text_prompt(self, content: str):
        """旧互換。共通 Gemini prompt を保存する。"""
        return await self.save_common_vision_prompt(content)

    async def get_common_vision_prompt(self):
        """共通Vision プロンプトの読み込み"""
        try:
            prompts_dir = self._get_prompts_dir()
            file_path = os.path.join(prompts_dir, "vision-common.txt")
            if not os.path.exists(file_path):
                return {"exists": False, "file_path": file_path, "content": ""}
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                content = f.read()
            return {"exists": True, "file_path": file_path, "content": content}
        except Exception as e:
            logger.error(f"共通Vision プロンプトの読み込みに失敗: {e}")
            return {"exists": False, "error": str(e)}

    async def save_common_vision_prompt(self, content: str):
        """共通Vision プロンプトの保存と適用"""
        try:
            prompts_dir = self._get_prompts_dir()
            os.makedirs(prompts_dir, exist_ok=True)
            file_path = os.path.join(prompts_dir, "vision-common.txt")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info("共通Vision プロンプトを保存")
            self._apply_common_vision_prompt(content.strip())
            return True
        except Exception as e:
            logger.error(f"共通Vision プロンプトの保存に失敗: {e}")
            logger.error(traceback.format_exc())
            return False

    # --- ゲーム別プロンプト API ---

    def _migrate_old_game_prompt(self, app_id: int):
        """旧形式のゲーム別 prompt を {app_id}/vision.txt へ移行する。"""
        migrate_old_game_prompt(self._get_games_dir(), app_id)

    async def ensure_game_text_prompt_file(self, app_id: int, display_name: str):
        """旧互換。ゲーム別 Gemini prompt を返す。"""
        return await self.ensure_game_vision_prompt_file(app_id, display_name)

    async def ensure_game_vision_prompt_file(self, app_id: int, display_name: str):
        """ゲーム別Vision プロンプトファイルを確保し、内容を読み込んで適用する"""
        # 翻訳履歴用にゲーム情報を保持
        self._current_app_id = app_id
        self._current_app_name = display_name
        try:
            games_dir = self._get_games_dir()
            game_dir = os.path.join(games_dir, str(app_id))
            os.makedirs(game_dir, exist_ok=True)
            self._migrate_old_game_prompt(app_id)
            file_path = os.path.join(game_dir, "vision.txt")

            if not os.path.exists(file_path):
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(f"--- {display_name} (App ID: {app_id}) Vision ---\n")
                logger.info(f"ゲーム別Vision プロンプトファイルを作成: {file_path}")

            with open(file_path, 'r', encoding='utf-8-sig') as f:
                content = f.read()

            prompt = self._extract_prompt_from_content(content)
            self._apply_game_vision_prompt(prompt)

            return {
                "app_id": app_id,
                "display_name": display_name,
                "file_path": file_path,
                "content": content,
                "prompt": prompt,
            }
        except Exception as e:
            logger.error(f"ゲーム別Vision プロンプトファイルの処理に失敗: {e}")
            logger.error(traceback.format_exc())
            return {"app_id": app_id, "error": str(e)}

    async def get_game_text_prompt(self, app_id: int):
        """旧互換。ゲーム別 Gemini prompt を返す。"""
        return await self.get_game_vision_prompt(app_id)

    async def get_game_vision_prompt(self, app_id: int):
        """ゲーム別Vision プロンプトファイルの内容を返す"""
        try:
            games_dir = self._get_games_dir()
            self._migrate_old_game_prompt(app_id)
            file_path = os.path.join(games_dir, str(app_id), "vision.txt")
            if not os.path.exists(file_path):
                return {"exists": False, "app_id": app_id}
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                content = f.read()
            prompt = self._extract_prompt_from_content(content)
            return {
                "exists": True,
                "app_id": app_id,
                "file_path": file_path,
                "content": content,
                "prompt": prompt,
            }
        except Exception as e:
            logger.error(f"ゲーム別Vision プロンプトの読み込みに失敗: {e}")
            return {"exists": False, "app_id": app_id, "error": str(e)}

    async def save_game_text_prompt(self, app_id: int, content: str):
        """旧互換。ゲーム別 Gemini prompt を保存する。"""
        return await self.save_game_vision_prompt(app_id, content)

    async def save_game_vision_prompt(self, app_id: int, content: str):
        """ゲーム別Vision プロンプトファイルを保存し、プロンプトを再適用する"""
        try:
            games_dir = self._get_games_dir()
            game_dir = os.path.join(games_dir, str(app_id))
            os.makedirs(game_dir, exist_ok=True)
            self._migrate_old_game_prompt(app_id)
            file_path = os.path.join(game_dir, "vision.txt")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"ゲーム別Vision プロンプトを保存: app_id={app_id}")
            prompt = self._extract_prompt_from_content(content)
            self._apply_game_vision_prompt(prompt)
            return True
        except Exception as e:
            logger.error(f"ゲーム別Vision プロンプトの保存に失敗: {e}")
            logger.error(traceback.format_exc())
            return False

    # --- 後方互換: 旧 API ---

    async def ensure_game_prompt_file(self, app_id: int, display_name: str):
        """旧API互換: ゲーム別 Gemini prompt ファイルを確保する。"""
        return await self.ensure_game_vision_prompt_file(app_id, display_name)

    async def get_game_prompt(self, app_id: int):
        """旧API互換: ゲーム別 Gemini prompt を返す。"""
        return await self.get_game_vision_prompt(app_id)

    async def save_game_prompt(self, app_id: int, content: str):
        """旧API互換: ゲーム別 Gemini prompt を保存する。"""
        return await self.save_game_vision_prompt(app_id, content)

    async def get_all_settings(self):
        try:
            settings = {
                "target_language": self._target_language,
                "input_language": self._input_language,
                "input_mode": self._input_mode,
                "enabled": self._settings.get_setting("enabled", True),
                "hold_time_translate": self._settings.get_setting("hold_time_translate", 1000),
                "hold_time_dismiss": self._settings.get_setting("hold_time_dismiss", 500),
                "pause_game_on_overlay": self._settings.get_setting("pause_game_on_overlay", False),
                "quick_toggle_enabled": self._settings.get_setting("quick_toggle_enabled", False),
                "debug_mode": self._settings.get_setting("debug_mode", False),
                "font_scale": self._settings.get_setting("font_scale", 1.0),
                "grouping_power": self._settings.get_setting("grouping_power", 0.25),
                "hide_identical_translations": self._settings.get_setting("hide_identical_translations", False),
                "allow_label_growth": self._settings.get_setting("allow_label_growth", False),
                "gemini_base_url": self._gemini_base_url,
                "gemini_api_key": self._gemini_api_key,
                "gemini_model": self._gemini_model,
                "agent_enabled": self._settings.get_setting("agent_enabled", False),
                "advanced_features_enabled": self._settings.get_setting("advanced_features_enabled", False),
                "pin_feature_enabled": self._settings.get_setting("pin_feature_enabled", False),
                "pin_shortcut_enabled": self._settings.get_setting("pin_shortcut_enabled", False),
                "pin_input_mode": self._settings.get_setting("pin_input_mode", None),
                "hold_time_pin": self._settings.get_setting("hold_time_pin", 1000),
                "translation_history_enabled_default": self._settings.get_setting("translation_history_enabled_default", True),
                "pin_history_enabled_default": self._settings.get_setting("pin_history_enabled_default", True),
            }
            return settings
        except Exception as e:
            logger.error(f"Error getting all settings: {str(e)}")
            logger.error(traceback.format_exc())
            return {}

    async def get_provider_status(self):
        """Gemini専用構成のプロバイダー状態を返す。"""
        try:
            if not self._provider_manager:
                return {"error": "Provider manager not initialized"}
            vision = self._provider_manager.get_vision_provider()
            return {
                "provider": "gemini_vision",
                "mode": "direct",
                "gemini_model": self._gemini_model,
                "gemini_base_url": self._effective_gemini_base_url(),
                "gemini_api_key_set": bool(self._gemini_api_key),
                "vision_available": vision.is_available() if vision else False,
            }
        except Exception as e:
            logger.error(f"Error getting provider status: {str(e)}")
            return {"error": str(e)}

    async def take_screenshot(self, app_name: str = ""):
        logger.debug(f"Taking screenshot for app: {app_name}")
        global _processing_lock

        if _processing_lock:
            logger.info("Screenshot already in progress, skipping")
            raise RuntimeError("Screenshot already in progress")

        # Minimal test‑pattern in case encoding fails or file isn't created
        test_base64 = (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mNk+M9Qz0AEYBxVSF+"
            "FABJADveWyWxwAAAAAElFTkSuQmCC"
        )

        try:
            _processing_lock = True

            # Sanitize and default app name
            if not app_name or app_name.strip().lower() == "null":
                app_name = "Decky-Screenshot"
            else:
                app_name = app_name.replace(":", " ").replace("/", " ").strip()

            # Build filename
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            os.makedirs(self._screenshotPath, exist_ok=True)
            screenshot_path = f"{self._screenshotPath}/{app_name}_{timestamp}.png"
            logger.debug(f"Screenshot path: {screenshot_path}")

            # Prepare environment
            env = os.environ.copy()
            env.update({
                "XDG_RUNTIME_DIR": "/run/user/1000",
                "XDG_SESSION_TYPE": "wayland",
                "HOME": DECKY_HOME
            })

            # GStreamer pipeline: grab a few frames then EOS
            # Using num-buffers=5 to skip potentially invalid first frames from PipeWire
            cmd = (
                # keep only the path to your plugins, without GST_VAAPI_ALL_DRIVERS
                f"GST_PLUGIN_PATH={GSTPLUGINSPATH} "
                f"LD_LIBRARY_PATH={DEPSPATH} "
                f"gst-launch-1.0 -e "
                # capture multiple buffers to ensure valid frame (pngenc snapshot=true saves last)
                f"pipewiresrc do-timestamp=true num-buffers=5 ! "
                # let videoconvert work by default (CPU), it will create normal raw
                f"videoconvert ! "
                # then directly to PNG
                f"pngenc snapshot=true ! "
                f"filesink location=\"{screenshot_path}\""
            )
            logger.debug(f"GStreamer command: {cmd}")

            # Launch subprocess asynchronously
            proc = await asyncio.create_subprocess_exec(
                'gst-launch-1.0',
                '-e',
                'pipewiresrc',
                'do-timestamp=true',
                'num-buffers=5',
                '!',
                'videoconvert',
                '!',
                'pngenc',
                'snapshot=true',
                '!',
                'filesink',
                f'location={screenshot_path}',
                stdout=PIPE,
                stderr=PIPE,
                env=env
            )
            # Wait for pipeline to finish (it will exit after 1 frame), with timeout
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning("GStreamer timed out after 5s, sending SIGINT for graceful shutdown")
                proc.send_signal(signal.SIGINT)
                try:
                    # give 2 more seconds to finish after SIGINT
                    out, err = await asyncio.wait_for(proc.communicate(), timeout=2)
                except asyncio.TimeoutError:
                    logger.error("GStreamer did not exit within 2s after SIGINT, killing process")
                    proc.kill()
                    out, err = await proc.communicate()

            logger.debug(f"GStreamer stdout: {out.decode().strip() or 'None'}")
            stderr_output = err.decode().strip()
            if stderr_output:
                logger.debug(f"GStreamer stderr: {stderr_output}")
            logger.debug(f"GStreamer return code: {proc.returncode}")

            # Give the filesystem a moment - seems to work without it
            # await asyncio.sleep(0.25)

            # Check file and return
            if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 0:
                size = os.path.getsize(screenshot_path)
                logger.debug(f"Screenshot saved ({size} bytes)")
                base64_data = get_base64_image(screenshot_path)
                if base64_data:
                    return {"path": screenshot_path, "base64": base64_data}
                else:
                    logger.error("Failed to encode screenshot to base64 — returning test pattern")
                    return {"path": screenshot_path, "base64": test_base64}
            else:
                logger.error(f"Screenshot file missing or empty: {screenshot_path}")
                return {"path": "", "base64": test_base64}

        except Exception as e:
            logger.error(f"Screenshot error: {e}")
            logger.error(traceback.format_exc())
            return {"path": "", "base64": test_base64}

        finally:
            _processing_lock = False

    async def saveConfig(self):
        try:
            if not self._settings:
                logger.error("Cannot save config - settings not initialized")
                return False

            results = [
                self._settings.set_setting("target_language", self._target_language),
                self._settings.set_setting("input_mode", self._input_mode),
                self._settings.set_setting("input_language", self._input_language),
                self._settings.set_setting("hold_time_translate", self._hold_time_translate),
                self._settings.set_setting("hold_time_dismiss", self._hold_time_dismiss),
                self._settings.set_setting("pause_game_on_overlay", self._pause_game_on_overlay),
                self._settings.set_setting("quick_toggle_enabled", self._quick_toggle_enabled),
            ]
            return all(results)
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            logger.error(traceback.format_exc())
            return False

    async def is_paused(self, pid: int) -> bool:
        try:
            cmd = ["ps", "--pid", str(pid), "-o", "stat="]
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as p:
                stdout, stderr = p.communicate()
                status = stdout.lstrip().decode('utf-8')
                return status.startswith('T')
        except Exception as e:
            logger.error(f"is_paused: Error checking pause status: {e}")
            logger.error(traceback.format_exc())
            return False

    async def pause(self, pid: int) -> bool:
        logger.debug(f"Pausing process {pid}")
        if not pid:
            return False

        pids = get_all_children(pid)
        if pids:
            pids.insert(0, str(pid))
            command = ["kill", "-SIGSTOP"]
            command.extend(pids)
            try:
                result = subprocess.run(command, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
                return result.returncode == 0
            except Exception as e:
                logger.error(f"Error pausing process {pid}: {e}")
                return False
        else:
            try:
                command = ["kill", "-SIGSTOP", str(pid)]
                result = subprocess.run(command, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
                return result.returncode == 0
            except Exception as e:
                logger.error(f"Error pausing process {pid}: {e}")
                return False

    async def resume(self, pid: int) -> bool:
        logger.debug(f"Resuming process {pid}")
        if not pid:
            return False

        pids = get_all_children(pid)
        if pids:
            pids.insert(0, str(pid))
            command = ["kill", "-SIGCONT"]
            command.extend(pids)
            try:
                result = subprocess.run(command, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
                return result.returncode == 0
            except Exception as e:
                logger.error(f"Error resuming process {pid}: {e}")
                return False
        else:
            try:
                command = ["kill", "-SIGCONT", str(pid)]
                result = subprocess.run(command, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
                return result.returncode == 0
            except Exception as e:
                logger.error(f"Error resuming process {pid}: {e}")
                return False

    async def terminate(self, pid: int) -> bool:
        pids = get_all_children(pid)
        if pids:
            command = ["kill", "-SIGTERM"]
            command.extend(pids)
            try:
                return subprocess.run(command, stderr=sys.stderr, stdout=sys.stdout).returncode == 0
            except:
                return False
        else:
            return False

    async def kill(self, pid: int) -> bool:
        pids = get_all_children(pid)
        if pids:
            command = ["kill", "-SIGKILL"]
            command.extend(pids)
            try:
                return subprocess.run(command, stderr=sys.stderr, stdout=sys.stdout).returncode == 0
            except:
                return False
        else:
            return False

    async def pid_from_appid(self, appid: int) -> int:
        pid = ""
        try:
            cmd = ["pgrep", "--full", "--oldest", f"/reaper\\s.*\\bAppId={appid}\\b"]
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as p:
                stdout, stderr = p.communicate()
                pid = stdout.strip()

            if not pid:
                cmd = ["pgrep", "-f", f"GameId={appid}"]
                with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as p:
                    stdout, stderr = p.communicate()
                    pid = stdout.strip()

            if pid:
                return int(pid)
            else:
                logger.debug(f"No process found for AppId={appid}")
                return 0
        except Exception as e:
            logger.error(f"Error finding pid for AppId={appid}: {e}")
            return 0

    async def appid_from_pid(self, pid: int) -> int:
        logger.debug(f"Looking for AppId with pid={pid}")
        while pid and pid != 1:
            try:
                with open(f"/proc/{pid}/cmdline", "r") as f:
                    args = f.read().split('\0')

                for arg in args:
                    arg = arg.strip()
                    if arg.startswith("AppId="):
                        arg = arg.lstrip("AppId=")
                        if arg:
                            logger.debug(f"Found AppId={arg} for pid={pid}")
                            return int(arg)
            except Exception:
                pass

            try:
                cmd = ["ps", "--pid", str(pid), "-o", "ppid="]
                with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as p:
                    stdout, _ = p.communicate()
                    strppid = stdout.strip()

                if strppid:
                    pid = int(strppid)
                else:
                    break
            except Exception as e:
                logger.error(f"Error finding parent for pid={pid}: {e}")
                break

        logger.debug(f"No AppId found for pid={pid}")
        return 0

    # --- 旧互換RPC（deprecated） ---
    # Gemini専用構成では vision_translate が正式経路。
    # 以下はフロントエンドの TextRecognizer.tsx から参照が残っているため、
    # エラーにならないよう空実装で残す。次段で TextRecognizer.tsx ごと削除予定。

    async def recognize_text(self, image_data: str):
        """deprecated: Gemini専用構成では未使用。vision_translate を使用してください。"""
        logger.warning("recognize_text は deprecated です。vision_translate を使用してください。")
        return []

    async def recognize_text_file(self, image_path: str):
        """deprecated: Gemini専用構成では未使用。vision_translate を使用してください。"""
        logger.warning("recognize_text_file は deprecated です。vision_translate を使用してください。")
        # 一時ファイルの後始末だけは行う
        if image_path and os.path.exists(image_path):
            try:
                os.remove(image_path)
            except Exception:
                pass
        return []

    async def delete_screenshot(self, image_path: str):
        """一時スクリーンショットファイルを削除する。Vision direct経路など、
        recognize_text_file を経由しない場合に使用。"""
        if image_path and os.path.exists(image_path):
            try:
                os.remove(image_path)
                logger.debug(f"Deleted temporary screenshot: {image_path}")
                return True
            except Exception as e:
                logger.warning(f"Failed to delete temporary screenshot: {e}")
                return False
        return True

    async def translate_text(self, text_regions, target_language=None, input_language=None, image_data=None):
        """deprecated: Gemini専用構成では未使用。vision_translate を使用してください。"""
        logger.warning("translate_text は deprecated です。vision_translate を使用してください。")
        return []

    async def preflight_vision_check(self, mode: str = None):
        """Vision Translationの事前検証RPC。Vision+JSON対応のみ確認。
        mode引数でoff→direct等の遷移前検証を可能にする。"""
        try:
            if not self._provider_manager:
                return {"ok": False, "message": "Provider manager not initialized"}
            return await self._provider_manager.preflight_vision_check(mode=mode)
        except Exception as e:
            logger.error(f"Vision preflight error: {e}")
            logger.error(traceback.format_exc())
            return {"ok": False, "message": str(e)}

    async def vision_translate(self, image_data, target_language=None, input_language=None):
        """Vision Translation: スクリーンショットから直接テキスト検出+翻訳。OCRバイパス。"""
        try:
            # SSH編集対応: 翻訳前に共通プロンプトを再読み込み
            self._reload_common_prompts()
            if not image_data:
                return {"error": "vision_failed", "message": "No image data"}

            target_lang = target_language or self._target_language
            input_lang = input_language or self._input_language

            if not self._provider_manager:
                return {"error": "vision_failed", "message": "Provider manager not initialized"}

            # Base64デコード
            img_str = image_data
            if img_str.startswith('data:image'):
                img_str = img_str.split(',', 1)[1]
            image_bytes = base64.b64decode(img_str)

            # 画像サイズ取得（システムPythonサブプロセス）
            image_width, image_height = await self._get_image_size(image_bytes)
            if not image_width or not image_height:
                return {"error": "vision_failed", "message": "Failed to get image dimensions"}

            start_time = time.time()
            result = await self._provider_manager.recognize_and_translate(
                image_bytes, input_lang, target_lang,
                image_width, image_height,
            )
            elapsed = time.time() - start_time

            if result is None:
                logger.warning(f"Vision Translation失敗 ({elapsed:.2f}s)")
                return {"error": "vision_failed", "message": "Vision translation returned no results"}

            logger.info(f"Vision Translation完了: {len(result)} regions in {elapsed:.2f}s")

            # 翻訳履歴の保存
            try:
                if self._settings.get_setting("translation_history_enabled_default", True):
                    app_id = getattr(self, "_current_app_id", None)
                    app_name = getattr(self, "_current_app_name", "") or ""
                    if app_id:
                        translation_history.log_translation(
                            log_dir=DECKY_PLUGIN_LOG_DIR,
                            app_id=str(app_id),
                            app_name=app_name,
                            source="overlay",
                            target_lang=target_lang,
                            input_lang=input_lang,
                            regions=result,
                        )
            except Exception as hist_err:
                logger.debug(f"翻訳履歴保存失敗（翻訳自体は成功）: {hist_err}")

            return result

        except NetworkError as e:
            logger.error(f"Network error during vision translation: {e}")
            return {"error": "network_error", "message": str(e)}
        except ApiKeyError as e:
            logger.error(f"API key error during vision translation: {e}")
            return {"error": "api_key_error", "message": "Invalid API key"}
        except Exception as e:
            logger.error(f"Vision translation error: {e}")
            logger.error(traceback.format_exc())
            return {"error": "vision_failed", "message": str(e)}

    # --- ピン機能 RPC ---

    async def pin_capture(self, app_id: int, game_name: str = "", image_data: str = None, trigger: str = "button"):
        """スクリーンショットをピンとして保存し、バックグラウンドで Gemini 解析する。"""
        try:
            pin_id = pin_history.generate_pin_id()
            capture_source = "reuse" if image_data else "live_capture"

            # 画像データの取得
            if image_data:
                img_str = image_data
                if img_str.startswith('data:image'):
                    img_str = img_str.split(',', 1)[1]
                image_bytes = base64.b64decode(img_str)
            else:
                # バックエンドでスクリーンショット取得
                screenshot_result = await self.take_screenshot(game_name or "pin")
                if not screenshot_result or not isinstance(screenshot_result, dict):
                    return {"ok": False, "error": "スクリーンショット取得失敗"}
                img_str = screenshot_result.get("base64", "")
                if not img_str:
                    return {"ok": False, "error": "スクリーンショットのbase64が空"}
                if img_str.startswith('data:image'):
                    img_str = img_str.split(',', 1)[1]
                image_bytes = base64.b64decode(img_str)
                # 一時スクリーンショットを削除
                tmp_path = screenshot_result.get("path", "")
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

            # pin_history_enabled_default が OFF なら保存しない
            if not self._settings.get_setting("pin_history_enabled_default", True):
                return {"ok": False, "error": "Pin history is disabled"}

            # 永続画像保存
            image_path = pin_history.save_image(
                DECKY_PLUGIN_LOG_DIR, str(app_id), pin_id, image_bytes
            )

            # pending レコードを保存
            record = pin_history.create_pin_record(
                pin_id=pin_id,
                app_id=app_id,
                game_name=game_name,
                trigger=trigger,
                capture_source=capture_source,
                image_path=image_path,
                analysis_status="pending",
                analysis_model=self._gemini_model,
                input_language=self._input_language,
                target_language=self._target_language,
            )
            pin_history.append_record(DECKY_PLUGIN_LOG_DIR, str(app_id), record)

            # バックグラウンドで Gemini 解析
            asyncio.create_task(self._pin_analyze(
                pin_id, str(app_id), image_bytes
            ))

            return {
                "ok": True,
                "pin_id": pin_id,
                "image_path": image_path,
                "analysis_status": "pending",
            }
        except Exception as e:
            logger.error(f"pin_capture エラー: {e}")
            logger.error(traceback.format_exc())
            return {"ok": False, "error": str(e)}

    async def _pin_analyze(self, pin_id: str, app_id: str, image_bytes: bytes):
        """ピンのバックグラウンド Gemini 解析。結果をレコードに反映する。"""
        try:
            target_lang = self._target_language
            input_lang = self._input_language

            # 言語未設定チェック
            if not target_lang or not self._gemini_api_key:
                pin_history.update_record(DECKY_PLUGIN_LOG_DIR, app_id, pin_id, {
                    "analysis_status": "skipped_config_missing",
                    "regions": [],
                    "recognized_text": "",
                    "translated_text": "",
                    "search_text": "",
                })
                logger.info(f"ピン解析スキップ（設定不足）: {pin_id}")
                return

            if not self._provider_manager:
                pin_history.update_record(DECKY_PLUGIN_LOG_DIR, app_id, pin_id, {
                    "analysis_status": "failed",
                    "error": "Provider manager not initialized",
                })
                return

            # 画像サイズ取得
            image_width, image_height = await self._get_image_size(image_bytes)
            if not image_width or not image_height:
                pin_history.update_record(DECKY_PLUGIN_LOG_DIR, app_id, pin_id, {
                    "analysis_status": "failed",
                    "error": "画像サイズ取得失敗",
                })
                return

            # Gemini 解析（vision_translate と同じ経路）
            self._reload_common_prompts()
            result = await self._provider_manager.recognize_and_translate(
                image_bytes, input_lang, target_lang,
                image_width, image_height,
            )

            if result is None:
                pin_history.complete_analysis(
                    DECKY_PLUGIN_LOG_DIR, app_id, pin_id,
                    regions=[], error="Gemini解析結果なし",
                )
                logger.warning(f"ピン解析失敗: {pin_id}")
                return

            # 解析成功
            pin_history.complete_analysis(
                DECKY_PLUGIN_LOG_DIR, app_id, pin_id,
                regions=result, model=self._gemini_model,
            )
            logger.info(f"ピン解析完了: {pin_id}, {len(result)} regions")

        except Exception as e:
            logger.error(f"ピン解析エラー ({pin_id}): {e}")
            logger.error(traceback.format_exc())
            pin_history.complete_analysis(
                DECKY_PLUGIN_LOG_DIR, app_id, pin_id,
                regions=[], error=str(e),
            )

    async def list_pin_history(self, app_id: int, limit: int = 20):
        """直近のピン履歴を返す。"""
        try:
            return pin_history.list_recent(DECKY_PLUGIN_LOG_DIR, str(app_id), limit)
        except Exception as e:
            logger.error(f"list_pin_history エラー: {e}")
            return []

    async def get_pin_history_status(self, app_id: int):
        """ピン履歴の件数・サイズ情報を返す。"""
        try:
            return pin_history.get_history_info(DECKY_PLUGIN_LOG_DIR, str(app_id))
        except Exception as e:
            logger.error(f"get_pin_history_status エラー: {e}")
            return {"app_id": str(app_id), "count": 0, "total_size_bytes": 0}

    async def search_pin_history(self, app_id: int, keyword: str, limit: int = 50):
        """キーワードでピン履歴を検索する。"""
        try:
            return pin_history.search_history(DECKY_PLUGIN_LOG_DIR, str(app_id), keyword, limit)
        except Exception as e:
            logger.error(f"search_pin_history エラー: {e}")
            return []

    async def get_translation_history_status(self, app_id: int):
        """翻訳履歴の件数・サイズ情報を返す。"""
        try:
            return translation_history.get_game_history_info(
                DECKY_PLUGIN_LOG_DIR, settingsDir, str(app_id)
            )
        except Exception as e:
            logger.error(f"get_translation_history_status エラー: {e}")
            return {"app_id": str(app_id), "count": 0, "size_bytes": 0}

    async def delete_pin_history_for_game(self, app_id: int):
        """ゲーム単位でピン履歴を削除する。"""
        try:
            return pin_history.delete_game_pins(DECKY_PLUGIN_LOG_DIR, str(app_id))
        except Exception as e:
            logger.error(f"delete_pin_history_for_game エラー: {e}")
            return {"deleted": False, "error": str(e)}

    async def delete_translation_history_for_game(self, app_id: int):
        """ゲーム単位で翻訳履歴を削除する。"""
        try:
            return translation_history.delete_game_history(DECKY_PLUGIN_LOG_DIR, str(app_id))
        except Exception as e:
            logger.error(f"delete_translation_history_for_game エラー: {e}")
            return {"deleted": False, "error": str(e)}

    async def _get_image_size(self, image_bytes: bytes) -> tuple:
        """画像バイトデータからサイズ(width, height)を取得する。
        PILが使えないDecky環境のため、PNGヘッダから直接読み取る。"""
        try:
            import struct
            # PNGシグネチャ確認
            if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
                # IHDRチャンクからwidth, height取得（オフセット16-24）
                width = struct.unpack('>I', image_bytes[16:20])[0]
                height = struct.unpack('>I', image_bytes[20:24])[0]
                logger.debug(f"Image size from PNG header: {width}x{height}")
                return width, height

            # PNG以外の場合はサブプロセスでPIL使用
            import subprocess
            python_path = ""
            for path in ['/usr/bin/python3', '/usr/bin/python3.13', '/usr/local/bin/python3']:
                import os
                if os.path.exists(path) and os.access(path, os.X_OK):
                    python_path = path
                    break
            if not python_path:
                logger.error("システムPythonが見つかりません")
                return (None, None)

            script = "import sys,io;from PIL import Image;d=sys.stdin.buffer.read();i=Image.open(io.BytesIO(d));print(f'{i.size[0]} {i.size[1]}')"
            result = subprocess.run(
                [python_path, '-S', '-c', script],
                input=image_bytes, capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                parts = result.stdout.decode().strip().split()
                return int(parts[0]), int(parts[1])
            return (None, None)
        except Exception as e:
            logger.error(f"画像サイズ取得エラー: {e}")
            return (None, None)

    async def get_enabled_state(self):
        return await self.get_setting("enabled", True)

    async def set_enabled_state(self, enabled):
        return await self.set_setting("enabled", enabled)

    async def get_input_language(self):
        return self._input_language

    async def set_input_language(self, language):
        return await self.set_setting("input_language", language)

    async def get_confidence_threshold(self):
        """deprecated: Gemini専用構成では未使用。"""
        return 0.6

    async def set_confidence_threshold(self, threshold: float):
        """deprecated: Gemini専用構成では未使用。"""
        return True

    async def get_pause_game_on_overlay(self):
        return self._pause_game_on_overlay

    async def set_pause_game_on_overlay(self, enabled: bool):
        self._pause_game_on_overlay = enabled
        return await self.set_setting("pause_game_on_overlay", enabled)

    async def get_target_language(self):
        return self._target_language

    async def set_target_language(self, language):
        return await self.set_setting("target_language", language)

    async def get_input_mode(self):
        return self._input_mode

    async def set_input_mode(self, mode):
        return await self.set_setting("input_mode", mode)

    async def start_hidraw_monitor(self):
        try:
            if self._hidraw_monitor is None:
                self._hidraw_monitor = HidrawButtonMonitor()

            if self._hidraw_monitor.running:
                hidraw_ok = True
            elif self._hidraw_monitor.start():
                hidraw_ok = True
            else:
                hidraw_ok = False

            # Start evdev monitor for external gamepads
            if EVDEV_AVAILABLE:
                if self._evdev_monitor is None:
                    self._evdev_monitor = EvdevGamepadMonitor()
                if not self._evdev_monitor.running:
                    self._evdev_monitor.start()

            if hidraw_ok:
                return {"success": True, "message": "Monitor started"}
            else:
                return {"success": False, "error": "Failed to initialize device"}
        except Exception as e:
            logger.error(f"Error starting hidraw monitor: {e}")
            return {"success": False, "error": str(e)}

    async def stop_hidraw_monitor(self):
        try:
            if self._hidraw_monitor:
                self._hidraw_monitor.stop()
            if self._evdev_monitor:
                self._evdev_monitor.stop()
            return {"success": True, "message": "Monitor stopped"}
        except Exception as e:
            logger.error(f"Error stopping hidraw monitor: {e}")
            return {"success": False, "error": str(e)}

    async def get_hidraw_events(self, max_events: int = 10):
        """Get pending button events from the hidraw monitor."""
        try:
            if self._hidraw_monitor and self._hidraw_monitor.running:
                events = self._hidraw_monitor.get_events(max_events)
                return {"success": True, "events": events}
            return {"success": False, "events": [], "error": "Monitor not running"}
        except Exception as e:
            logger.error(f"Error getting hidraw events: {e}")
            return {"success": False, "events": [], "error": str(e)}

    async def get_hidraw_button_state(self):
        """Get the current complete button state from both monitors.

        Merges button state from hidraw (built-in controller) and evdev
        (external gamepads) via set union.
        """
        try:
            buttons = set()
            any_running = False

            if self._hidraw_monitor and self._hidraw_monitor.running:
                any_running = True
                buttons.update(self._hidraw_monitor.get_button_state())

            if self._evdev_monitor and self._evdev_monitor.running:
                any_running = True
                buttons.update(self._evdev_monitor.get_button_state())

            if any_running:
                return {"success": True, "buttons": list(buttons)}
            return {"success": False, "buttons": [], "error": "Monitor not running"}
        except Exception as e:
            logger.error(f"Error getting hidraw button state: {e}")
            return {"success": False, "buttons": [], "error": str(e)}

    async def get_hidraw_status(self):
        """Get hidraw and evdev monitor status for diagnostics."""
        try:
            status = {}
            if self._hidraw_monitor:
                status["hidraw"] = self._hidraw_monitor.get_status()
            else:
                status["hidraw"] = {"running": False, "initialized": False}

            if self._evdev_monitor:
                status["evdev"] = self._evdev_monitor.get_status()
            else:
                status["evdev"] = {"running": False, "available": EVDEV_AVAILABLE}

            return {"success": True, "status": status}
        except Exception as e:
            logger.error(f"Error getting hidraw status: {e}")
            return {"success": False, "error": str(e)}

    # --- Agent RPC: 外部AI / CLI 向け読み取り専用インターフェース ---

    # 通知キュー（フロントエンドがポーリングで取得）
    _agent_notifications: list = []

    def _agent_notify(self, mode: str = "dot", purpose: str = "", thumbnail: str = None):
        """Agent操作の通知をキューに追加する。

        mode: "dot" | "thumbnail" | "message"
        """
        from agent_core import _now_iso
        notification = {
            "mode": mode,
            "timestamp": _now_iso(),
        }
        if purpose:
            notification["purpose"] = purpose[:100]
        if thumbnail:
            notification["thumbnail"] = thumbnail
        self._agent_notifications.append(notification)
        # 古い通知を捨てる（最大10件）
        if len(self._agent_notifications) > 10:
            self._agent_notifications = self._agent_notifications[-10:]

    def _on_cli_notification(self, purpose: str, image_path: str, mode: str = "thumbnail"):
        """CLI からの UDS 通知コールバック。"""
        thumbnail = None
        if mode in ("thumbnail",) and image_path and os.path.exists(image_path):
            b64 = get_base64_image(image_path)
            if b64:
                thumbnail = f"data:image/png;base64,{b64}"
        self._agent_notify(mode=mode, purpose=purpose, thumbnail=thumbnail)
        logger.info(f"CLI通知受信 [{mode}]: {purpose[:50]}")

    async def agent_poll_notifications(self):
        """未読の通知を返してキューをクリアする。フロントエンドがポーリングで呼ぶ。"""
        notifications = list(self._agent_notifications)
        self._agent_notifications.clear()
        return notifications

    async def agent_ping(self):
        """疎通確認。"""
        return {"ok": True}

    async def agent_get_capabilities(self):
        """利用可能な機能一覧を返す。"""
        from agent_core import get_capabilities
        return get_capabilities()

    async def agent_get_running_game(self):
        """現在起動中のゲーム情報を返す。
        フロントエンドから Router.MainRunningApp 経由で取得した情報を返す。
        ゲーム情報はフロントエンドのみが持つため、キャッシュされた値を返す。"""
        return {
            "ok": True,
            "action": "game",
            "game": {
                "app_id": getattr(self, "_current_app_id", None),
                "display_name": getattr(self, "_current_app_name", None),
            },
        }

    async def agent_set_running_game(self, app_id, display_name):
        """フロントエンドからゲーム情報を受け取ってキャッシュする。"""
        self._current_app_id = app_id
        self._current_app_name = display_name
        # CLI向けにファイルにも書き出す
        from agent_core import write_running_game
        write_running_game(app_id, display_name)
        logger.debug(f"Agent: ゲーム情報更新 app_id={app_id}, name={display_name}")
        return True

    def _check_agent_enabled(self, action: str) -> dict:
        """Agent CLI が無効の場合エラー応答を返す。有効なら None。"""
        if not self._agent_enabled:
            return {"ok": False, "action": action,
                    "error": {"code": "agent_disabled", "message": "Agent CLI is disabled"}}
        return None

    async def agent_capture_screen(self, purpose: str):
        """スクリーンショットを取得する。purposeは必須。"""
        err = self._check_agent_enabled("capture")
        if err:
            return err
        if not purpose:
            return {"ok": False, "action": "capture",
                    "error": {"code": "missing_purpose", "message": "purposeは必須です"}}

        from agent_core import capture_screenshot, make_success_response, make_error_response

        logger.info(f"Agent capture: {purpose[:100]}")
        self._agent_notify(mode="dot", purpose=purpose)

        app_name = getattr(self, "_current_app_name", "") or ""

        result = await capture_screenshot(
            app_name=app_name,
            plugin_dir=DECKY_PLUGIN_DIR,
            decky_home=DECKY_HOME,
        )

        if "error" in result:
            return make_error_response("capture", result["error"], result["message"], purpose)

        game_info = await self.agent_get_running_game()
        return make_success_response(
            "capture",
            purpose=purpose,
            captured_at=result["captured_at"],
            game=game_info.get("game", {}),
            image={
                "path": result["path"],
                "base64": f"data:image/png;base64,{result['base64']}",
            },
        )

    async def agent_translate_screen(self, purpose: str, target_language: str = None, input_language: str = None):
        """スクリーンショットを取得してVision翻訳する。"""
        err = self._check_agent_enabled("translate")
        if err:
            return err
        if not purpose:
            return {"ok": False, "action": "translate",
                    "error": {"code": "missing_purpose", "message": "purposeは必須です"}}

        from agent_core import capture_screenshot, translate_screen, make_success_response, make_error_response

        logger.info(f"Agent translate: {purpose[:100]}")
        self._agent_notify(mode="dot", purpose=purpose)

        # 共通プロンプト再読み込み
        self._reload_common_prompts()

        app_name = getattr(self, "_current_app_name", "") or ""

        # スクリーンショット取得
        cap_result = await capture_screenshot(
            app_name=app_name,
            plugin_dir=DECKY_PLUGIN_DIR,
            decky_home=DECKY_HOME,
        )
        if "error" in cap_result:
            return make_error_response("translate", cap_result["error"], cap_result["message"], purpose)

        # 翻訳
        target = target_language or self._target_language
        input_lang = input_language or self._input_language

        tr_result = await translate_screen(
            self._provider_manager, cap_result["base64"], target, input_lang,
        )

        # 一時ファイル削除
        if cap_result.get("path") and os.path.exists(cap_result["path"]):
            try:
                os.remove(cap_result["path"])
            except Exception:
                pass

        if "error" in tr_result:
            return make_error_response("translate", tr_result["error"], tr_result["message"], purpose)

        game_info = await self.agent_get_running_game()
        return make_success_response(
            "translate",
            purpose=purpose,
            captured_at=cap_result["captured_at"],
            game=game_info.get("game", {}),
            regions=tr_result["regions"],
        )

    async def agent_describe_screen(self, purpose: str, prompt: str = None):
        """スクリーンショットを取得して攻略支援向け画面説明を返す。"""
        err = self._check_agent_enabled("describe")
        if err:
            return err
        if not purpose:
            return {"ok": False, "action": "describe",
                    "error": {"code": "missing_purpose", "message": "purposeは必須です"}}

        from agent_core import capture_screenshot, describe_screen, make_success_response, make_error_response

        logger.info(f"Agent describe: {purpose[:100]}")
        self._agent_notify(mode="dot", purpose=purpose)

        # 共通プロンプト再読み込み
        self._reload_common_prompts()

        app_name = getattr(self, "_current_app_name", "") or ""

        # スクリーンショット取得
        cap_result = await capture_screenshot(
            app_name=app_name,
            plugin_dir=DECKY_PLUGIN_DIR,
            decky_home=DECKY_HOME,
        )
        if "error" in cap_result:
            return make_error_response("describe", cap_result["error"], cap_result["message"], purpose)

        # 画面説明
        desc_result = await describe_screen(
            self._provider_manager, cap_result["base64"], prompt=prompt,
        )

        # 一時ファイル削除
        if cap_result.get("path") and os.path.exists(cap_result["path"]):
            try:
                os.remove(cap_result["path"])
            except Exception:
                pass

        if "error" in desc_result:
            return make_error_response("describe", desc_result["error"], desc_result["message"], purpose)

        game_info = await self.agent_get_running_game()
        return make_success_response(
            "describe",
            purpose=purpose,
            captured_at=cap_result["captured_at"],
            game=game_info.get("game", {}),
            description=desc_result["description"],
        )

    async def _main(self):
        logger.info("Plugin initialization started")
        try:
            self._settings = SettingsManager(
                name="decky-translator-settings",
                settings_directory=settingsDir
            )
            self._settings.read()

            def load_setting(key, default):
                saved = self._settings.get_setting(key)
                if saved is not None:
                    return saved
                self._settings.set_setting(key, default)
                return default

            # Load basic settings
            self._target_language = load_setting("target_language", self._target_language)
            self._input_language = load_setting("input_language", self._input_language)
            self._input_mode = load_setting("input_mode", self._input_mode)
            self._hold_time_translate = load_setting("hold_time_translate", self._hold_time_translate)
            self._hold_time_dismiss = load_setting("hold_time_dismiss", self._hold_time_dismiss)
            self._pause_game_on_overlay = load_setting("pause_game_on_overlay", self._pause_game_on_overlay)
            self._quick_toggle_enabled = load_setting("quick_toggle_enabled", self._quick_toggle_enabled)

            os.makedirs(self._screenshotPath, exist_ok=True)

            # Gemini設定を読み込み（gemini_* > vision_llm_* > text_llm_* > llm_* の順でフォールバック）
            getter = self._settings.get_setting
            self._gemini_base_url = normalize_gemini_setting(getter, "base_url", default="")
            self._gemini_api_key = normalize_gemini_setting(getter, "api_key", default="")
            self._gemini_model = normalize_gemini_setting(getter, "model", default="")
            self._gemini_disable_thinking = normalize_gemini_setting(getter, "disable_thinking", default=True)
            self._gemini_parallel = normalize_gemini_setting(getter, "parallel", default=True)
            self._vision_coordinate_mode = self._settings.get_setting(
                "vision_coordinate_mode",
                self._settings.get_setting("llm_coordinate_mode", "pixel")
            )
            self._settings.set_setting("gemini_base_url", self._gemini_base_url)
            self._settings.set_setting("gemini_api_key", self._gemini_api_key)
            self._settings.set_setting("gemini_model", self._gemini_model)

            # Initialize provider manager（Gemini Vision直結）
            self._provider_manager = ProviderManager()
            self._provider_manager.configure_vision(
                mode="direct",
                base_url=self._effective_gemini_base_url(),
                api_key=self._gemini_api_key,
                model=self._gemini_model,
                disable_thinking=self._gemini_disable_thinking,
                parallel=self._gemini_parallel,
                coordinate_mode=self._vision_coordinate_mode,
            )

            # 共通 Gemini prompt を読み込んで適用
            prompts_dir = self._get_prompts_dir()

            # 旧 llm_system_prompt からの移行: ファイルが存在しない場合のみ
            old_system_prompt = self._settings.get_setting("llm_system_prompt", "")
            migrate_llm_system_prompt(prompts_dir, old_system_prompt)

            self._ensure_vision_common_prompt_file()

            # Apply debug_mode log level
            if self._settings.get_setting("debug_mode", False):
                logger.setLevel(logging.DEBUG)
                logger.debug("Debug logging enabled")

            logger.info(
                f"Initialized - Gemini: model={self._gemini_model}, "
                f"base_url={self._effective_gemini_base_url()}, "
                f"api_key_set={bool(self._gemini_api_key)}, "
                f"target_lang={self._target_language}"
            )

            # Start hidraw button monitor
            self._hidraw_monitor = HidrawButtonMonitor()
            if self._hidraw_monitor.start():
                logger.info("Hidraw button monitor started")
            else:
                logger.warning("Failed to start hidraw button monitor")

            # Start evdev monitor for external gamepads
            if EVDEV_AVAILABLE:
                self._evdev_monitor = EvdevGamepadMonitor()
                if self._evdev_monitor.start():
                    logger.info("Evdev gamepad monitor started")
                else:
                    logger.warning("Failed to start evdev gamepad monitor")
            else:
                logger.info("evdev not available, external gamepad support disabled")

            # Agent CLI 設定を読み込み、有効時のみソケットサーバーを起動
            self._agent_enabled = self._settings.get_setting("agent_enabled", False)
            if self._agent_enabled is None:
                self._agent_enabled = False
            if self._agent_enabled:
                self._notify_server = NotifySocketServer(self._on_cli_notification)
                self._notify_server.start()
            else:
                logger.info("Agent CLI is disabled")

        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            logger.error(traceback.format_exc())
        return

    async def _unload(self):
        logger.info("Unloading plugin")
        try:
            if self._evdev_monitor:
                self._evdev_monitor.stop()
                self._evdev_monitor = None

            if self._hidraw_monitor:
                self._hidraw_monitor.stop()
                self._hidraw_monitor = None

            if self._notify_server:
                self._notify_server.stop()
                self._notify_server = None

            std_out_file.close()
            std_err_file.close()
        except Exception as e:
            logger.error(f"Error during plugin unload: {e}")
            logger.error(traceback.format_exc())
        return
