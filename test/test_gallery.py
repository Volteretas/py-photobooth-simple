import os
import sys
from datetime import datetime
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

os.environ["KIVY_NO_ARGS"] = "1"

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np

from libs.config import Config
from libs.file_utils import FileUtils
from libs.screens import (
    ScreenMgr,
    StartScreen,
    GalleryScreen,
    GalleryDetailScreen,
    ReviewScreen,
    CountdownScreen,
    PrintStatusPopup,
    DeleteConfirmPopup,
    DeleteErrorPopup,
    ICON_GALLERY,
    ICON_ADMIN,
    ICON_TEMPLATE,
    ICON_DELETE,
)
from photoboothapp import PhotoboothApp


def create_dummy_image(path, width=400, height=300):
    """Helper to create a valid JPEG file for image loading and copy tests."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:] = (100, 150, 200)
    cv2.imwrite(str(path), img)


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


class TestGalleryFeature(unittest.TestCase):
    """Test suite covering the 10 core requirements of the PhotoBooth Gallery."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mock_cfg = get_mock_config(self.temp_dir.name)

        # Patch external hardware/services to prevent side-effects during testing
        self.patchers = [
            patch('photoboothapp.Config', return_value=self.mock_cfg),
            patch('photoboothapp.DeviceUtils'),
            patch('photoboothapp.RingLed'),
            patch('photoboothapp.UsbTransfer'),
            patch('photoboothapp.WebServer'),
        ]
        for p in self.patchers:
            p.start()

        self.app = PhotoboothApp()
        self.app.transition_to = MagicMock()
        self.app.request_transition_to = MagicMock()

    def tearDown(self):
        try:
            self.app.on_stop()
        except Exception:
            pass
        for p in reversed(self.patchers):
            p.stop()
        self.temp_dir.cleanup()

    def test_1_creation_of_gallery_directories(self):
        """1. Gallery directories DCIM/gallery/strips, photos, and small/strips are created."""
        expected_strips_dir = os.path.join(self.temp_dir.name, 'gallery', 'strips')
        expected_photos_dir = os.path.join(self.temp_dir.name, 'gallery', 'photos')
        expected_small_dir = os.path.join(self.temp_dir.name, 'gallery', 'small', 'strips')

        self.assertEqual(self.app.gallery_strips_directory, expected_strips_dir)
        self.assertEqual(self.app.gallery_photos_directory, expected_photos_dir)
        self.assertEqual(self.app.gallery_small_strips_directory, expected_small_dir)

        self.assertTrue(os.path.exists(expected_strips_dir), "gallery/strips/ directory must exist")
        self.assertTrue(os.path.exists(expected_photos_dir), "gallery/photos/ directory must exist")
        self.assertTrue(os.path.exists(expected_small_dir), "gallery/small/strips/ directory must exist")
        self.assertTrue(os.path.isdir(expected_strips_dir))
        self.assertTrue(os.path.isdir(expected_photos_dir))
        self.assertTrue(os.path.isdir(expected_small_dir))

    def test_2_generation_of_session_id_without_collisions(self):
        """2. Session ID generation uses high-precision timestamp and avoids collisions."""
        fixed_dt = datetime(2026, 10, 4, 11, 32, 15, 789123)
        session_id_1 = self.app.generate_session_id(now=fixed_dt)

        self.assertEqual(session_id_1, '2026-10-04_11-32-15_789')

        # Simulate the first session file existing in gallery/strips/
        strip_file_1 = os.path.join(self.app.gallery_strips_directory, f'{session_id_1}.jpg')
        with open(strip_file_1, 'w') as f:
            f.write('dummy')

        # A consecutive session with the exact same millisecond timestamp should get a suffix
        session_id_2 = self.app.generate_session_id(now=fixed_dt)
        self.assertEqual(session_id_2, '2026-10-04_11-32-15_789_01')

        # Simulate the second session file also existing
        strip_file_2 = os.path.join(self.app.gallery_strips_directory, f'{session_id_2}.jpg')
        with open(strip_file_2, 'w') as f:
            f.write('dummy')

        # A third session at the same millisecond timestamp should get _02
        session_id_3 = self.app.generate_session_id(now=fixed_dt)
        self.assertEqual(session_id_3, '2026-10-04_11-32-15_789_02')

    def test_3_save_collage_and_small_thumbnail(self):
        """3. Permanently saving a session copies collage.jpg to strips/ and thumbnail to small/strips/."""
        # Create tmp collage files
        collage_src = self.app.get_collage()
        collage_small_src = FileUtils.get_small_path(collage_src)
        create_dummy_image(collage_src, width=600, height=1800)
        create_dummy_image(collage_small_src, width=200, height=600)

        session_id = self.app.save_collage()
        self.assertIsNotNone(session_id)

        expected_strip = os.path.join(self.app.gallery_strips_directory, f'{session_id}.jpg')
        expected_small = os.path.join(self.app.gallery_small_strips_directory, f'{session_id}_small.jpg')
        strip_in_strips = os.path.join(self.app.gallery_strips_directory, f'{session_id}_small.jpg')

        self.assertTrue(os.path.exists(expected_strip), "Final strip collage must be saved in gallery/strips/")
        self.assertTrue(os.path.exists(expected_small), "Strip thumbnail must be saved in gallery/small/strips/")
        self.assertFalse(os.path.exists(strip_in_strips), "gallery/strips/ must NOT contain _small.jpg")
        self.assertEqual(self.app.last_saved_session_id, session_id)
        self.assertEqual(self.app.last_saved_strip_path, expected_strip)

        # Fallback test: when collage_small.jpg does not exist in tmp, save_collage generates it in small/strips/
        FileUtils.remove_file(collage_small_src)
        self.assertFalse(os.path.exists(collage_small_src))

        session_id_fallback = self.app.save_collage()
        expected_small_fallback = os.path.join(self.app.gallery_small_strips_directory, f'{session_id_fallback}_small.jpg')
        self.assertTrue(os.path.exists(expected_small_fallback), "Thumbnail should be generated if missing from tmp")
        self.assertFalse(os.path.exists(os.path.join(self.app.gallery_strips_directory, f'{session_id_fallback}_small.jpg')))

    def test_4_save_all_individual_photos(self):
        """4. Permanently saving a session copies all individual captures to flat gallery/photos/."""
        collage_src = self.app.get_collage()
        create_dummy_image(collage_src, width=600, height=1800)

        # Create 3 individual captures
        shot_files = [self.app.get_shot(i) for i in range(3)]
        for i, shot_file in enumerate(shot_files):
            create_dummy_image(shot_file, width=800, height=600)

        session_id = self.app.save_collage()
        self.assertIsNotNone(session_id)

        # All 3 photos must be present with session prefix in gallery/photos/
        expected_photo_1 = os.path.join(self.app.gallery_photos_directory, f'{session_id}_01.jpg')
        expected_photo_2 = os.path.join(self.app.gallery_photos_directory, f'{session_id}_02.jpg')
        expected_photo_3 = os.path.join(self.app.gallery_photos_directory, f'{session_id}_03.jpg')

        self.assertTrue(os.path.exists(expected_photo_1))
        self.assertTrue(os.path.exists(expected_photo_2))
        self.assertTrue(os.path.exists(expected_photo_3))

        # Must be flat: no per-session subdirectories inside gallery/photos/
        for entry in os.listdir(self.app.gallery_photos_directory):
            entry_path = os.path.join(self.app.gallery_photos_directory, entry)
            self.assertTrue(os.path.isfile(entry_path), f"Unexpected subdirectory found: {entry}")

        self.assertEqual(len(self.app.last_saved_photos), 3)

    def test_5_listing_and_sorting_of_strips(self):
        """5. Gallery lists strips ordered newest first, without including thumbnails as standalone strips."""
        # Create 3 strip pairs with different timestamps
        timestamps = [
            '2026-10-04_09-30-00_100',
            '2026-10-04_14-15-20_450',
            '2026-10-04_11-00-10_880',
        ]
        for ts in timestamps:
            strip_path = os.path.join(self.app.gallery_strips_directory, f'{ts}.jpg')
            small_path = os.path.join(self.app.gallery_small_strips_directory, f'{ts}_small.jpg')
            create_dummy_image(strip_path, 200, 600)
            create_dummy_image(small_path, 100, 300)

        gallery_screen = GalleryScreen(self.app)
        strips = gallery_screen._get_strips_list()

        # Should find exactly 3 strips (not 6)
        self.assertEqual(len(strips), 3)

        # Strips should be sorted reverse-chronologically (newest first)
        self.assertEqual(strips[0]['session_id'], '2026-10-04_14-15-20_450')
        self.assertEqual(strips[1]['session_id'], '2026-10-04_11-00-10_880')
        self.assertEqual(strips[2]['session_id'], '2026-10-04_09-30-00_100')

        # Each entry must reference the correct small thumbnail in gallery/small/strips/
        for strip_info in strips:
            self.assertTrue(strip_info['small_path'].endswith('_small.jpg'))
            self.assertIn('small/strips', strip_info['small_path'])
            self.assertTrue(os.path.exists(strip_info['small_path']))

    def test_6_behavior_when_gallery_is_empty(self):
        """6. GalleryScreen shows friendly empty state message when no strips exist."""
        gallery_screen = GalleryScreen(self.app)
        gallery_screen.on_entry()

        self.assertEqual(gallery_screen.empty_label.opacity, 1.0)
        self.assertEqual(gallery_screen.scroll_view.opacity, 0.0)
        self.assertEqual(len(gallery_screen.cards_grid.children), 0)
        self.assertEqual(gallery_screen.empty_label.text, self.app.t('gallery.empty'))

    def test_7_selection_of_strip(self):
        """7. Selecting a strip in GalleryScreen triggers transition to GalleryDetailScreen with parameters."""
        ts = '2026-10-04_12-00-00_123'
        strip_path = os.path.join(self.app.gallery_strips_directory, f'{ts}.jpg')
        small_path = os.path.join(self.app.gallery_small_strips_directory, f'{ts}_small.jpg')
        create_dummy_image(strip_path, 200, 600)
        create_dummy_image(small_path, 100, 300)

        gallery_screen = GalleryScreen(self.app)
        gallery_screen.on_entry()

        self.assertEqual(len(gallery_screen.strip_cards), 1)
        card = gallery_screen.strip_cards[0]
        self.assertEqual(card.session_id, ts)
        self.assertEqual(card.strip_path, strip_path)

        # Trigger selection
        gallery_screen.on_strip_selected(card)
        self.app.transition_to.assert_called_once_with(
            ScreenMgr.GALLERY_DETAIL,
            strip_path=strip_path,
            session_id=ts,
        )

    def test_8_reprint_uses_correct_file(self):
        """8. Reprint from gallery detail prints the exact strip file and tracks print stat."""
        ts = '2026-10-04_13-00-00_555'
        strip_path = os.path.join(self.app.gallery_strips_directory, f'{ts}.jpg')
        create_dummy_image(strip_path, 200, 600)

        self.app.has_printer = MagicMock(return_value=True)
        self.app.devices.has_printer.return_value = True
        self.app.devices.print.return_value = 'task-reprint-1'
        self.app.stats_store = MagicMock()
        self.app.stats_store.can_print.return_value = True

        # Test trigger_reprint directly on app
        task_id = self.app.trigger_reprint(strip_path, copies=1)
        self.assertEqual(task_id, 'task-reprint-1')
        self.app.devices.print.assert_called_once()
        called_args = self.app.devices.print.call_args[0]
        self.assertEqual(called_args[0], strip_path)
        self.app.stats_store.track_photo_printed.assert_called_once()

        # Test GalleryDetailScreen on_reprint
        detail_screen = GalleryDetailScreen(self.app)
        detail_screen.on_entry({'strip_path': strip_path, 'session_id': ts})

        self.assertEqual(detail_screen.strip_image.source, strip_path)
        self.assertEqual(detail_screen.date_label.text, '2026-10-04  13:00:00')

        detail_screen.on_reprint(None)
        self.assertIsNotNone(detail_screen.print_popup)
        self.assertEqual(detail_screen.print_popup.file_path, strip_path)

        # Texture release on exit
        detail_screen.on_exit()
        self.assertEqual(detail_screen.strip_image.source, '')

    def test_9_retake_leaves_no_garbage_in_gallery(self):
        """9. Retake in ReviewScreen discards captures and leaves no files in gallery/."""
        # Setup files in tmp as if capture sequence finished
        collage_src = self.app.get_collage()
        shot_src = self.app.get_shot(0)
        create_dummy_image(collage_src, 200, 600)
        create_dummy_image(shot_src, 800, 600)

        review_screen = ReviewScreen(self.app)
        review_screen.on_entry({'format': 0})

        # At this point (just entering ReviewScreen), gallery must still be empty!
        self.assertEqual(os.listdir(self.app.gallery_strips_directory), [])
        self.assertEqual(os.listdir(self.app.gallery_photos_directory), [])

        # User chooses Retake
        review_screen.retake_event(None)

        # Gallery must remain completely empty
        self.assertEqual(os.listdir(self.app.gallery_strips_directory), [])
        self.assertEqual(os.listdir(self.app.gallery_photos_directory), [])

        # Temporary files in tmp must be purged
        self.assertFalse(os.path.exists(collage_src))
        self.assertFalse(os.path.exists(shot_src))

    def test_10_incomplete_session_not_saved_as_finished(self):
        """10. Incomplete session (aborted or empty tmp) is not saved as finished."""
        # Case A: calling save_collage with empty tmp returns None
        result = self.app.save_collage()
        self.assertIsNone(result)
        self.assertIsNone(self.app.last_saved_session_id)
        self.assertEqual(os.listdir(self.app.gallery_strips_directory), [])
        self.assertEqual(os.listdir(self.app.gallery_photos_directory), [])

        # Case B: tmp has capture but no collage.jpg
        shot_src = self.app.get_shot(0)
        create_dummy_image(shot_src, 800, 600)
        result_no_collage = self.app.save_collage()
        self.assertIsNone(result_no_collage)
        self.assertEqual(os.listdir(self.app.gallery_strips_directory), [])
        self.assertEqual(os.listdir(self.app.gallery_photos_directory), [])

        # Case C: CountdownScreen home_event aborts session without saving
        from kivy.input.providers.mouse import MouseMotionEvent
        countdown_screen = CountdownScreen(self.app)
        countdown_screen._current_shot = 1
        mock_touch = MagicMock(spec=MouseMotionEvent)
        mock_obj = MagicMock()
        mock_obj.last_touch = mock_touch
        countdown_screen.home_event(mock_obj)
        self.app.transition_to.assert_called_with(ScreenMgr.START)
        self.assertEqual(os.listdir(self.app.gallery_strips_directory), [])
        self.assertEqual(os.listdir(self.app.gallery_photos_directory), [])

    def test_11_start_screen_gallery_button(self):
        """11. StartScreen features a Gallery button next to Template and Admin buttons."""
        start_screen = StartScreen(self.app)

        self.assertTrue(hasattr(start_screen, 'btn_gallery'), "StartScreen must have btn_gallery")
        self.assertEqual(start_screen.btn_gallery.children[0].text, ICON_GALLERY)

        # Verify button cluster layout:
        # Left cluster: [ Template ] [ Gallery ]
        # Right cluster: [ Fullscreen ] [ Admin ] [ Close ]
        self.assertGreater(start_screen.btn_gallery.x, start_screen.btn_change_template.x)
        self.assertGreater(start_screen.btn_admin.x, start_screen.btn_fullscreen.x)
        self.assertGreater(start_screen.btn_close.x, start_screen.btn_admin.x)

        # Trigger gallery button
        start_screen.on_gallery(None)
        self.app.transition_to.assert_called_with(ScreenMgr.GALLERY)

    def test_12_thumbnails_stored_in_small_strips_directory(self):
        """12. Miniatures are saved in gallery/small/strips/ and not inside gallery/strips/."""
        collage_src = self.app.get_collage()
        collage_small_src = FileUtils.get_small_path(collage_src)
        create_dummy_image(collage_src, 600, 1800)
        create_dummy_image(collage_small_src, 200, 600)

        session_id = self.app.save_collage()
        self.assertIsNotNone(session_id)

        strip_file = os.path.join(self.app.gallery_strips_directory, f'{session_id}.jpg')
        small_file = os.path.join(self.app.gallery_small_strips_directory, f'{session_id}_small.jpg')

        self.assertTrue(os.path.exists(strip_file))
        self.assertTrue(os.path.exists(small_file))

        for f in os.listdir(self.app.gallery_strips_directory):
            self.assertFalse(f.endswith('_small.jpg'), f"Found thumbnail in strips/: {f}")

    def test_13_legacy_thumbnails_migration(self):
        """13. Legacy _small.jpg in gallery/strips/ are moved to gallery/small/strips/ safely."""
        ts = '2026-10-04_10-00-00_111'
        strip_file = os.path.join(self.app.gallery_strips_directory, f'{ts}.jpg')
        legacy_small = os.path.join(self.app.gallery_strips_directory, f'{ts}_small.jpg')
        create_dummy_image(strip_file, 600, 1800)
        create_dummy_image(legacy_small, 200, 600)

        strips = GalleryScreen.get_strips_list(self.app)

        new_small = os.path.join(self.app.gallery_small_strips_directory, f'{ts}_small.jpg')
        self.assertTrue(os.path.exists(new_small), "Legacy thumbnail should be moved to gallery/small/strips/")
        self.assertFalse(os.path.exists(legacy_small), "Legacy thumbnail should be removed from gallery/strips/")
        self.assertTrue(os.path.exists(strip_file), "Original high-res strip must remain intact")
        self.assertEqual(len(strips), 1)
        self.assertEqual(strips[0]['small_path'], new_small)

    def test_14_gallery_screen_scroll_with_many_items(self):
        """14. Gallery holds more elements than visible initially and ScrollView enables vertical scrolling."""
        timestamps = [f'2026-10-04_12-{i:02d}-00_000' for i in range(18)]
        for ts in timestamps:
            create_dummy_image(os.path.join(self.app.gallery_strips_directory, f'{ts}.jpg'), 200, 600)
            create_dummy_image(os.path.join(self.app.gallery_small_strips_directory, f'{ts}_small.jpg'), 100, 300)

        gallery_screen = GalleryScreen(self.app)
        gallery_screen.on_entry()

        self.assertEqual(len(gallery_screen.strip_cards), 18)
        self.assertEqual(len(gallery_screen.cards_grid.children), 18)
        self.assertGreater(gallery_screen.grid_container.height, gallery_screen.scroll_view.height)
        self.assertTrue(gallery_screen.scroll_view.do_scroll_y)

    def test_15_gallery_detail_navigation_and_boundary_arrows(self):
        """15. GalleryDetailScreen navigates between strips and disables/hides arrows at boundaries."""
        timestamps = [
            '2026-10-04_15-00-00_001',
            '2026-10-04_14-00-00_002',
            '2026-10-04_13-00-00_003',
        ]
        for ts in timestamps:
            create_dummy_image(os.path.join(self.app.gallery_strips_directory, f'{ts}.jpg'), 200, 600)
            create_dummy_image(os.path.join(self.app.gallery_small_strips_directory, f'{ts}_small.jpg'), 100, 300)

        detail_screen = GalleryDetailScreen(self.app)

        # 1. Enter on first strip (newest)
        detail_screen.on_entry({'session_id': timestamps[0]})
        self.assertEqual(detail_screen._current_index, 0)
        self.assertEqual(detail_screen.date_label.text, '2026-10-04  15:00:00')
        self.assertTrue(detail_screen.btn_prev.disabled)
        self.assertEqual(detail_screen.btn_prev.opacity, 0.0)
        self.assertFalse(detail_screen.btn_next.disabled)
        self.assertEqual(detail_screen.btn_next.opacity, 1.0)

        # 2. Navigate next -> middle strip
        detail_screen.on_next_strip(None)
        self.assertEqual(detail_screen._current_index, 1)
        self.assertEqual(detail_screen.date_label.text, '2026-10-04  14:00:00')
        self.assertEqual(detail_screen._strip_path, os.path.join(self.app.gallery_strips_directory, f'{timestamps[1]}.jpg'))
        self.assertFalse(detail_screen.btn_prev.disabled)
        self.assertEqual(detail_screen.btn_prev.opacity, 1.0)
        self.assertFalse(detail_screen.btn_next.disabled)
        self.assertEqual(detail_screen.btn_next.opacity, 1.0)

        # 3. Navigate next -> last strip
        detail_screen.on_next_strip(None)
        self.assertEqual(detail_screen._current_index, 2)
        self.assertEqual(detail_screen.date_label.text, '2026-10-04  13:00:00')
        self.assertEqual(detail_screen._strip_path, os.path.join(self.app.gallery_strips_directory, f'{timestamps[2]}.jpg'))
        self.assertTrue(detail_screen.btn_next.disabled)
        self.assertEqual(detail_screen.btn_next.opacity, 0.0)
        self.assertFalse(detail_screen.btn_prev.disabled)
        self.assertEqual(detail_screen.btn_prev.opacity, 1.0)

        # 4. Navigate prev -> back to middle strip
        detail_screen.on_prev_strip(None)
        self.assertEqual(detail_screen._current_index, 1)
        self.assertEqual(detail_screen.date_label.text, '2026-10-04  14:00:00')

    def test_16_reprint_uses_selected_strip_after_navigation(self):
        """16. Reprint uses the currently navigated strip after moving with arrows."""
        timestamps = [
            '2026-10-04_16-00-00_001',
            '2026-10-04_15-00-00_002',
        ]
        for ts in timestamps:
            create_dummy_image(os.path.join(self.app.gallery_strips_directory, f'{ts}.jpg'), 200, 600)
            create_dummy_image(os.path.join(self.app.gallery_small_strips_directory, f'{ts}_small.jpg'), 100, 300)

        self.app.has_printer = MagicMock(return_value=True)
        detail_screen = GalleryDetailScreen(self.app)
        detail_screen.on_entry({'session_id': timestamps[0]})

        self.assertEqual(detail_screen._strip_path, os.path.join(self.app.gallery_strips_directory, f'{timestamps[0]}.jpg'))

        detail_screen.on_next_strip(None)
        expected_path = os.path.join(self.app.gallery_strips_directory, f'{timestamps[1]}.jpg')
        self.assertEqual(detail_screen._strip_path, expected_path)

        detail_screen.on_reprint(None)
        self.assertIsNotNone(detail_screen.print_popup)
        self.assertEqual(detail_screen.print_popup.file_path, expected_path)

    def test_17_delete_button_layout_and_states(self):
        """17. Delete button exists, is positioned next to print button, and updates state."""
        detail_screen = GalleryDetailScreen(self.app)
        self.assertIsNotNone(detail_screen.btn_delete)
        self.assertEqual(detail_screen.btn_delete.icon_widget.text, ICON_DELETE)

        # Initially no image -> disabled with 0.5 opacity
        detail_screen.on_entry({})
        self.assertTrue(detail_screen.btn_delete.disabled)
        self.assertEqual(detail_screen.btn_delete.opacity, 0.5)

        # When image present -> enabled with 1.0 opacity
        ts = '2026-10-04_18-00-00_001'
        img_path = os.path.join(self.app.gallery_strips_directory, f'{ts}.jpg')
        create_dummy_image(img_path)
        detail_screen.on_entry({'session_id': ts})

        self.assertFalse(detail_screen.btn_delete.disabled)
        self.assertEqual(detail_screen.btn_delete.opacity, 1.0)

        # Layout: btn_delete is placed to the left of btn_print
        detail_screen.layout.size = (1920, 1080)
        detail_screen.layout.do_layout()
        detail_screen._update_buttons_pos()
        self.assertLess(detail_screen.btn_delete.x, detail_screen.btn_print.x)

    def test_18_delete_confirmation_popup_cancel(self):
        """18. Clicking delete opens confirm popup; canceling preserves file and selection."""
        ts = '2026-10-04_18-00-00_002'
        img_path = os.path.join(self.app.gallery_strips_directory, f'{ts}.jpg')
        create_dummy_image(img_path)

        detail_screen = GalleryDetailScreen(self.app)
        detail_screen.on_entry({'session_id': ts})
        self.assertIsNone(detail_screen.delete_popup)

        # Open delete popup
        detail_screen.on_delete_strip(None)
        popup = detail_screen.delete_popup
        self.assertIsNotNone(popup)
        self.assertIsInstance(popup, DeleteConfirmPopup)
        self.assertTrue(detail_screen.btn_delete.disabled)
        self.assertGreater(popup.card.width, 400)
        self.assertGreater(popup.card.height, 250)

        # Cancel deletion
        popup._on_cancel(None)
        self.assertIsNone(detail_screen.delete_popup)
        self.assertTrue(os.path.exists(img_path))
        self.assertEqual(detail_screen._strip_path, img_path)
        self.assertFalse(detail_screen.btn_delete.disabled)

    def test_19_delete_confirmation_popup_confirm_with_multiple_images(self):
        """19. Confirming delete removes only the selected strip and safely advances index."""
        timestamps = [
            '2026-10-04_18-00-00_003',
            '2026-10-04_17-00-00_004',
            '2026-10-04_16-00-00_005',
        ]
        for ts in timestamps:
            create_dummy_image(os.path.join(self.app.gallery_strips_directory, f'{ts}.jpg'), 200, 600)
            create_dummy_image(os.path.join(self.app.gallery_small_strips_directory, f'{ts}_small.jpg'), 100, 300)
            create_dummy_image(os.path.join(self.app.gallery_photos_directory, f'{ts}_01.jpg'), 400, 300)

        detail_screen = GalleryDetailScreen(self.app)
        # Enter on middle strip (index 1)
        detail_screen.on_entry({'session_id': timestamps[1]})
        self.assertEqual(detail_screen._current_index, 1)

        middle_strip = os.path.join(self.app.gallery_strips_directory, f'{timestamps[1]}.jpg')

        detail_screen.on_delete_strip(None)
        self.assertIsNotNone(detail_screen.delete_popup)
        detail_screen.delete_popup._on_confirm(None)

        # Confirm middle strip deleted
        self.assertFalse(os.path.exists(middle_strip))
        # Other strips still exist
        self.assertTrue(os.path.exists(os.path.join(self.app.gallery_strips_directory, f'{timestamps[0]}.jpg')))
        self.assertTrue(os.path.exists(os.path.join(self.app.gallery_strips_directory, f'{timestamps[2]}.jpg')))
        # Related photo in photos directory was not deleted
        self.assertTrue(os.path.exists(os.path.join(self.app.gallery_photos_directory, f'{timestamps[1]}_01.jpg')))

        # Safely selected the remaining strip
        self.assertEqual(len(detail_screen._strips), 2)
        self.assertEqual(detail_screen._current_index, 1)
        self.assertEqual(detail_screen._strip_path, os.path.join(self.app.gallery_strips_directory, f'{timestamps[2]}.jpg'))

    def test_20_delete_last_remaining_image_transitions_to_gallery(self):
        """20. Deleting the last photo transitions back to GalleryScreen empty state."""
        ts = '2026-10-04_19-00-00_006'
        img_path = os.path.join(self.app.gallery_strips_directory, f'{ts}.jpg')
        create_dummy_image(img_path)

        detail_screen = GalleryDetailScreen(self.app)
        detail_screen.on_entry({'session_id': ts})

        self.app.transition_to = MagicMock()

        detail_screen.on_delete_strip(None)
        detail_screen.delete_popup._on_confirm(None)

        self.assertFalse(os.path.exists(img_path))
        self.assertEqual(len(detail_screen._strips), 0)
        self.app.transition_to.assert_called_with(ScreenMgr.GALLERY)

    def test_21_delete_error_handling(self):
        """21. When deletion fails, error popup appears and dismisses without crash."""
        ts = '2026-10-04_20-00-00_007'
        img_path = os.path.join(self.app.gallery_strips_directory, f'{ts}.jpg')
        create_dummy_image(img_path)

        detail_screen = GalleryDetailScreen(self.app)
        detail_screen.on_entry({'session_id': ts})

        with patch.object(self.app, 'delete_gallery_strip', side_effect=OSError("Read-only filesystem")):
            detail_screen.on_delete_strip(None)
            detail_screen.delete_popup._on_confirm(None)

            self.assertIsNotNone(detail_screen.error_popup)
            self.assertIsInstance(detail_screen.error_popup, DeleteErrorPopup)

            # Dismiss error popup
            detail_screen.error_popup._on_close(None)
            self.assertIsNone(detail_screen.error_popup)
            # File still present and selected
            self.assertTrue(os.path.exists(img_path))
            self.assertEqual(detail_screen._strip_path, img_path)

    def test_22_delete_gallery_strip_security_and_validation(self):
        """22. PhotoboothApp.delete_gallery_strip validates paths and rejects invalid/traversal paths."""
        # 1. Empty/None path
        with self.assertRaises(ValueError):
            self.app.delete_gallery_strip(None)
        with self.assertRaises(ValueError):
            self.app.delete_gallery_strip("")

        # 2. Path outside gallery strips directory
        outside_file = os.path.join(self.temp_dir.name, 'outside.jpg')
        create_dummy_image(outside_file)
        with self.assertRaises(ValueError):
            self.app.delete_gallery_strip(outside_file)

        # 3. Path traversal attack
        traversal = os.path.join(self.app.gallery_strips_directory, '..', '..', 'outside.jpg')
        with self.assertRaises(ValueError):
            self.app.delete_gallery_strip(traversal)

        # 4. Trying to delete directory itself
        with self.assertRaises(ValueError):
            self.app.delete_gallery_strip(self.app.gallery_strips_directory)

        # 5. Non-existent file
        non_existent = os.path.join(self.app.gallery_strips_directory, 'ghost.jpg')
        with self.assertRaises(FileNotFoundError):
            self.app.delete_gallery_strip(non_existent)

        # 6. Invalid extension
        invalid_ext = os.path.join(self.app.gallery_strips_directory, 'test.txt')
        with open(invalid_ext, 'w') as f:
            f.write('not an image')
        with self.assertRaises(ValueError):
            self.app.delete_gallery_strip(invalid_ext)

        # 7. Valid strip deletion
        valid_strip = os.path.join(self.app.gallery_strips_directory, 'valid.jpg')
        create_dummy_image(valid_strip)
        self.assertTrue(os.path.exists(valid_strip))
        result = self.app.delete_gallery_strip(valid_strip)
        self.assertTrue(result)
        self.assertFalse(os.path.exists(valid_strip))


if __name__ == '__main__':
    unittest.main()
