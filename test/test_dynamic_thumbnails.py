import os
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout

from libs.screens import CountdownScreen, ThumbnailSlot, ScreenMgr
from libs.template_collage import (
    TemplateCollage,
    validate_template_structure,
    MIN_TEMPLATE_PHOTOS,
    MAX_TEMPLATE_PHOTOS,
)
from libs.web_server import WebServer


def _make_template_dict(name="Test", photo_count=3, width=1800, height=1200):
    photos = []
    slot_w = width // max(1, photo_count)
    for i in range(photo_count):
        photos.append({
            'x': i * slot_w,
            'y': 0,
            'width': slot_w,
            'height': height,
        })
    return {
        'name': name,
        'description': f'Template with {photo_count} photos',
        'page': {'width': width, 'height': height},
        'photos': photos,
        'print_params': {'PageSize': '4x6in', 'print-scaling': 'fit'},
    }


class TestTemplateStructureValidation(unittest.TestCase):
    """Test validation of template photo counts and structure."""

    def test_valid_photo_counts_1_to_4(self):
        for count in range(1, 5):
            t = _make_template_dict(photo_count=count)
            is_valid, err = validate_template_structure(t)
            self.assertTrue(is_valid, f"Template with {count} photos should be valid, got error: {err}")
            self.assertIsNone(err)

    def test_rejection_of_invalid_counts(self):
        # 0 photos
        t0 = _make_template_dict(photo_count=0)
        is_valid, err = validate_template_structure(t0)
        self.assertFalse(is_valid)
        self.assertIn("between 1 and 4 photos", err)

        # 5 photos
        t5 = _make_template_dict(photo_count=5)
        is_valid, err = validate_template_structure(t5)
        self.assertFalse(is_valid)
        self.assertIn("between 1 and 4 photos", err)

    def test_rejection_of_malformed_structures(self):
        # Not a dict
        self.assertFalse(validate_template_structure("not a dict")[0])
        # Missing name
        t = _make_template_dict()
        del t['name']
        self.assertFalse(validate_template_structure(t)[0])
        # Missing page
        t = _make_template_dict()
        del t['page']
        self.assertFalse(validate_template_structure(t)[0])
        # Missing photos
        t = _make_template_dict()
        del t['photos']
        self.assertFalse(validate_template_structure(t)[0])
        # Photos not a list
        t = _make_template_dict()
        t['photos'] = "not a list"
        self.assertFalse(validate_template_structure(t)[0])
        # Photo missing dimensions
        t = _make_template_dict(photo_count=1)
        t['photos'] = [{'x': 0, 'y': 0}]
        self.assertFalse(validate_template_structure(t)[0])


