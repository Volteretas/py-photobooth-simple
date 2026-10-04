import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["KIVY_NO_ARGS"] = "1"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from kivy.core.window import Window
from libs.config import Config
from libs.screens import ScreenMgr, StartScreen, ReviewScreen, SelectFormatScreen
from libs.web_server import WebServer
from photoboothapp import PhotoboothApp


def get_mock_config(temp_dcim):
    """Create a mock Config instance backed by a temporary directory."""
    cfg = MagicMock(spec=Config)
    cfg.get_dcim_directory.return_value = temp_dcim
    cfg.get_fullscreen.return_value = False
    cfg.get_language.return_value = 'en'
    cfg.get_camera.return_value = 'auto'
    cfg.get_share.return_value = False
    cfg.get_web_port.return_value = 5000
    cfg.get_startscreen_background_image.return_value = ''
    cfg.get_startscreen_text_color.return_value = '#FFFFFF'
    cfg.get_startscreen_show_title.return_value = True
    cfg.get_startscreen_show_instructions.return_value = True
    cfg.get_filters.return_value = False
    cfg.get_preview_blur_refresh_frames.return_value = 3
    cfg.get_blur_camera.return_value = False
    cfg.get_blur_images.return_value = False
    cfg.get_blur_collage.return_value = False
    cfg.get_countdown.return_value = 3
    cfg.get_capture_timeout.return_value = 10
    cfg.get_processing_timeout.return_value = 10
    cfg.get_review_slide_duration.return_value = 2.0
    cfg.get_review_crossfade_duration.return_value = 0.45
    cfg.get_feedback_enabled.return_value = False
    cfg.get_disk_min_free_gb.return_value = 1.0
    cfg.get_disk_max_used_percent.return_value = 95
    cfg.get_save_timeout.return_value = 10
    cfg.get_printer_wait_timeout.return_value = 45
    cfg.get_usb_export_enabled.return_value = False
    cfg.get_usb_min_free_gb.return_value = 1.0
    cfg.get_usb_copy_timeout.return_value = 10
    cfg.get_printer.return_value = None
    cfg.get_max_prints.return_value = None
    cfg.get_calibration.return_value = 1.0
    cfg.get_dslr_liveview_params.return_value = {}
    cfg.get_dslr_capture_params.return_value = {}
    cfg.get_log_retention_days.return_value = 7
    cfg.get_log_max_files.return_value = 10
    cfg.get_ringled.return_value = False
    cfg.get_admin_password.return_value = 'test'
    return cfg


