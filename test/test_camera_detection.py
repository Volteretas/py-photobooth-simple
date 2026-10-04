import os
import sys
os.environ["KIVY_NO_ARGS"] = "1"
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
from libs.web_server import WebServer
from libs.device_utils import (
    DeviceUtils,
    CaptureDevice,
    Cv2Camera,
    DummyCamera,
    detect_cameras
)


class TestCameraDetection(unittest.TestCase):
    def test_1_detect_connected_cameras(self):
        """1. Detects connected Linux cameras and retrieves device path and real name."""
        cameras = detect_cameras()
        self.assertIsInstance(cameras, list)
        for cam in cameras:
            self.assertIn('id', cam)
            self.assertIn('device', cam)
            self.assertIn('name', cam)
            self.assertIn('type', cam)
            self.assertTrue(len(cam['name']) > 0)
            self.assertTrue(cam['device'].startswith('/dev/video') or cam['type'] == 'gphoto2')

    def test_2_empty_list_when_no_cameras(self):
        """2. Returns an empty list when no cameras are present."""
        with patch('glob.glob', return_value=[]), patch('libs.device_utils.gp', None):
            cameras = detect_cameras()
            self.assertEqual(cameras, [])

    def test_2_empty_list_when_devices_are_not_capture(self):
        """2b. Returns an empty list when devices exist but none are capture devices."""
        with patch('glob.glob', return_value=['/dev/video99']), \
             patch('os.open', side_effect=OSError('Mock: Not accessible')), \
             patch('os.path.exists', return_value=False), \
             patch('libs.device_utils.gp', None):
            cameras = detect_cameras()
            self.assertEqual(cameras, [])

    def test_selection_1_c922_available_uses_c922(self):
        """Target 1: When C922 is available and preferred, C922 is selected and used."""
        detected = [
            {'id': 0, 'device': '/dev/video0', 'name': 'HP Wide Vision HD Camera: HP Wi', 'type': 'v4l2'},
            {'id': 2, 'device': '/dev/video2', 'name': 'C922 Pro Stream Webcam', 'type': 'v4l2'}
        ]
        def mock_cap(target):
            cap = MagicMock()
            cap.isOpened.return_value = True
            cap.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))
            return cap

        with patch('libs.device_utils.detect_cameras', return_value=detected), \
             patch('libs.device_utils.cv2.VideoCapture', side_effect=mock_cap):
            devices = DeviceUtils(printer_name=None, cv2_port=2)
            try:
                self.assertIsNotNone(devices._preview)
                self.assertNotIsInstance(devices._preview, DummyCamera)
                self.assertEqual(devices._preview.port, 2)
                self.assertIn('C922', devices._preview.device_name)
                self.assertTrue(devices.get_diagnostic_status()['camera_ok'])
            finally:
                devices.close()

    def test_selection_2_c922_disconnected_hp_available_uses_hp(self):
        """Target 2: When C922 is disconnected (port 2 fails) but HP is available, fallback selects HP."""
        hp_only = [
            {'id': 0, 'device': '/dev/video0', 'name': 'HP Wide Vision HD Camera: HP Wi', 'type': 'v4l2'}
        ]
        real_videocapture = cv2.VideoCapture

        def mock_videocapture(target):
            # Port 2 / /dev/video2 cannot be opened (simulating disconnected C922)
            if target == 2 or target == '/dev/video2':
                mock = MagicMock()
                mock.isOpened.return_value = False
                return mock
            # Port 0 (HP) can be opened
            return real_videocapture(target)

        with patch('libs.device_utils.detect_cameras', return_value=hp_only), \
             patch('libs.device_utils.cv2.VideoCapture', side_effect=mock_videocapture):
            devices = DeviceUtils(printer_name=None, cv2_port=2)
            try:
                self.assertIsNotNone(devices._preview)
                self.assertNotIsInstance(devices._preview, DummyCamera)
                self.assertEqual(devices._preview.port, 0)
                self.assertIn('HP', devices._preview.device_name)
                self.assertTrue(devices.get_diagnostic_status()['camera_ok'])
            finally:
                devices.close()

    def test_selection_3_no_cameras_uses_dummy_camera(self):
        """Target 3: When no camera is available, DummyCamera is used without crashing."""
        with patch('libs.device_utils.detect_cameras', return_value=[]), \
             patch('libs.device_utils.Picamera2Camera', side_effect=Exception('No PiCam')), \
             patch('libs.device_utils.Gphoto2Camera', side_effect=Exception('No DSLR')), \
             patch('libs.device_utils.cv2.VideoCapture') as mock_cv:
            mock_cv.return_value.isOpened.return_value = False
            devices = DeviceUtils(printer_name=None, cv2_port=2)
            try:
                self.assertIsInstance(devices._preview, DummyCamera)
                self.assertIsInstance(devices._capture, DummyCamera)
                status = devices.get_diagnostic_status()
                self.assertFalse(status['camera_ok'])
                self.assertEqual(status['camera_name'], 'None')
                self.assertIsNone(devices.get_preview())
                self.assertEqual(devices.get_preview_frame_id(), 0)
                self.assertEqual(devices.get_preview_fps(), 30)
                self.assertFalse(devices.has_physical_flash())
                with self.assertRaises(IOError):
                    devices.capture('dummy.jpg')
            finally:
                devices.close()

    def test_camera_auto_selection(self):
        """1. CAMERA = auto: automatically selects an available camera."""
        detected = [
            {'id': 0, 'device': '/dev/video0', 'name': 'HP Wide Vision HD Camera: HP Wi', 'type': 'v4l2'},
            {'id': 2, 'device': '/dev/video2', 'name': 'C922 Pro Stream Webcam', 'type': 'v4l2'}
        ]
        with patch('libs.device_utils.detect_cameras', return_value=detected):
            devices = DeviceUtils(printer_name=None, cv2_port='auto')
            try:
                self.assertIsNotNone(devices._preview)
                self.assertNotIsInstance(devices._preview, DummyCamera)
                self.assertIn(devices._preview.port, (0, 2))
                self.assertTrue(devices.get_diagnostic_status()['camera_ok'])
            finally:
                devices.close()

    def test_camera_name_selection(self):
        """2. Selection by camera name: uses preferred camera by descriptive name."""
        detected = [
            {'id': 0, 'device': '/dev/video0', 'name': 'HP Wide Vision HD Camera: HP Wi', 'type': 'v4l2'},
            {'id': 2, 'device': '/dev/video2', 'name': 'C922 Pro Stream Webcam', 'type': 'v4l2'}
        ]
        def mock_cap(target):
            cap = MagicMock()
            cap.isOpened.return_value = True
            cap.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))
            return cap

        with patch('libs.device_utils.detect_cameras', return_value=detected), \
             patch('libs.device_utils.cv2.VideoCapture', side_effect=mock_cap):
            # Test selecting C922 by name
            devices_c922 = DeviceUtils(printer_name=None, cv2_port='C922 Pro Stream Webcam')
            try:
                self.assertIsNotNone(devices_c922._preview)
                self.assertEqual(devices_c922._preview.port, 2)
                self.assertIn('C922', devices_c922._preview.device_name)
            finally:
                devices_c922.close()

            # Test selecting HP by name
            devices_hp = DeviceUtils(printer_name=None, cv2_port='HP Wide Vision HD Camera: HP Wi')
            try:
                self.assertIsNotNone(devices_hp._preview)
                self.assertEqual(devices_hp._preview.port, 0)
                self.assertIn('HP', devices_hp._preview.device_name)
            finally:
                devices_hp.close()

    def test_camera_name_disconnected_fallback(self):
        """3. Configured camera by name not available -> falls back to available camera."""
        hp_only = [
            {'id': 0, 'device': '/dev/video0', 'name': 'HP Wide Vision HD Camera: HP Wi', 'type': 'v4l2'}
        ]
        def mock_cap_hp(target):
            cap = MagicMock()
            cap.isOpened.return_value = True
            cap.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))
            return cap

        with patch('libs.device_utils.detect_cameras', return_value=hp_only), \
             patch('libs.device_utils.cv2.VideoCapture', side_effect=mock_cap_hp):
            # Preferred camera is C922, but only HP is connected
            devices = DeviceUtils(printer_name=None, cv2_port='C922 Pro Stream Webcam')
            try:
                self.assertIsNotNone(devices._preview)
                self.assertNotIsInstance(devices._preview, DummyCamera)
                self.assertEqual(devices._preview.port, 0)
                self.assertIn('HP', devices._preview.device_name)
                self.assertTrue(devices.get_diagnostic_status()['camera_ok'])
            finally:
                devices.close()

    def test_web_server_camera_dynamic_choices(self):
        """5. Web admin interface generates dynamic choices from detect_cameras()."""
        from libs.web_server import WebServer
        mock_cams = [
            {'id': 0, 'device': '/dev/video0', 'name': 'HP Wide Vision', 'type': 'v4l2'},
            {'id': 2, 'device': '/dev/video2', 'name': 'C922 Pro Stream Webcam', 'type': 'v4l2'}
        ]
        with patch('libs.device_utils.detect_cameras', return_value=mock_cams):
            ws = WebServer(save_directory='./DCIM')
            sections = ws._get_config_form_sections()
            cam_section = next((s for s in sections if s['title'] == 'Camera'), None)
            self.assertIsNotNone(cam_section)

            field = next((f for f in cam_section['fields'] if f['option'] == 'CAMERA'), None)
            self.assertIsNotNone(field)
            self.assertEqual(field['control'], 'select')

            choices = field['choices']
            # First choice should be auto
            self.assertEqual(choices[0][0], 'auto')
            self.assertTrue(choices[0][1].startswith('Auto'))

            # Connected cameras should be listed with name and device
            self.assertIn(('HP Wide Vision', 'HP Wide Vision (/dev/video0)'), choices)
            self.assertIn(('C922 Pro Stream Webcam', 'C922 Pro Stream Webcam (/dev/video2)'), choices)

            # Test preserving a disconnected camera
            sections_disconnected = ws._get_config_form_sections({'Camera__CAMERA': 'Disconnected Camera Pro'})
            cam_field_disc = next(f for f in next(s for s in sections_disconnected if s['title'] == 'Camera')['fields'] if f['option'] == 'CAMERA')
            self.assertIn(('Disconnected Camera Pro', 'Current: Disconnected Camera Pro (not detected)'), cam_field_disc['choices'])
            self.assertEqual(cam_field_disc['value'], 'Disconnected Camera Pro')