class TestTemplateCollagePhotoCounts(unittest.TestCase):
    """Test TemplateCollage class photo loading and rejection."""

    def test_template_collage_loads_1_to_4_photos(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            for count in range(1, 5):
                t_dict = _make_template_dict(name=f"Template {count}", photo_count=count)
                fpath = os.path.join(tmp_dir, f"template_{count}.json")
                with open(fpath, 'w', encoding='utf-8') as f:
                    json.dump(t_dict, f)

                collage = TemplateCollage(fpath)
                self.assertEqual(collage.get_photos_required(), count)

    def test_template_collage_rejects_invalid_photo_counts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            # 0 photos
            fpath0 = os.path.join(tmp_dir, "template_0.json")
            with open(fpath0, 'w', encoding='utf-8') as f:
                json.dump(_make_template_dict(photo_count=0), f)
            with self.assertRaises(ValueError):
                TemplateCollage(fpath0)

            # 5 photos
            fpath5 = os.path.join(tmp_dir, "template_5.json")
            with open(fpath5, 'w', encoding='utf-8') as f:
                json.dump(_make_template_dict(photo_count=5), f)
            with self.assertRaises(ValueError):
                TemplateCollage(fpath5)


class TestWebServerTemplateApiPhotoCounts(unittest.TestCase):
    """Test WebServer template creation and validation for 1 to 4 photos."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.save_dir = os.path.join(self.tmp_dir.name, 'save')
        os.makedirs(self.save_dir, exist_ok=True)
        self.server = WebServer(save_directory=self.save_dir)
        self.server.templates_directory = os.path.join(self.tmp_dir.name, 'templates')
        os.makedirs(self.server.templates_directory, exist_ok=True)
        self.client = self.server.app.test_client()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_save_templates_1_to_4_photos(self):
        for count in range(1, 5):
            payload = {
                'filename': f'test_{count}_photos.json',
                'template': _make_template_dict(name=f'T{count}', photo_count=count),
            }
            res = self.client.post('/api/templates', json=payload)
            self.assertEqual(res.status_code, 200, f"Saving {count} photos failed: {res.data}")
            saved_path = os.path.join(self.server.templates_directory, f'test_{count}_photos.json')
            self.assertTrue(os.path.exists(saved_path))
            with open(saved_path, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)
            self.assertEqual(len(saved_data['photos']), count)

    def test_reject_save_with_invalid_photo_counts(self):
        # 0 photos rejected
        res0 = self.client.post('/api/templates', json={
            'filename': 'invalid_0.json',
            'template': _make_template_dict(photo_count=0),
        })
        self.assertEqual(res0.status_code, 400)
        self.assertIn(b'between 1 and 4 photos', res0.data)

        # 5 photos rejected
        res5 = self.client.post('/api/templates', json={
            'filename': 'invalid_5.json',
            'template': _make_template_dict(photo_count=5),
        })
        self.assertEqual(res5.status_code, 400)
        self.assertIn(b'between 1 and 4 photos', res5.data)


class TestDynamicCountdownScreenThumbnails(unittest.TestCase):
    """Test dynamic thumbnail slots in CountdownScreen."""

    def _create_mock_app(self, photo_count=3):
        app = MagicMock()
        app.COUNTDOWN = 5
        app.CAPTURE_TIMEOUT = 15
        app.PROCESSING_TIMEOUT = 30
        app.BLUR_CAMERA = False
        app.PREVIEW_BLUR_REFRESH_FRAMES = 1
        app.devices.get_preview_fps.return_value = 30
        app.t.return_value = 'Loading...'
        app.THUMBNAILS_ASPECT_RATIO = 16.0 / 9.0
        app.THUMBNAILS_IMAGE_FIT_MODE = 'contain'
        app.selected_format = 0
        app.get_shots_to_take.return_value = photo_count
        app.get_format_aspect_ratio.return_value = 16.0 / 9.0
        app.has_pending_photo_tasks.return_value = False
        app.has_process_failed.return_value = False
        app.is_shot_completed.return_value = False
        app.ringled = None
        return app

    def test_countdown_screen_slots_match_photo_count_1_to_4(self):
        for count in range(1, 5):
            app = self._create_mock_app(photo_count=count)
            screen = CountdownScreen(app)
            self.assertEqual(len(screen.thumbnail_slots), count, f"Expected {count} thumbnail slots")
            self.assertEqual(len(screen.thumbnails_container.children), count)

    def test_switching_templates_updates_slots_dynamically(self):
        app = self._create_mock_app(photo_count=3)
        screen = CountdownScreen(app)
        self.assertEqual(len(screen.thumbnail_slots), 3)

        # Switch to 2-photo template
        app.get_shots_to_take.return_value = 2
        screen.on_entry({'format': 1, 'shot': 0})
        self.assertEqual(len(screen.thumbnail_slots), 2)
        self.assertEqual(len(screen.thumbnails_container.children), 2)

        # Switch to 4-photo template
        app.get_shots_to_take.return_value = 4
        screen.on_entry({'format': 2, 'shot': 0})
        self.assertEqual(len(screen.thumbnail_slots), 4)
        self.assertEqual(len(screen.thumbnails_container.children), 4)

        # Switch to 1-photo template
        app.get_shots_to_take.return_value = 1
        screen.on_entry({'format': 3, 'shot': 0})
        self.assertEqual(len(screen.thumbnail_slots), 1)
        self.assertEqual(len(screen.thumbnails_container.children), 1)
        self.assertEqual(screen.thumbnails_container.opacity, 1)

    def test_thumbnails_container_height_and_aspect_ratio(self):
        app = self._create_mock_app(photo_count=4)
        app.THUMBNAILS_ASPECT_RATIO = 4.0 / 3.0
        app.THUMBNAILS_IMAGE_FIT_MODE = 'cover'

        screen = CountdownScreen(app)
        screen._update_thumbnails_layout()

        # All slots must have the configured aspect ratio and fit mode
        for slot in screen.thumbnail_slots:
            self.assertEqual(slot.image.fit_mode, 'cover')
            # Check slot height matches width / (4/3)
            expected_h = slot.width / (4.0 / 3.0)
            self.assertAlmostEqual(slot.height, expected_h, places=1)


if __name__ == '__main__':
    unittest.main()