class TestBugFixes(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dcim_dir = os.path.join(self.temp_dir.name, 'dcim')
        os.makedirs(self.dcim_dir, exist_ok=True)
        self.mock_config = get_mock_config(self.dcim_dir)

        self.patchers = [
            patch('photoboothapp.Config', return_value=self.mock_config),
            patch('photoboothapp.DeviceUtils'),
            patch('photoboothapp.RingLed'),
            patch('photoboothapp.UsbTransfer'),
            patch('photoboothapp.WebServer'),
        ]
        for p in self.patchers:
            p.start()

        self.app = PhotoboothApp()
        self.app.sm = MagicMock(spec=ScreenMgr)
        self.app.transition_to = MagicMock()
        self.app.request_transition_to = MagicMock()

    def tearDown(self):
        try:
            self.app.on_stop()
        except Exception:
            pass
        for p in self.patchers:
            p.stop()
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # BUG 1 — ReviewScreen Print button bounds
    # -------------------------------------------------------------------------
    def test_bug1_review_screen_controls_within_window_bounds(self):
        """ReviewScreen action buttons must strictly stay within window bounds across resolutions."""
        review_screen = ReviewScreen(self.app)

        test_resolutions = [
            (800, 600),
            (1024, 768),
            (1280, 720),
            (1920, 1080),
            (600, 1024),  # portrait
        ]

        for width, height in test_resolutions:
            Window.size = (width, height)
            review_screen.size = (width, height)
            review_screen.overlay_layout.size = (width, height)
            review_screen._layout_action_buttons()

            btn = review_screen.btn_print
            # Button must be fully inside the visible screen / overlay area
            self.assertGreaterEqual(btn.x, 0, f"Button x < 0 at resolution {width}x{height}")
            self.assertLessEqual(btn.right, width, f"Button right > width at resolution {width}x{height}")
            self.assertGreaterEqual(btn.y, 0, f"Button y < 0 at resolution {width}x{height}")
            self.assertLessEqual(btn.top, height, f"Button top > height at resolution {width}x{height}")

            # Also check retake button when enabled
            if hasattr(review_screen, 'btn_retake') and review_screen.btn_retake.parent:
                btn_ret = review_screen.btn_retake
                self.assertGreaterEqual(btn_ret.x, 0)
                self.assertLessEqual(btn_ret.right, width)
                self.assertGreaterEqual(btn_ret.y, 0)
                self.assertLessEqual(btn_ret.top, height)

    def test_bug1_image_aspect_does_not_affect_controls(self):
        """Image dimensions / aspect ratio must not push buttons out of bounds."""
        review_screen = ReviewScreen(self.app)
        Window.size = (1920, 1080)
        review_screen.size = (1920, 1080)
        review_screen.overlay_layout.size = (1920, 1080)
        review_screen._layout_action_buttons()

        pos_before = (review_screen.btn_print.x, review_screen.btn_print.y)

        # Simulate large image container with different sizes
        review_screen.image_container.size = (600, 1800)  # vertical strip
        review_screen._layout_action_buttons()
        self.assertEqual((review_screen.btn_print.x, review_screen.btn_print.y), pos_before)

        review_screen.image_container.size = (1800, 600)  # horizontal strip
        review_screen._layout_action_buttons()
        self.assertEqual((review_screen.btn_print.x, review_screen.btn_print.y), pos_before)

    # -------------------------------------------------------------------------
    # BUG 2 — PageSize when creating templates from Web Admin
    # -------------------------------------------------------------------------
    def test_bug2_web_admin_template_creation_sets_pagesize_4x6in(self):
        """Templates created via Web Admin must save PageSize as '4x6in'."""
        with tempfile.TemporaryDirectory() as web_tmp:
            save_dir = os.path.join(web_tmp, 'save')
            os.makedirs(save_dir, exist_ok=True)
            server = WebServer(save_directory=save_dir)
            server.templates_directory = os.path.join(web_tmp, 'templates')
            os.makedirs(server.templates_directory, exist_ok=True)

            client = server.app.test_client()

            # Case A: Template with original PageSize from base template (e.g. w288h432)
            payload_a = {
                'filename': 'new_template_a.json',
                'template': {
                    'name': 'Test Template A',
                    'description': 'Created from strip base',
                    'page': {'width': 600, 'height': 1800},
                    'photos': [{'x': 30, 'y': 30, 'width': 540, 'height': 540}],
                    'print_params': {
                        'PageSize': 'w288h432-div2',
                        'print-scaling': 'fit'
                    }
                }
            }
            res_a = client.post('/api/templates', json=payload_a)
            self.assertEqual(res_a.status_code, 200)

            saved_path_a = os.path.join(server.templates_directory, 'new_template_a.json')
            self.assertTrue(os.path.exists(saved_path_a))
            with open(saved_path_a, 'r', encoding='utf-8') as f:
                data_a = json.load(f)

            self.assertIn('print_params', data_a)
            self.assertEqual(data_a['print_params']['PageSize'], '4x6in')

            # Case B: Template without print_params at all
            payload_b = {
                'filename': 'new_template_b.json',
                'template': {
                    'name': 'Test Template B',
                    'page': {'width': 1800, 'height': 1200},
                    'photos': []
                }
            }
            res_b = client.post('/api/templates', json=payload_b)
            self.assertEqual(res_b.status_code, 200)

            saved_path_b = os.path.join(server.templates_directory, 'new_template_b.json')
            self.assertTrue(os.path.exists(saved_path_b))
            with open(saved_path_b, 'r', encoding='utf-8') as f:
                data_b = json.load(f)

            self.assertIn('print_params', data_b)
            self.assertEqual(data_b['print_params']['PageSize'], '4x6in')

    # -------------------------------------------------------------------------
    # BUG 3 — Fullscreen mode and buttons
    # -------------------------------------------------------------------------
    def test_bug3_fullscreen_uses_auto_mode(self):
        """Fullscreen init should request 'auto' to use real desktop resolution."""
        orig_fullscreen = Window.fullscreen
        try:
            self.app.FULLSCREEN = True
            Window.fullscreen = False
            mgr = ScreenMgr(self.app)
            self.assertEqual(Window.fullscreen, 'auto')
        finally:
            Window.fullscreen = orig_fullscreen

    def test_bug3_start_screen_buttons_exist_and_functional(self):
        """StartScreen must provide fullscreen toggle and close buttons without interfering with other buttons."""
        start_screen = StartScreen(self.app)

        # Check buttons exist
        self.assertTrue(hasattr(start_screen, 'btn_fullscreen'))
        self.assertTrue(hasattr(start_screen, 'btn_close'))
        self.assertIsNotNone(start_screen.btn_fullscreen)
        self.assertIsNotNone(start_screen.btn_close)

        # Fullscreen toggle callback
        orig_fullscreen = Window.fullscreen
        try:
            Window.fullscreen = 'auto'
            start_screen.on_toggle_fullscreen(None)
            self.assertFalse(Window.fullscreen)

            start_screen.on_toggle_fullscreen(None)
            self.assertEqual(Window.fullscreen, 'auto')
        finally:
            Window.fullscreen = orig_fullscreen

        # Close button calls app.stop()
        with patch.object(self.app, 'stop') as mock_stop:
            start_screen.on_close_app(None)
            mock_stop.assert_called_once()

    def test_bug3_esc_exits_fullscreen_on_startscreen(self):
        """Pressing Esc on StartScreen exits fullscreen."""
        orig_fullscreen = Window.fullscreen
        try:
            self.app.FULLSCREEN = False
            sm = ScreenMgr(self.app)
            sm.current = sm.START
            Window.fullscreen = 'auto'

            # Keycode 27 is Escape in Kivy
            sm._on_key_down(Window, 27, None, None, None)
            self.assertFalse(Window.fullscreen)
        finally:
            Window.fullscreen = orig_fullscreen

    # -------------------------------------------------------------------------
    # SelectFormatScreen - Show all templates & vertical scroll
    # -------------------------------------------------------------------------
    def _create_mock_template(self, name, photos=3):
        mock_t = MagicMock()
        mock_t.get_name.return_value = name
        mock_t.get_photos_required.return_value = photos
        mock_t.get_preview.return_value = ''
        mock_t.get_aspect_ratio.return_value = 1.5
        return mock_t

    def test_select_format_screen_shows_all_templates_without_limit_of_3(self):
        """SelectFormatScreen must build and display cards for all templates without a hardcoded limit of 3."""
        templates = [
            self._create_mock_template("Template 1"),
            self._create_mock_template("Template 2"),
            self._create_mock_template("Template 3"),
            self._create_mock_template("Template 4"),
        ]
        self.app.print_formats = templates
        select_screen = SelectFormatScreen(self.app)

        self.assertEqual(len(select_screen.format_cards), 4)
        self.assertEqual(len(select_screen.cards_grid.children), 4)

    def test_select_format_screen_scrolls_vertically_when_templates_exceed_screen(self):
        """When templates exceed vertical space, ScrollView must enable vertical scrolling and keep both first and last card accessible."""
        templates = [
            self._create_mock_template(f"Template {i}") for i in range(6)
        ]
        self.app.print_formats = templates
        select_screen = SelectFormatScreen(self.app)

        # Force layout update
        Window.size = (1920, 1080)
        select_screen.size = (1920, 1080)
        select_screen.scroll_view.size = (1920, 1080)
        select_screen._update_card_sizes()
        select_screen.cards_grid.do_layout()
        select_screen._update_container_height()
        select_screen.grid_container.do_layout()
        select_screen.scroll_view.update_from_scroll()

        # Grid and container must allow scrolling
        self.assertGreater(select_screen.cards_grid.height, select_screen.scroll_view.height)
        self.assertEqual(select_screen.grid_container.height, select_screen.cards_grid.height)
        self.assertEqual(select_screen.grid_container.anchor_y, 'top')
        self.assertGreater(select_screen.scroll_view.viewport_size[1], select_screen.scroll_view.height)

        # Test scroll to top (scroll_y = 1.0)
        select_screen.scroll_view.scroll_y = 1.0
        select_screen.scroll_view.update_from_scroll()
        first_card = select_screen.format_cards[0]
        self.assertGreaterEqual(first_card.to_window(first_card.x, first_card.y)[1], 0)

        # Test scroll to bottom (scroll_y = 0.0)
        select_screen.scroll_view.scroll_y = 0.0
        select_screen.scroll_view.update_from_scroll()
        last_card = select_screen.format_cards[-1]
        self.assertGreaterEqual(last_card.to_window(last_card.x, last_card.y)[1], 0)

    def test_select_format_screen_selection_and_lifecycle(self):
        """Selecting any template card transitions to COUNTDOWN with the selected format index."""
        from kivy.input.motionevent import MotionEvent
        from kivy.input.providers.mouse import MouseMotionEvent

        templates = [
            self._create_mock_template("Template 1"),
            self._create_mock_template("Template 2"),
            self._create_mock_template("Template 3"),
            self._create_mock_template("Template 4"),
        ]
        self.app.print_formats = templates
        select_screen = SelectFormatScreen(self.app)

        # Select fourth card (index 3)
        fourth_card = select_screen.format_cards[3]
        mock_touch = MagicMock(spec=MouseMotionEvent)
        fourth_card.last_touch = mock_touch
        select_screen.on_format_selected(fourth_card)

        self.assertEqual(self.app.selected_format, 3)
        self.app.transition_to.assert_called_with(ScreenMgr.COUNTDOWN, shot=0, format=3)

        # on_entry resets scroll position to 1.0
        select_screen.scroll_view.scroll_y = 0.2
        select_screen.on_entry({'source_screen': ScreenMgr.START})
        self.assertEqual(select_screen.scroll_view.scroll_y, 1.0)

        # on_back returns to START
        select_screen.on_back(None)
        self.app.transition_to.assert_called_with(ScreenMgr.START)


if __name__ == '__main__':
    unittest.main()

