#!/usr/bin/python3

import os
import shutil
import sys
import signal
import threading
import time
import traceback
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIRECTORY = PROJECT_ROOT / 'logs'
LOG_DIRECTORY.mkdir(exist_ok=True)

from kivy.config import Config as KivyConfig
KivyConfig.set('kivy', 'log_enable', '1')
KivyConfig.set('kivy', 'log_level', 'info')
KivyConfig.set('kivy', 'log_dir', str(LOG_DIRECTORY))
KivyConfig.set('kivy', 'log_name', 'photobooth_%y-%m-%d_%_.txt')
KivyConfig.set('kivy', 'exit_on_escape', '0')

# os.environ['KIVY_NO_CONSOLELOG'] = '1'
from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.logger import Logger
from kivy.uix.screenmanager import FadeTransition

APP_FONT = PROJECT_ROOT / 'assets' / 'fonts' / 'Montserrat-Regular.ttf'
LabelBase.register(
    name='Roboto',
    fn_regular=str(APP_FONT),
    fn_bold=str(APP_FONT),
    fn_italic=str(APP_FONT),
    fn_bolditalic=str(APP_FONT),
)

from libs.config import Config
from libs.device_utils import DeviceUtils, PrinterStatusError
from libs.file_utils import FileUtils
from libs.i18n import I18n
from libs.screens import ScreenMgr
from libs.ringled import RingLed
from libs.stats_store import StatsStore
from libs.template_collage import load_templates
from libs.usb_transfer import UsbTransfer
from libs.web_server import WebServer

RINGLED = None
APP_VERSION = '1.2'

def signal_handler(sig, frame):
    print("\nCtrl+C detected. Exiting gracefully...")
    if RINGLED:
        RINGLED.clear()
    sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)