class TestStartScreenAdminButton(unittest.TestCase):
    """Tests for StartScreen admin web button and WebServer dynamic URL resolution."""

    def test_web_server_get_local_ip(self):
        ip = WebServer.get_local_ip()
        self.assertIsInstance(ip, str)
        self.assertTrue(len(ip) > 0)
        parts = ip.split('.')
        self.assertEqual(len(parts), 4)

    def test_web_server_get_admin_url(self):
        ws = WebServer(save_directory='./DCIM', port=5000)
        url = ws.get_admin_url()
        self.assertTrue(url.startswith('http://'))
        self.assertTrue(url.endswith(':5000/admin'))
        self.assertNotIn('0.0.0.0', url)

    def test_start_screen_admin_button_creation_and_position(self):
        from libs.screens import StartScreen, ICON_ADMIN
        mock_app = MagicMock()
        mock_app.STARTSCREEN_TEXT_COLOR = '#FFFFFF'
        mock_app.STARTSCREEN_BACKGROUND_IMAGE = 'assets/backgrounds/bg_start.jpeg'
        mock_app.STARTSCREEN_SHOW_TITLE = True
        mock_app.STARTSCREEN_SHOW_INSTRUCTIONS = True
        mock_app.APP_VERSION = '1.0'
        mock_app.t = lambda k, **kw: k
        mock_app.print_formats = [1, 2]
        mock_app.selected_format = 0
        mock_app.web_server = WebServer(save_directory='./DCIM', port=5000)

        screen = StartScreen(mock_app)
        self.assertTrue(hasattr(screen, 'btn_admin'))
        self.assertEqual(screen.btn_admin.children[0].text, ICON_ADMIN)
        self.assertGreater(screen.btn_admin.x, screen.btn_change_template.x)

    def test_start_screen_on_admin_opens_browser(self):
        from libs.screens import StartScreen
        import time

        mock_app = MagicMock()
        mock_app.STARTSCREEN_TEXT_COLOR = '#FFFFFF'
        mock_app.STARTSCREEN_BACKGROUND_IMAGE = 'assets/backgrounds/bg_start.jpeg'
        mock_app.STARTSCREEN_SHOW_TITLE = True
        mock_app.STARTSCREEN_SHOW_INSTRUCTIONS = True
        mock_app.APP_VERSION = '1.0'
        mock_app.t = lambda k, **kw: k
        mock_app.print_formats = [1, 2]
        mock_app.selected_format = 0
        mock_app.web_server = WebServer(save_directory='./DCIM', port=5000)

        screen = StartScreen(mock_app)
        with patch('webbrowser.open') as mock_open:
            mock_open.return_value = True
            screen.on_admin(None)
            time.sleep(0.05)
            mock_open.assert_called_once()
            url = mock_open.call_args[0][0]
            self.assertTrue(url.startswith('http://'))
            self.assertTrue(url.endswith(':5000/admin'))


