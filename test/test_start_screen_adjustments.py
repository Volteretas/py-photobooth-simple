import os
import unittest
from unittest.mock import MagicMock

import numpy as np
from kivy.core.window import Window
from libs.file_utils import FileUtils
from libs.screens import (
    StartScreen,
    BackgroundScreen,
    ICON_CANCEL,
    ICON_FULLSCREEN,
    ICON_WINDOWED,
    ICON_ADMIN,
    ICON_GALLERY,
    ICON_TEMPLATE,
    CANCEL_COLOR,
    HOME_COLOR,
)


class TestStartScreenAdjustments(unittest.TestCase):
    def setUp(self):
        self.mock_app = MagicMock()
        self.mock_app.STARTSCREEN_TEXT_COLOR = '#FFFFFF'
        self.mock_app.STARTSCREEN_BACKGROUND_IMAGE = 'assets/backgrounds/bg_start.jpeg'
        self.mock_app.STARTSCREEN_SHOW_TITLE = False
        self.mock_app.STARTSCREEN_SHOW_INSTRUCTIONS = True
        self.mock_app.APP_VERSION = '1.0'
        self.mock_app.t = lambda k, **kw: k
        self.mock_app.print_formats = [1, 2]
        self.mock_app.selected_format = 0

    def test_start_screen_button_order_fullscreen_admin_close(self):
        """Right cluster must strictly follow: Fullscreen -> Admin (Settings) -> Close."""
        screen = StartScreen(self.mock_app)

        for w, h in [(1920, 1080), (1280, 800), (1024, 768), (800, 600)]:
            screen.size = (w, h)
            screen.pos = (0, 0)
            screen.do_layout()
            screen._update_buttons_pos()

            # Right cluster check
            self.assertLess(
                screen.btn_fullscreen.x,
                screen.btn_admin.x,
                f"Fullscreen ({screen.btn_fullscreen.x}) must be to the left of Admin ({screen.btn_admin.x}) at {w}x{h}"
            )
            self.assertLess(
                screen.btn_admin.x,
                screen.btn_close.x,
                f"Admin ({screen.btn_admin.x}) must be to the left of Close ({screen.btn_close.x}) at {w}x{h}"
            )

            # Left cluster check
            self.assertLess(
                screen.btn_change_template.x,
                screen.btn_gallery.x,
                f"Template must be to the left of Gallery at {w}x{h}"
            )

    def test_start_screen_buttons_preserve_properties_and_actions(self):
        """Preserve styles, icons, sizes, colors and release callbacks."""
        screen = StartScreen(self.mock_app)

        # Fullscreen button
        self.assertIn(screen.btn_fullscreen.icon_widget.text, (ICON_FULLSCREEN, ICON_WINDOWED))
        self.assertEqual(screen.btn_fullscreen.icon_widget.background_color, list(HOME_COLOR))

        # Admin / Settings button
        self.assertEqual(screen.btn_admin.icon_widget.text, ICON_ADMIN)
        self.assertEqual(screen.btn_admin.icon_widget.background_color, list(HOME_COLOR))

        # Close button
        self.assertEqual(screen.btn_close.icon_widget.text, ICON_CANCEL)
        self.assertEqual(screen.btn_close.icon_widget.background_color, list(CANCEL_COLOR))

    def test_background_screen_cover_mode_aspect_ratio_and_coverage(self):
        """Background must cover the screen completely in cover mode preserving aspect ratio."""
        bg_screen = BackgroundScreen(bg='assets/backgrounds/bg_start.jpeg')
        tex = bg_screen.background_image.texture
        self.assertIsNotNone(tex, "Background image texture must exist")
        tw, th = tex.size
        expected_ratio = tw / th

        test_resolutions = [
            (1920, 1080),  # 16:9
            (1280, 800),   # 16:10
            (1024, 768),   # 4:3
            (1000, 1000),  # 1:1
            (720, 1280),   # 9:16 portrait
        ]

        for w, h in test_resolutions:
            bg_screen.size = (w, h)
            bg_screen.pos = (0, 0)
            bg_screen.on_size()

            bg_w, bg_h = bg_screen.background_image.size
            bg_x, bg_y = bg_screen.background_image.pos

            # 1. Aspect ratio preserved
            actual_ratio = bg_w / bg_h
            self.assertAlmostEqual(
                actual_ratio,
                expected_ratio,
                places=3,
                msg=f"Ratio at {w}x{h} should be {expected_ratio:.4f}, got {actual_ratio:.4f}"
            )

            # 2. Complete coverage: width and height must be >= screen dimensions
            self.assertGreaterEqual(bg_w, w - 1e-3, f"Width should cover screen at {w}x{h}")
            self.assertGreaterEqual(bg_h, h - 1e-3, f"Height should cover screen at {w}x{h}")

            # 3. Centering
            expected_x = (w - bg_w) / 2.0
            expected_y = (h - bg_h) / 2.0
            self.assertAlmostEqual(bg_x, expected_x, places=2, msg=f"X centering failed at {w}x{h}")
            self.assertAlmostEqual(bg_y, expected_y, places=2, msg=f"Y centering failed at {w}x{h}")

    def test_file_utils_extract_blurred_region_cover_mode(self):
        """extract_blurred_region scales source image in cover mode maintaining aspect ratio."""
        dummy_img = np.zeros((2400, 3600, 3), dtype=np.uint8)
        region = FileUtils.extract_blurred_region(
            dummy_img,
            screen_size=(1920, 1080),
            region=(100, 100, 300, 150),
        )
        self.assertIsNotNone(region)
        self.assertEqual(region.shape, (150, 300, 3))

    def test_start_screen_template_button_visible_with_single_or_multiple_formats(self):
        """Template button must remain visible when 1 or more formats are available."""
        # Single format
        self.mock_app.print_formats = [MagicMock()]
        screen = StartScreen(self.mock_app)
        screen.on_entry()
        self.assertEqual(screen.btn_change_template.opacity, 1)
        self.assertFalse(screen.btn_change_template.disabled)

        self.mock_app.print_formats = [MagicMock(), MagicMock()]
        screen.on_entry()
        self.assertEqual(screen.btn_change_template.opacity, 1)
        self.assertFalse(screen.btn_change_template.disabled)

    def test_start_screen_custom_title_and_instructions_display(self):

        """StartScreen uses custom title and instructions when configured."""
        self.mock_app.STARTSCREEN_TITLE = 'Boda de Ana y Juan'
        self.mock_app.STARTSCREEN_INSTRUCTIONS = 'Toque la pantalla\nSonría'
        self.mock_app.STARTSCREEN_SHOW_TITLE = True
        self.mock_app.STARTSCREEN_SHOW_INSTRUCTIONS = True

        screen = StartScreen(self.mock_app)
        self.assertEqual(screen.start_label.text, 'Boda de Ana y Juan')
        self.assertEqual(screen.instructions_label.text, 'Toque la pantalla\nSonría')
        self.assertEqual(screen.start_label.opacity, 1)
        self.assertEqual(screen.instructions_label.opacity, 1)

    def test_start_screen_fallback_when_title_and_instructions_empty(self):
        """StartScreen falls back to default i18n keys when custom options are empty."""
        self.mock_app.STARTSCREEN_TITLE = ''
        self.mock_app.STARTSCREEN_INSTRUCTIONS = ''
        self.mock_app.STARTSCREEN_SHOW_TITLE = True
        self.mock_app.STARTSCREEN_SHOW_INSTRUCTIONS = True

        screen = StartScreen(self.mock_app)
        self.assertEqual(screen.start_label.text, 'start.title')
        self.assertEqual(screen.instructions_label.text, 'start.tap_to_start')

    def test_start_screen_show_title_and_show_instructions_toggles(self):
        """Disabling SHOW_TITLE or SHOW_INSTRUCTIONS hides labels without clearing their text."""
        self.mock_app.STARTSCREEN_TITLE = 'Mi Título'
        self.mock_app.STARTSCREEN_INSTRUCTIONS = 'Mis Instrucciones'
        self.mock_app.STARTSCREEN_SHOW_TITLE = False
        self.mock_app.STARTSCREEN_SHOW_INSTRUCTIONS = False

        screen = StartScreen(self.mock_app)
        self.assertEqual(screen.start_label.text, 'Mi Título')
        self.assertEqual(screen.instructions_label.text, 'Mis Instrucciones')
        self.assertEqual(screen.start_label.opacity, 0)
        self.assertEqual(screen.instructions_label.opacity, 0)

    def test_start_screen_multiline_instructions_height_adaptation(self):
        """Multiline instructions adapt height hint to accommodate multiple lines."""
        self.mock_app.STARTSCREEN_INSTRUCTIONS = 'Línea 1\nLínea 2\nLínea 3'
        screen = StartScreen(self.mock_app)
        self.assertGreater(screen.instructions_label.size_hint_y, 0.1)
        self.assertIn('\n', screen.instructions_label.text)

    def test_config_title_and_instructions_methods(self):
        """Config class reads TITLE and unescapes INSTRUCTIONS."""
        import configparser
        from libs.config import Config

        cfg = Config.__new__(Config)
        cfg.config = configparser.ConfigParser()
        cfg.config.read_string('''
[StartScreen]
TITLE = Gran Fiesta
INSTRUCTIONS = Pulsa para empezar\\n¡No te muevas!
''')
        self.assertEqual(cfg.get_startscreen_title(), 'Gran Fiesta')
        self.assertEqual(cfg.get_startscreen_instructions(), 'Pulsa para empezar\n¡No te muevas!')

    def test_web_server_start_screen_config_coercion_and_preview(self):
        """WebServer coerces multiline instructions to escaped format and preview uses fallbacks."""
        from libs.web_server import WebServer

        server = WebServer.__new__(WebServer)
        server.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        server.config_file = os.path.join(server.project_root, 'config.ini')

        field_title = server._get_config_field_spec('StartScreen', 'TITLE')
        field_instructions = server._get_config_field_spec('StartScreen', 'INSTRUCTIONS')

        self.assertIsNotNone(field_title)
        self.assertIsNotNone(field_instructions)
        self.assertEqual(field_title['label'], 'Home Screen Title')
        self.assertEqual(field_instructions['label'], 'Home Screen Instructions')
        self.assertEqual(field_instructions['control'], 'textarea')

        # Coercion
        coerced_title = server._coerce_form_field_value(field_title, '  Mi Fiesta  \n ', '')
        self.assertEqual(coerced_title, 'Mi Fiesta')

        coerced_inst = server._coerce_form_field_value(field_instructions, "Línea 1\r\nLínea 2", '')
        self.assertEqual(coerced_inst, "Línea 1\\nLínea 2")

        # Normalization for form textarea
        normalized_inst = server._normalize_form_value(field_instructions, "Línea 1\\nLínea 2")
        self.assertEqual(normalized_inst, "Línea 1\nLínea 2")

        # Preview with custom values
        preview = server._get_start_screen_preview(form_values={
            'StartScreen__TITLE': 'Evento Especial',
            'StartScreen__INSTRUCTIONS': 'Sonríe\\nahora',
            'StartScreen__SHOW_TITLE': True,
            'StartScreen__SHOW_INSTRUCTIONS': True,
        })
        self.assertEqual(preview['text'], 'Evento Especial')
        self.assertEqual(preview['instructions_text'], 'Sonríe\nahora')

        # Preview fallback when empty
        preview_fallback = server._get_start_screen_preview(form_values={
            'StartScreen__TITLE': '',
            'StartScreen__INSTRUCTIONS': '',
        })
        self.assertEqual(preview_fallback['text'], 'PHOTO BOOTH')
        self.assertEqual(preview_fallback['instructions_text'], 'TAP TO START')

    def test_web_server_html_rendering_and_xss_protection(self):
        """Web template renders title and instructions controls, and auto-escapes HTML tags."""
        from libs.web_server import WebServer

        server = WebServer(
            save_directory='/tmp/save_test',
            port=5000,
            admin_password=None,
        )


        with server.app.test_client() as client:
            # Inject malicious text in preview values
            with client.session_transaction() as sess:
                sess['admin_authenticated'] = True

            with server.app.test_request_context('/admin'):
                html = server._render_admin_page(form_values={
                    'StartScreen__TITLE': '<script>alert("xss-title")</script>',
                    'StartScreen__INSTRUCTIONS': '<b>Line 1</b>\n<img src=x onerror=alert(1)>',
                })


                # Ensure textarea for instructions exists
                self.assertIn('<textarea', html)
                self.assertIn('name="StartScreen__INSTRUCTIONS"', html)
                self.assertIn('name="StartScreen__TITLE"', html)

                # Ensure XSS payloads are properly escaped and never unescaped in HTML
                self.assertNotIn('<script>alert("xss-title")</script>', html)
                self.assertNotIn('<img src=x onerror=alert(1)>', html)
                self.assertIn('&lt;script&gt;alert(&#34;xss-title&#34;)&lt;/script&gt;', html)



if __name__ == '__main__':
    unittest.main()