class PhotoboothApp(App):
    def __init__(self, **kwargs):
        global RINGLED
        Logger.info('PhotoboothApp: __init__().')
        super(PhotoboothApp, self).__init__(**kwargs)

        # Load configuration
        config = Config()
        self.config = config
        self.FULLSCREEN = config.get_fullscreen()
        self.LANGUAGE = config.get_language()
        self.CAMERA = config.get_camera()
        self.SHARE = config.get_share()
        self.WEB_PORT = config.get_web_port()
        self.STARTSCREEN_BACKGROUND_IMAGE = config.get_startscreen_background_image()
        self.STARTSCREEN_TEXT_COLOR = config.get_startscreen_text_color()
        self.STARTSCREEN_SHOW_TITLE = config.get_startscreen_show_title()
        self.STARTSCREEN_SHOW_INSTRUCTIONS = config.get_startscreen_show_instructions()
        self.FILTERS = config.get_filters()
        self.PREVIEW_BLUR_REFRESH_FRAMES = config.get_preview_blur_refresh_frames()
        self.BLUR_CAMERA = config.get_blur_camera()
        self.BLUR_IMAGES = config.get_blur_images()
        self.BLUR_COLLAGE = config.get_blur_collage()
        self.COUNTDOWN = config.get_countdown()
        self.CAPTURE_TIMEOUT = config.get_capture_timeout()
        self.PROCESSING_TIMEOUT = config.get_processing_timeout()
        self.REVIEW_SLIDE_DURATION = config.get_review_slide_duration()
        self.REVIEW_CROSSFADE_DURATION = config.get_review_crossfade_duration()
        self.FEEDBACK_ENABLED = config.get_feedback_enabled()
        self.DCIM_DIRECTORY = config.get_dcim_directory()
        self.DISK_MIN_FREE_GB = config.get_disk_min_free_gb()
        self.DISK_MAX_USED_PERCENT = config.get_disk_max_used_percent()
        self.SAVE_TIMEOUT = config.get_save_timeout()
        self.PRINTER_WAIT_TIMEOUT = config.get_printer_wait_timeout()
        self.USB_EXPORT = config.get_usb_export_enabled()
        self.USB_MIN_FREE_GB = config.get_usb_min_free_gb()
        self.USB_COPY_TIMEOUT = config.get_usb_copy_timeout()
        self.PRINTER = config.get_printer()
        self.MAX_PRINTS = config.get_max_prints()
        self.CALIBRATION = config.get_calibration()
        self._dslr_liveview_params = config.get_dslr_liveview_params()
        self._dslr_capture_params = config.get_dslr_capture_params()
        self._log_retention_days = config.get_log_retention_days()
        self._log_max_files = config.get_log_max_files()
        self.i18n = I18n(self.LANGUAGE)
        self.APP_VERSION = APP_VERSION

        self._rotate_logs()
        
        # Initialize RingLed if enabled in config
        if config.get_ringled():
            RINGLED = RingLed(num_pixels=12)
            Logger.info('PhotoboothApp: RingLed enabled')
        else:
            Logger.info('PhotoboothApp: RingLed disabled')

        # Assign local variables
        self.sm = None
        self._requested_screen = None
        self._requested_kwargs = None
        self.pending_photo_tasks = []
        self._pending_photo_error = None
        self._pending_photo_started_at = None
        self._pending_photo_lock = threading.Lock()
        self.last_saved_session_directory = None
        self.processes = []
        self._process_lock = threading.Lock()
        self._process_state = {
            'kind': None,
            'token': 0,
            'error': None,
            'traceback': None,
            'started_at': None,
            'finished_at': None,
        }
        self._process_token = 0
        self._device_reconnect_lock = threading.Lock()
        self._device_reconnecting = False
        self._device_reconnect_last_attempt = 0
        self._print_state_uncertain = False
        self.usb_transfer = None
        self.ringled = RINGLED
        self.devices = DeviceUtils(
            printer_name=self.PRINTER,
            cv2_port=self.CAMERA,
            zoom=self.CALIBRATION,
            dslr_liveview_params=self._dslr_liveview_params,
            dslr_capture_params=self._dslr_capture_params,
        )
        
        # Load templates from JSON files
        self.print_formats = load_templates('templates')
        
        # Check if templates were loaded
        if len(self.print_formats) == 0:
            Logger.error('No templates found in templates/ directory!')
            raise Exception('No templates found. Please ensure template JSON files exist in the templates/ directory.')
        self._selected_format = self._load_last_template()

        # Create required directories
        self.tmp_directory = os.path.join(self.DCIM_DIRECTORY, 'tmp')
        self.save_directory = os.path.join(self.DCIM_DIRECTORY, 'save')
        self.gallery_directory = os.path.join(self.DCIM_DIRECTORY, 'gallery')
        self.gallery_strips_directory = os.path.join(self.gallery_directory, 'strips')
        self.gallery_photos_directory = os.path.join(self.gallery_directory, 'photos')
        self.gallery_small_strips_directory = os.path.join(self.gallery_directory, 'small', 'strips')
        if not os.path.exists(self.DCIM_DIRECTORY): os.makedirs(self.DCIM_DIRECTORY)
        if not os.path.exists(self.tmp_directory): os.makedirs(self.tmp_directory)
        if not os.path.exists(self.save_directory): os.makedirs(self.save_directory)
        if not os.path.exists(self.gallery_strips_directory): os.makedirs(self.gallery_strips_directory)
        if not os.path.exists(self.gallery_photos_directory): os.makedirs(self.gallery_photos_directory)
        if not os.path.exists(self.gallery_small_strips_directory): os.makedirs(self.gallery_small_strips_directory)
        self.migrate_legacy_gallery_thumbnails()
        self.last_saved_session_id = None
        self.last_saved_strip_path = None
        self.last_saved_photos = []
        self._save_last_template()
        self.stats_store = StatsStore(
            os.path.join(self.save_directory, '.stats.json'),
            max_prints=self.MAX_PRINTS,
        )

        # Start USB transfer
        if self.USB_EXPORT:
            self.usb_transfer = UsbTransfer(
                self, self.save_directory, min_free_gb=self.USB_MIN_FREE_GB,
                copy_timeout=self.USB_COPY_TIMEOUT,
            )
            self.usb_transfer.start()
        else:
            Logger.info('PhotoboothApp: USB export disabled')
        
        # The web server always runs for gallery/admin access; SHARE only controls UI buttons.
        abs_save_directory = os.path.abspath(self.save_directory)
        self.web_server = WebServer(
            abs_save_directory,
            host='0.0.0.0',
            port=self.WEB_PORT,
            admin_password=config.get_admin_password(),
            stats_store=self.stats_store,
            restart_callback=self.request_restart,
        )
        if self.web_server.start():
            Logger.info(
                'PhotoboothApp: Web server started at %s:%s (share_ui=%s)',
                abs_save_directory,
                self.WEB_PORT,
                self.SHARE,
            )
        else:
            Logger.error('PhotoboothApp: Web server failed to start; gallery and admin are unavailable')
            self._requested_screen = ScreenMgr.ERROR
            self._requested_kwargs = {
                'message': self.t('web.port_error', port=self.WEB_PORT),
                'show_continue': True,
                'show_restart': True,
            }

        self._log_disk_space('startup')
        if self.is_disk_space_critical():
            self._requested_screen = ScreenMgr.ERROR
            self._requested_kwargs = self._disk_maintenance_kwargs()
        self._log_runtime_snapshot('startup')

    def build(self):
        Logger.info('PhotoboothApp: build().')
        self.sm = ScreenMgr(self, transition=FadeTransition(duration=0.08))
        if self._requested_screen:
            self.sm.current = self._requested_screen
        self.sm.current_screen.on_entry()
        if self._requested_screen and self._requested_kwargs:
            self.sm.current_screen.on_entry(self._requested_kwargs)
        return self.sm

    def t(self, key, default=None, **kwargs):
        return self.i18n.t(key, default=default, **kwargs)

    def on_stop(self):
        self._log_runtime_snapshot('shutdown')
        if self.ringled:
            self.ringled.clear()
        if getattr(self, 'web_server', None):
            self.web_server.stop()
        if getattr(self, 'usb_transfer', None):
            self.usb_transfer.stop()
        if getattr(self, 'devices', None):
            self.devices.close()

    def request_restart(self):
        """Request a clean application restart from a background thread."""
        Logger.warning('PhotoboothApp: restart requested')
        self._log_runtime_snapshot('restart_requested')
        Clock.schedule_once(lambda dt: self.stop(), 0)

    def request_transition_to(self, new_state, **kwargs):
        """
        Request a screen transition from any thread.
        """
        Clock.schedule_once(lambda dt: self.transition_to(new_state, **kwargs), 0)

    def transition_to(self, new_state, **kwargs):
        self.sm.current_screen.on_exit()
        self.sm.current = new_state
        self.sm.current_screen.on_entry(kwargs)

    def enter_maintenance_mode(self, message, show_continue=False, show_restart=True):
        Logger.error('PhotoboothApp: entering maintenance mode message=%s', message)
        self.request_transition_to(
            ScreenMgr.ERROR,
            message=message,
            show_continue=show_continue,
            show_restart=show_restart,
        )

    def get_current_screen_name(self):
        if self.sm is None:
            return None
        return self.sm.current

    def is_usb_copy_allowed(self):
        current_screen = self.get_current_screen_name()
        if current_screen == ScreenMgr.START:
            return True
        if current_screen == ScreenMgr.COUNTDOWN:
            screen = self.sm.get_screen(ScreenMgr.COUNTDOWN)
            if getattr(screen, '_current_shot', 0) == 0 and not getattr(screen, '_timer_active', False):
                return True
        return False

    def get_shot(self, shot_idx):
        return os.path.join(self.tmp_directory, "capture-{}.jpg".format(shot_idx))

    def get_collage(self):
        return os.path.join(self.tmp_directory, 'collage.jpg')

    def get_saved_collage(self):
        if getattr(self, 'last_saved_strip_path', None) and os.path.exists(self.last_saved_strip_path):
            return self.last_saved_strip_path
        if not self.last_saved_session_directory:
            return None
        path = os.path.join(self.last_saved_session_directory, 'collage.jpg')
        return path if os.path.exists(path) else None

    @property
    def selected_format(self):
        return getattr(self, '_selected_format', 0)

    @selected_format.setter
    def selected_format(self, value):
        if isinstance(value, int) and hasattr(self, 'print_formats') and 0 <= value < len(self.print_formats):
            self._selected_format = value
            self._save_last_template()
        elif hasattr(self, 'print_formats') and len(self.print_formats) > 0:
            self._selected_format = 0

    def _get_last_template_path(self):
        return os.path.join(self.DCIM_DIRECTORY, '.last_template')

    def _load_last_template(self):
        try:
            path = self._get_last_template_path()
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    saved = f.read().strip()
                if saved:
                    # Match by template filename first (e.g. 'strip.json', 'Prueba_1.json')
                    for idx, fmt in enumerate(self.print_formats):
                        template_file = os.path.basename(getattr(fmt, '_template_path', ''))
                        if template_file and template_file == saved:
                            Logger.info(f'PhotoboothApp: restored last template by filename: {saved} (format index {idx})')
                            return idx
                    # Match by template name second
                    for idx, fmt in enumerate(self.print_formats):
                        template_name = getattr(fmt, '_name', '') or (fmt.get_name() if hasattr(fmt, 'get_name') else '')
                        if template_name and template_name == saved:
                            Logger.info(f'PhotoboothApp: restored last template by name: {saved} (format index {idx})')
                            return idx
                    # Match by integer index third
                    if saved.isdigit():
                        idx = int(saved)
                        if 0 <= idx < len(self.print_formats):
                            Logger.info(f'PhotoboothApp: restored last template by index: {idx}')
                            return idx
        except Exception as e:
            Logger.warning(f'PhotoboothApp: failed to load last template: {e}')
        return 0

    def _save_last_template(self):
        try:
            if not os.path.exists(self.DCIM_DIRECTORY):
                os.makedirs(self.DCIM_DIRECTORY)
            path = self._get_last_template_path()
            current_format = getattr(self, '_selected_format', 0)
            if hasattr(self, 'print_formats') and 0 <= current_format < len(self.print_formats):
                fmt = self.print_formats[current_format]
                template_file = os.path.basename(getattr(fmt, '_template_path', ''))
                to_save = template_file or str(current_format)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(to_save)
        except Exception as e:
            Logger.warning(f'PhotoboothApp: failed to save last template: {e}')

    def get_shots_to_take(self, format=None):
        if format is None:
            format = self.selected_format
        return self.print_formats[format].get_photos_required()

    def get_layout_previews(self, format=0):
        return [f.get_preview() for f in self.print_formats]

    def get_format_aspect_ratio(self, format_idx=None):
        """Get the aspect ratio (width/height) for the given format."""
        if format_idx is None:
            format_idx = self.selected_format
        return self.print_formats[format_idx].get_aspect_ratio()

    def _log_disk_space(self, context):
        try:
            usage = self.get_disk_usage()
            Logger.info(
                'PhotoboothApp: disk usage [%s] free=%.2fGB total=%.2fGB used=%.1f%% path=%s',
                context,
                usage['free_gb'],
                usage['total_gb'],
                usage['used_percent'],
                self.DCIM_DIRECTORY,
            )
        except Exception as exc:
            Logger.warning('PhotoboothApp: disk usage check failed [%s]: %s', context, exc)

    def _rotate_logs(self):
        try:
            now = time.time()
            max_age = self._log_retention_days * 86400
            log_files = [path for path in LOG_DIRECTORY.iterdir() if path.is_file()]

            removed = 0
            for path in log_files:
                try:
                    if now - path.stat().st_mtime > max_age:
                        path.unlink()
                        removed += 1
                except OSError as exc:
                    Logger.warning('PhotoboothApp: could not remove old log %s: %s', path, exc)

            remaining = sorted(
                [path for path in LOG_DIRECTORY.iterdir() if path.is_file()],
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for path in remaining[self._log_max_files:]:
                try:
                    path.unlink()
                    removed += 1
                except OSError as exc:
                    Logger.warning('PhotoboothApp: could not remove extra log %s: %s', path, exc)

            Logger.info('PhotoboothApp: log rotation removed_files=%s retention_days=%s max_files=%s', removed, self._log_retention_days, self._log_max_files)
        except Exception as exc:
            Logger.warning('PhotoboothApp: log rotation failed: %s', exc)

    def get_disk_usage(self):
        usage = shutil.disk_usage(self.DCIM_DIRECTORY)
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        used_percent = 0 if usage.total == 0 else ((usage.total - usage.free) / usage.total) * 100
        return {
            'free_gb': free_gb,
            'total_gb': total_gb,
            'used_percent': used_percent,
        }

    def is_disk_space_critical(self):
        try:
            usage = self.get_disk_usage()
        except Exception as exc:
            Logger.warning('PhotoboothApp: disk critical check failed: %s', exc)
            return False
        return usage['free_gb'] < self.DISK_MIN_FREE_GB or usage['used_percent'] >= self.DISK_MAX_USED_PERCENT

    def _disk_maintenance_kwargs(self):
        return {
            'message': self.t('storage.full'),
            'show_continue': False,
            'show_restart': True,
        }

    def ensure_disk_space_or_maintenance(self):
        if not self.is_disk_space_critical():
            return True
        self.enter_maintenance_mode(**self._disk_maintenance_kwargs())
        return False

    def _log_runtime_snapshot(self, context):
        Logger.info(
            'PhotoboothApp: runtime snapshot [%s] threads=%d current_screen=%s share=%s printer=%s',
            context,
            len(threading.enumerate()),
            self.get_current_screen_name(),
            self.SHARE,
            self.PRINTER,
        )

    def _start_background_process(self, kind, target, *args, **kwargs):
        with self._process_lock:
            self._process_token += 1
            process_token = self._process_token
            self._process_state = {
                'kind': kind,
                'token': process_token,
                'error': None,
                'traceback': None,
                'started_at': time.monotonic(),
                'finished_at': None,
            }

        Logger.info('PhotoboothApp: background %s started token=%s', kind, process_token)

        def run_target():
            error = None
            tb = None
            try:
                target(*args, **kwargs)
            except Exception as exc:
                error = str(exc) or exc.__class__.__name__
                tb = traceback.format_exc()
                Logger.error('PhotoboothApp: background %s failed: %s', kind, error)
                Logger.error(tb)
            finally:
                with self._process_lock:
                    if self._process_state.get('token') == process_token:
                        self._process_state['error'] = error
                        self._process_state['traceback'] = tb
                        self._process_state['finished_at'] = time.monotonic()

                duration = time.monotonic() - self._process_state['started_at'] if self._process_state.get('token') == process_token else None
                if error is None:
                    Logger.info('PhotoboothApp: background %s completed token=%s duration=%.2fs', kind, process_token, duration or 0)
                else:
                    Logger.error('PhotoboothApp: background %s finished with error token=%s duration=%.2fs', kind, process_token, duration or 0)
                self._log_runtime_snapshot(f'background_{kind}_done')

        process = threading.Thread(target=run_target, name=f'photobooth-{kind}-{process_token}', daemon=True)
        process.start()
        self.processes = [process]

    def _get_process_state(self):
        with self._process_lock:
            return dict(self._process_state)

    def has_process_failed(self, kind=None):
        state = self._get_process_state()
        if kind is not None and state.get('kind') != kind:
            return False
        return state.get('error') is not None

    def get_process_error(self, kind=None):
        state = self._get_process_state()
        if kind is not None and state.get('kind') != kind:
            return None
        return state.get('traceback') or state.get('error')

    def has_process_timed_out(self, kind, timeout_seconds):
        state = self._get_process_state()
        if state.get('kind') != kind:
            return False
        if state.get('finished_at') is not None:
            return False
        started_at = state.get('started_at')
        if started_at is None:
            return False
        return (time.monotonic() - started_at) >= timeout_seconds

    def abandon_background_processes(self, kind=None, reason='unknown'):
        with self._process_lock:
            if kind is not None and self._process_state.get('kind') != kind:
                return
            Logger.warning('PhotoboothApp: abandoning background process kind=%s reason=%s', self._process_state.get('kind'), reason)
            self._process_token += 1
            self._process_state['error'] = reason
            self._process_state['finished_at'] = time.monotonic()
        self.processes = []

    def trigger_shot(self, shot_idx, format_idx):
        Logger.info('PhotoboothApp: trigger_shot().')
        if not self.ensure_disk_space_or_maintenance():
            raise RuntimeError('Photo storage is almost full')
        aspect_ratio = self.get_format_aspect_ratio(format_idx)
        Logger.info('PhotoboothApp: shot request idx=%s format=%s aspect_ratio=%.4f', shot_idx, format_idx, aspect_ratio)
        self._log_disk_space('before_shot')
        flash_callback = self.ringled.flash if self.ringled else None
        self._start_background_process('shot', self.devices.capture, self.get_shot(shot_idx), aspect_ratio, flash_callback)

    def is_shot_completed(self, shot_idx):
        if any(process.is_alive() for process in self.processes): return False
        return True

    def trigger_collage(self, format=0):
        Logger.info('PhotoboothApp: trigger_collage().')
        if not self.ensure_disk_space_or_maintenance():
            raise RuntimeError('Photo storage is almost full')
        photos = []
        for i in range(0, self.get_shots_to_take(format)): photos.append(self.get_shot(i))
        Logger.info('PhotoboothApp: collage request format=%s photos=%s', format, len(photos))
        self._log_disk_space('before_collage')
        # Pass for_print=True to enable horizontal duplication for strip formats
        self._start_background_process(
            'collage',
            self.print_formats[format].assemble,
            output_path=self.get_collage(),
            image_paths=photos,
            for_print=True,
        )

    def is_collage_completed(self):
        if any(process.is_alive() for process in self.processes): return False
        return True

    def has_background_processes(self):
        return any(process.is_alive() for process in self.processes)

    def has_physical_flash(self):
        return self.devices.has_physical_flash()

    def has_printer(self):
        return self.devices.has_printer()

    def get_printer_status(self):
        return self.devices.get_printer_status()

    def can_start_print(self):
        if self._print_state_uncertain or not self.has_printer():
            return False
        return self.stats_store.can_print()

    def mark_print_state_uncertain(self):
        self._print_state_uncertain = True

    def get_print_limit_info(self):
        return self.stats_store.get_print_limit_info()

    def get_diagnostic_status(self):
        """Collect read-only health data without taking control of camera or printer."""
        devices = self.devices.get_diagnostic_status()
        usage = self.get_disk_usage()
        devices.update({
            'print_limit': self.get_print_limit_info(),
            'printer_config_name': self.PRINTER,
            'web_ok': self.web_server.is_running(),
            'web_port': self.WEB_PORT,
            'storage_ok': not self.is_disk_space_critical(),
            'storage': usage,
            'camera_reconnecting': self._device_reconnecting,
        })
        if not devices['camera_ok']:
            self.request_camera_reconnect()
        return devices

    def cancel_stale_print_jobs(self):
        count = self.devices.cancel_stale_print_jobs(strict=True)
        self._print_state_uncertain = False
        return count

    def request_camera_reconnect(self):
        """Retry camera discovery in the background without freezing the kiosk UI."""
        with self._device_reconnect_lock:
            now = time.monotonic()
            if self._device_reconnecting or now - self._device_reconnect_last_attempt < 5:
                return
            self._device_reconnecting = True
            self._device_reconnect_last_attempt = now

        def reconnect():
            replacement = None
            old_devices = self.devices
            try:
                # A disconnected gPhoto/Picamera handle must be released before rediscovery.
                old_devices.close()
                replacement = DeviceUtils(
                    printer_name=self.PRINTER,
                    cv2_port=self.config.get_camera(),
                    zoom=self.CALIBRATION,
                    dslr_liveview_params=self._dslr_liveview_params,
                    dslr_capture_params=self._dslr_capture_params,
                )
                self.devices = replacement
                Logger.info('PhotoboothApp: camera reconnected')
            except Exception as exc:
                Logger.warning('PhotoboothApp: camera reconnect failed: %s', exc)
                if replacement:
                    replacement.close()
            finally:
                with self._device_reconnect_lock:
                    self._device_reconnecting = False

        threading.Thread(target=reconnect, name='photobooth-camera-reconnect', daemon=True).start()

    def track_print_sent(self):
        self.stats_store.track_print()

    def track_feedback(self, positive):
        self.stats_store.track_feedback(positive)

    def trigger_print(self, copies, format=0):
        Logger.info('PhotoboothApp: trigger_print().')
        if not self.has_printer():
            raise PrinterStatusError(self.get_printer_status().get('reasons'))
        if not self.stats_store.can_print():
            raise RuntimeError('Print limit reached')
        options = self.print_formats[format].get_print_params()
        options['copies'] = str(copies)
        Logger.info('PhotoboothApp: print request format=%s copies=%s printer_available=%s', format, copies, self.has_printer())
        self._log_disk_space('before_print')
        
        # Use duplicated print output only for templates that generate one.
        print_collage = self.get_collage().replace('.jpg', '_print.jpg')
        if self.print_formats[format].uses_print_version() and os.path.exists(print_collage):
            Logger.info(f'PhotoboothApp: Using print version: {print_collage}')
            return self.devices.print(print_collage, options)

        collage = self.get_collage() if os.path.exists(self.get_collage()) else self.get_saved_collage()
        if collage is None:
            raise FileNotFoundError('No collage available to print')
        return self.devices.print(collage, options)

    def start_photo_task(self, target, *args):
        def run_target():
            try:
                target(*args)
            except Exception:
                with self._pending_photo_lock:
                    self._pending_photo_error = traceback.format_exc()
                Logger.error(self._pending_photo_error)

        task = threading.Thread(target=run_target, name='photobooth-photo-task', daemon=True)
        with self._pending_photo_lock:
            self._pending_photo_error = None
            self._pending_photo_started_at = time.monotonic()
            self.pending_photo_tasks = [task for task in self.pending_photo_tasks if task.is_alive()]
            self.pending_photo_tasks.append(task)
        task.start()

    def has_pending_photo_tasks(self):
        with self._pending_photo_lock:
            self.pending_photo_tasks = [task for task in self.pending_photo_tasks if task.is_alive()]
            if not self.pending_photo_tasks:
                self._pending_photo_started_at = None
            return bool(self.pending_photo_tasks)

    def has_pending_photo_tasks_timed_out(self, timeout_seconds=None):
        timeout = timeout_seconds or self.SAVE_TIMEOUT
        with self._pending_photo_lock:
            return bool(
                self._pending_photo_started_at is not None
                and any(task.is_alive() for task in self.pending_photo_tasks)
                and time.monotonic() - self._pending_photo_started_at >= timeout
            )

    def get_pending_photo_error(self):
        with self._pending_photo_lock:
            return self._pending_photo_error

    def clear_pending_photo_error(self):
        with self._pending_photo_lock:
            self._pending_photo_error = None

    def is_print_completed(self, print_task_id):
        try:
            status = self.devices.get_print_status(print_task_id)
            Logger.info('PhotoboothApp: print status task=%s status=%s', print_task_id, status)
            return status == 'sent'
        except Exception as exc:
            Logger.error('PhotoboothApp: print status check failed task=%s error=%s', print_task_id, exc)
            return False

    def reset_devices(self, reason='unknown'):
        Logger.warning('PhotoboothApp: resetting devices reason=%s', reason)
        try:
            if getattr(self, 'devices', None):
                self.devices.close()
        except Exception as exc:
            Logger.warning('PhotoboothApp: device close during reset failed: %s', exc)

        self.devices = DeviceUtils(
            printer_name=self.PRINTER,
            cv2_port=self.config.get_camera(),
            zoom=self.CALIBRATION,
            dslr_liveview_params=self._dslr_liveview_params,
            dslr_capture_params=self._dslr_capture_params,
        )
        self._log_runtime_snapshot('devices_reset')

    def recover_devices_and_return_home(self, reason='unknown'):
        def recover():
            try:
                self.abandon_background_processes(kind='shot', reason=reason)
                self.reset_devices(reason=reason)
                self.request_transition_to(ScreenMgr.START)
            except Exception as exc:
                Logger.error('PhotoboothApp: device recovery failed: %s', exc)
                Logger.error(traceback.format_exc())
                self.enter_maintenance_mode(
                    message=self.t('camera.recovery_failed'),
                )

        threading.Thread(target=recover, name='photobooth-device-recovery', daemon=True).start()

    def migrate_legacy_gallery_thumbnails(self):
        strips_dir = getattr(self, 'gallery_strips_directory', None)
        small_dir = getattr(self, 'gallery_small_strips_directory', None)
        if not strips_dir or not os.path.exists(strips_dir) or not small_dir:
            return
        os.makedirs(small_dir, exist_ok=True)
        try:
            for fname in os.listdir(strips_dir):
                if fname.lower().endswith('_small.jpg'):
                    legacy_path = os.path.join(strips_dir, fname)
                    new_path = os.path.join(small_dir, fname)
                    if not os.path.exists(new_path):
                        FileUtils.move_file(legacy_path, new_path)
                    else:
                        FileUtils.remove_file(legacy_path)
        except Exception as exc:
            Logger.warning('PhotoboothApp: migrate_legacy_gallery_thumbnails error: %s', exc)

    def generate_session_id(self, now=None):
        if now is None:
            now = datetime.now()
        base_id = now.strftime('%Y-%m-%d_%H-%M-%S') + f'_{now.microsecond // 1000:03d}'
        session_id = base_id
        counter = 1
        strips_dir = getattr(self, 'gallery_strips_directory', os.path.join(self.DCIM_DIRECTORY, 'gallery', 'strips'))
        while os.path.exists(os.path.join(strips_dir, f'{session_id}.jpg')):
            session_id = f'{base_id}_{counter:02d}'
            counter += 1
        return session_id

    def save_collage(self):
        Logger.info('PhotoboothApp: save_collage().')
        if not self.ensure_disk_space_or_maintenance():
            raise RuntimeError('Photo storage is almost full')

        all_files = os.listdir(self.tmp_directory) if os.path.exists(self.tmp_directory) else []
        if len(all_files) == 0:
            return None

        collage_src = self.get_collage()
        if not os.path.exists(collage_src):
            Logger.warning('PhotoboothApp: save_collage: collage.jpg not found in tmp')
            return None

        session_id = self.generate_session_id()

        # 1. Copy collage.jpg -> gallery/strips/{session_id}.jpg
        strip_dst = os.path.join(self.gallery_strips_directory, f'{session_id}.jpg')
        FileUtils.copy_file(collage_src, strip_dst)

        # 2. Copy collage_small.jpg -> gallery/small/strips/{session_id}_small.jpg
        collage_small_src = FileUtils.get_small_path(collage_src)
        strip_small_dst = os.path.join(self.gallery_small_strips_directory, f'{session_id}_small.jpg')
        if os.path.exists(collage_small_src):
            FileUtils.copy_file(collage_small_src, strip_small_dst)
        else:
            try:
                import cv2
                im = cv2.imread(collage_src)
                if im is not None:
                    h, w = im.shape[:2]
                    target_w = 400
                    target_h = max(1, int(h * (target_w / w)))
                    resized = cv2.resize(im, (target_w, target_h), interpolation=cv2.INTER_AREA)
                    FileUtils.write_image(strip_small_dst, resized)
            except Exception as exc:
                Logger.warning('PhotoboothApp: could not create small strip thumbnail: %s', exc)

        # 3. Copy valid capture-N.jpg -> gallery/photos/{session_id}_01.jpg, {session_id}_02.jpg, ...
        saved_photos = []
        i = 0
        while True:
            shot_file = self.get_shot(i)
            if not os.path.exists(shot_file):
                break
            photo_dst = os.path.join(self.gallery_photos_directory, f'{session_id}_{i+1:02d}.jpg')
            FileUtils.copy_file(shot_file, photo_dst)
            saved_photos.append(photo_dst)
            i += 1

        self.last_saved_session_id = session_id
        self.last_saved_strip_path = strip_dst
        self.last_saved_photos = saved_photos

        self._log_disk_space('after_save')
        self.stats_store.track_photo_taken(session_id=session_id)
        Logger.info('PhotoboothApp: session saved to gallery id=%s (strip=%s, photos=%d)',
                    session_id, strip_dst, len(saved_photos))
        return session_id

    def delete_last_saved_session(self):
        session_id = getattr(self, 'last_saved_session_id', None)
        if not session_id:
            destination = getattr(self, 'last_saved_session_directory', None)
            if destination and os.path.exists(destination):
                try:
                    shutil.rmtree(destination)
                    self.last_saved_session_directory = None
                    return True
                except Exception:
                    pass
            return False

        strip_path = os.path.join(self.gallery_strips_directory, f'{session_id}.jpg')
        strip_small = os.path.join(self.gallery_small_strips_directory, f'{session_id}_small.jpg')
        legacy_strip_small = os.path.join(self.gallery_strips_directory, f'{session_id}_small.jpg')
        FileUtils.remove_file(strip_path)
        FileUtils.remove_file(strip_small)
        FileUtils.remove_file(legacy_strip_small)
        for photo_path in getattr(self, 'last_saved_photos', []):
            FileUtils.remove_file(photo_path)

        if os.path.exists(self.gallery_photos_directory):
            for f in os.listdir(self.gallery_photos_directory):
                if f.startswith(f'{session_id}_'):
                    FileUtils.remove_file(os.path.join(self.gallery_photos_directory, f))

        self.last_saved_session_id = None
        self.last_saved_strip_path = None
        self.last_saved_photos = []
        Logger.info('PhotoboothApp: removed saved gallery session %s', session_id)
        return True

    def trigger_reprint(self, file_path, copies=1):
        Logger.info('PhotoboothApp: trigger_reprint file=%s copies=%s', file_path, copies)
        if not self.has_printer():
            raise PrinterStatusError(self.get_printer_status().get('reasons'))
        if not self.stats_store.can_print():
            raise RuntimeError('Print limit reached')
        if not os.path.exists(file_path):
            raise FileNotFoundError(f'File not found for reprint: {file_path}')

        options = {}
        if hasattr(self, 'print_formats') and len(self.print_formats) > 0:
            options = self.print_formats[0].get_print_params()
        options['copies'] = str(copies)
        self._log_disk_space('before_reprint')

        task_id = self.devices.print(file_path, options)
        if task_id:
            self.stats_store.track_photo_printed()
        return task_id

    def purge_tmp(self):
        # List existing files and delete (including _print versions)
        all_files = os.listdir(self.tmp_directory)
        if len(all_files) == 0: return
        removed_files = 0
        for f in all_files:
            src_path = os.path.join(self.tmp_directory, f)
            if os.path.isfile(src_path):
                try:
                    if FileUtils.remove_file(src_path):
                        removed_files += 1
                except Exception as exc:
                    Logger.warning('PhotoboothApp: failed to purge temp file %s: %s', src_path, exc)
        Logger.info('PhotoboothApp: purged tmp directory removed_files=%s', removed_files)

if __name__ == '__main__':
    PhotoboothApp().run()