class TestAdminConfigReviewAndFeedback(unittest.TestCase):
    """Tests for Review slideshow and Feedback configuration in the web admin panel."""

    def setUp(self):
        self.ws = WebServer(save_directory='./DCIM')

    def test_1_fields_appear_in_admin_panel(self):
        """1. Both Feedback and Review slideshow fields appear in the admin panel."""
        sections = self.ws._get_config_form_sections()

        # Check Review slideshow section and field
        review_section = next((s for s in sections if s['title'] == 'Review slideshow'), None)
        self.assertIsNotNone(review_section, "Section 'Review slideshow' not found in config form sections")
        review_field = next((f for f in review_section['fields'] if f['option'] == 'SLIDE_DURATION'), None)
        self.assertIsNotNone(review_field, "Option 'SLIDE_DURATION' not found in Review section")
        self.assertEqual(review_field['section'], 'Review')
        self.assertEqual(review_field['control'], 'number')
        self.assertEqual(review_field['number_type'], 'float')
        self.assertGreaterEqual(review_field['step'], 0.1)

        # Check Feedback section and field
        feedback_section = next((s for s in sections if s['title'] == 'Feedback'), None)
        self.assertIsNotNone(feedback_section, "Section 'Feedback' not found in config form sections")
        feedback_field = next((f for f in feedback_section['fields'] if f['option'] == 'ENABLED'), None)
        self.assertIsNotNone(feedback_field, "Option 'ENABLED' not found in Feedback section")
        self.assertEqual(feedback_field['section'], 'Feedback')
        self.assertEqual(feedback_field['control'], 'checkbox')

    def test_2_fields_read_configured_values_and_defaults(self):
        """2. Both fields correctly read current values from config, or default when missing."""
        sample_ini = (
            "[Review]\n"
            "SLIDE_DURATION = 3.5\n"
            "CROSSFADE_DURATION = 0.45\n\n"
            "[Feedback]\n"
            "ENABLED = True\n"
        )
        with patch.object(self.ws, '_load_config_text', return_value=sample_ini):
            sections = self.ws._get_config_form_sections()
            review_field = next(f for s in sections if s['title'] == 'Review slideshow' for f in s['fields'] if f['option'] == 'SLIDE_DURATION')
            feedback_field = next(f for s in sections if s['title'] == 'Feedback' for f in s['fields'] if f['option'] == 'ENABLED')

            self.assertEqual(review_field['value'], '3.5')
            self.assertEqual(feedback_field['value'], True)
            self.assertTrue(feedback_field['checked'])

        # Test with Feedback = False and Review = 1.8
        sample_ini_disabled = (
            "[Review]\n"
            "SLIDE_DURATION = 1.8\n\n"
            "[Feedback]\n"
            "ENABLED = False\n"
        )
        with patch.object(self.ws, '_load_config_text', return_value=sample_ini_disabled):
            sections = self.ws._get_config_form_sections()
            review_field = next(f for s in sections if s['title'] == 'Review slideshow' for f in s['fields'] if f['option'] == 'SLIDE_DURATION')
            feedback_field = next(f for s in sections if s['title'] == 'Feedback' for f in s['fields'] if f['option'] == 'ENABLED')

            self.assertEqual(review_field['value'], '1.8')
            self.assertEqual(feedback_field['value'], False)
            self.assertFalse(feedback_field['checked'])

        # Test when [Review] and [Feedback] are missing from config
        minimal_ini = "[Global]\nFULLSCREEN = False\n"
        with patch.object(self.ws, '_load_config_text', return_value=minimal_ini):
            sections = self.ws._get_config_form_sections()
            review_field = next(f for s in sections if s['title'] == 'Review slideshow' for f in s['fields'] if f['option'] == 'SLIDE_DURATION')
            feedback_field = next(f for s in sections if s['title'] == 'Feedback' for f in s['fields'] if f['option'] == 'ENABLED')

            self.assertEqual(review_field['value'], '2.0')
            self.assertFalse(feedback_field['checked'])

    def test_3_save_feedback_enabled_true_and_false(self):
        """3. Saving Feedback ENABLED as True or False updates config correctly."""
        base_ini = (
            "[Review]\n"
            "SLIDE_DURATION = 2.0\n\n"
            "[Feedback]\n"
            "# Rating screen\n"
            "ENABLED = False\n"
        )
        # Update Feedback to True
        updates_true = {('Feedback', 'ENABLED'): 'True'}
        result_true = self.ws._apply_config_updates(base_ini, updates_true)
        self.assertIn("ENABLED = True", result_true)
        self.assertNotIn("ENABLED = False", result_true)
        self.assertIn("# Rating screen", result_true)
        self.assertIn("SLIDE_DURATION = 2.0", result_true)

        # Update Feedback to False
        base_ini_enabled = (
            "[Feedback]\n"
            "ENABLED = True\n"
        )
        updates_false = {('Feedback', 'ENABLED'): 'False'}
        result_false = self.ws._apply_config_updates(base_ini_enabled, updates_false)
        self.assertIn("ENABLED = False", result_false)
        self.assertNotIn("ENABLED = True", result_false)

        # Verify coercion logic for checkbox
        feedback_spec = self.ws._get_config_field_spec('Feedback', 'ENABLED')
        self.assertEqual(self.ws._coerce_form_field_value(feedback_spec, True, 'False'), 'True')
        self.assertEqual(self.ws._coerce_form_field_value(feedback_spec, False, 'True'), 'False')

    def test_4_save_slide_duration_decimal(self):
        """4. Saving SLIDE_DURATION with a decimal value updates config and preserves other settings."""
        base_ini = (
            "[Review]\n"
            "# Slide duration\n"
            "SLIDE_DURATION = 2.0\n"
            "CROSSFADE_DURATION = 0.45\n\n"
            "[Feedback]\n"
            "ENABLED = False\n"
        )
        updates = {('Review', 'SLIDE_DURATION'): '2.5'}
        result = self.ws._apply_config_updates(base_ini, updates)
        self.assertIn("SLIDE_DURATION = 2.5", result)
        self.assertIn("CROSSFADE_DURATION = 0.45", result)
        self.assertIn("# Slide duration", result)
        self.assertIn("ENABLED = False", result)

        # Verify coercion logic for float field
        review_spec = self.ws._get_config_field_spec('Review', 'SLIDE_DURATION')
        self.assertEqual(self.ws._coerce_form_field_value(review_spec, '2.5', '2.0'), '2.5')
        self.assertEqual(self.ws._coerce_form_field_value(review_spec, '0.5', '2.0'), '0.5')
        # Empty raises ValueError
        with self.assertRaises(ValueError):
            self.ws._coerce_form_field_value(review_spec, '', '2.0')
        # Value below min raises ValueError
        with self.assertRaises(ValueError):
            self.ws._coerce_form_field_value(review_spec, '0.1', '2.0')


if __name__ == '__main__':
    unittest.main()
