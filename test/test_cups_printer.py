import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from libs.config import Config
from libs.cups_utils import (
    CUPS_COMMAND_TIMEOUT,
    detect_printer_features,
    format_choice_label,
    get_available_printers,
    get_printer_features,
    get_printer_options,
    get_validated_cups_options,
    parse_lpoptions_output,
    validate_printer_setting,
)
from libs.web_server import WebServer
from photoboothapp import PhotoboothApp


# Sample real-world CUPS outputs for tests
SAMPLE_LPSTAT_OUTPUT = """printer EPSON-L805-Series is idle.  enabled since Fri 10 Oct 2026 06:40:48 PM -03
printer HP-Deskjet-2540 is idle.  enabled since Wed 01 Oct 2026 12:00:00 PM -03
system default destination: EPSON-L805-Series
"""

SAMPLE_LPOPTIONS_EPSON = """PageSize/Media Size: 100x148mm 4x6 *Letter A4
MediaType/Type: *PLAIN EPREMGLOSS PHOTOGLOSSY EMATTE
PrintQuality/Quality Option: Draft *Standard High
Color/Color: *Color Grayscale
"""

SAMPLE_LPOPTIONS_GENERIC = """PageSize/Media Size: *Letter A4 Legal
Duplex/2-Sided Printing: *None DuplexNoTumble DuplexTumble
Resolution/Resolution: 300dpi *600dpi 1200dpi
"""


def test_format_choice_label():
    assert format_choice_label('quality', 'HIGH') == 'High'
    assert format_choice_label('quality', 'DRAFT') == 'Draft'
    assert format_choice_label('quality', 'NORMAL') == 'Normal'
    assert format_choice_label('media_type', 'PLAIN') == 'Plain Paper'
    assert format_choice_label('media_type', 'PHOTOGLOSSY') == 'Photo Glossy'
    assert format_choice_label('media_type', 'EPREMGLOSS') == 'Premium Glossy'
    assert format_choice_label('media_type', 'CUSTOM_PAPER') == 'Custom Paper'


def test_get_available_printers_success():
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=['lpstat', '-p', '-d'],
            returncode=0,
            stdout=SAMPLE_LPSTAT_OUTPUT,
            stderr='',
        )
        result = get_available_printers()
        assert result['printers'] == ['EPSON-L805-Series', 'HP-Deskjet-2540']
        assert result['default'] == 'EPSON-L805-Series'


def test_parse_lpoptions_output_identifies_defaults():
    parsed = parse_lpoptions_output(SAMPLE_LPOPTIONS_EPSON)

    assert 'PrintQuality' in parsed
    assert parsed['PrintQuality']['default'] == 'Standard'
    assert parsed['PrintQuality']['values'] == ['Draft', 'Standard', 'High']
    assert parsed['PrintQuality']['label'] == 'Quality Option'

    assert 'MediaType' in parsed
    assert parsed['MediaType']['default'] == 'PLAIN'
    assert parsed['MediaType']['values'] == ['PLAIN', 'EPREMGLOSS', 'PHOTOGLOSSY', 'EMATTE']


def test_detect_printer_features_mapping():
    parsed = parse_lpoptions_output(SAMPLE_LPOPTIONS_EPSON)
    features = detect_printer_features(parsed)

    assert features['quality'] is not None
    assert features['quality']['name'] == 'PrintQuality'
    assert features['quality']['default'] == 'Standard'
    choices_dict = dict(features['quality']['choices'])
    assert 'High' in choices_dict
    assert choices_dict['High'] == 'High'

    assert features['media_type'] is not None
    assert features['media_type']['name'] == 'MediaType'
    assert features['media_type']['default'] == 'PLAIN'
    media_dict = dict(features['media_type']['choices'])
    assert 'PHOTOGLOSSY' in media_dict
    assert media_dict['PHOTOGLOSSY'] == 'Photo Glossy'


def test_detect_printer_features_without_quality_or_media():
    parsed = parse_lpoptions_output(SAMPLE_LPOPTIONS_GENERIC)
    features = detect_printer_features(parsed)

    assert features['quality'] is None
    assert features['media_type'] is None


def test_cups_command_errors_and_timeouts():
    # 1. TimeoutExpired
    with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='lpstat', timeout=CUPS_COMMAND_TIMEOUT)):
        assert get_available_printers() == {'printers': [], 'default': None}

    # 2. FileNotFoundError (e.g. cups not installed)
    with patch('subprocess.run', side_effect=FileNotFoundError()):
        assert get_available_printers() == {'printers': [], 'default': None}
        assert get_printer_options('EPSON-L805-Series') == {}

    # 3. Non-zero exit code
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=['lpstat'], returncode=1, stdout='', stderr='Error')
        assert get_available_printers() == {'printers': [], 'default': None}


def test_validate_printer_setting():
    with patch('libs.cups_utils.get_printer_options', return_value=parse_lpoptions_output(SAMPLE_LPOPTIONS_EPSON)):
        # Valid quality
        assert validate_printer_setting('EPSON-L805-Series', 'quality', 'High') == 'High'
        assert validate_printer_setting('EPSON-L805-Series', 'quality', 'Standard') == 'Standard'

        # Invalid quality raises ValueError
        with pytest.raises(ValueError, match="Invalid value 'UltraBest' for quality"):
            validate_printer_setting('EPSON-L805-Series', 'quality', 'UltraBest')

        # Valid media
        assert validate_printer_setting('EPSON-L805-Series', 'media_type', 'PHOTOGLOSSY') == 'PHOTOGLOSSY'

        # Invalid media raises ValueError
        with pytest.raises(ValueError, match="Invalid value 'Cardboard' for media_type"):
            validate_printer_setting('EPSON-L805-Series', 'media_type', 'Cardboard')


def test_get_validated_cups_options():
    with patch('libs.cups_utils.get_printer_options', return_value=parse_lpoptions_output(SAMPLE_LPOPTIONS_EPSON)):
        cups_opts = get_validated_cups_options('EPSON-L805-Series', quality_val='High', media_type_val='PHOTOGLOSSY')
        assert cups_opts == {'PrintQuality': 'High', 'MediaType': 'PHOTOGLOSSY'}

        # With invalid values, options are excluded gracefully
        cups_opts_bad = get_validated_cups_options('EPSON-L805-Series', quality_val='FakeQuality', media_type_val='PHOTOGLOSSY')
        assert cups_opts_bad == {'MediaType': 'PHOTOGLOSSY'}


def test_config_ini_per_printer_persistence_and_fallback(tmp_path):
    config_file = tmp_path / 'config.ini'
    config_file.write_text(
        """[Print]
PRINTER = EPSON-L805-Series
PRINT_QUALITY = High
MEDIA_TYPE = PHOTOGLOSSY
PRINT_QUALITY_EPSON-L805-Series = High
MEDIA_TYPE_EPSON-L805-Series = PHOTOGLOSSY
PRINT_QUALITY_HP-Deskjet-2540 = Draft
MEDIA_TYPE_HP-Deskjet-2540 = PLAIN
""",
        encoding='utf-8',
    )

    with patch('libs.config.CONFIG_PATH', config_file):
        cfg = Config()
        assert cfg.get_printer() == 'EPSON-L805-Series'

        # Specific printer lookups
        assert cfg.get_printer_quality('EPSON-L805-Series') == 'High'
        assert cfg.get_printer_media_type('EPSON-L805-Series') == 'PHOTOGLOSSY'
        assert cfg.get_printer_quality('HP-Deskjet-2540') == 'Draft'
        assert cfg.get_printer_media_type('HP-Deskjet-2540') == 'PLAIN'

        # Fallback for printer without specific key
        assert cfg.get_printer_quality('OtherPrinter') == 'High'
        assert cfg.get_printer_media_type('OtherPrinter') == 'PHOTOGLOSSY'


def _build_full_form_data(server, overrides=None):
    form_data = {}
    for section in server._get_config_form_sections():
        for field in section['fields']:
            if field['control'] == 'checkbox':
                if field['checked']:
                    form_data[field['name']] = 'true'
            else:
                form_data[field['name']] = str(field['value'])
    if overrides:
        form_data.update(overrides)
    return form_data


def test_web_server_collect_config_form_updates_per_printer(tmp_path):
    server = WebServer.__new__(WebServer)
    server.project_root = str(tmp_path)

    base_config = """[Global]
FULLSCREEN = False
SHARE = False
RINGLED = False
ADMIN_PASSWORD = admin
LANGUAGE = en

[Log]
LOG_RETENTION_DAYS = 14
LOG_MAX_FILES = 40

[StartScreen]
BACKGROUND_IMAGE = assets/backgrounds/bg_start.jpeg
TEXT_COLOR = #FFFFFF
SHOW_TITLE = True
TITLE =
SHOW_INSTRUCTIONS = True
INSTRUCTIONS =

[Camera]
CAMERA = auto

[Capture]
COUNTDOWN = 5
CAPTURE_TIMEOUT = 15
PROCESSING_TIMEOUT = 30
CALIBRATION = None
FILTERS = False
BLUR_CAMERA = False
PREVIEW_BLUR_REFRESH_FRAMES = 5
BLUR_IMAGES = False
BLUR_COLLAGE = False

[THUMBNAILS]
ASPECT_RATIO = 16:9
IMAGE_FIT_MODE = contain

[Review]
SLIDE_DURATION = 2.0

[Feedback]
ENABLED = False

[Storage]
DCIM_DIRECTORY = ./DCIM
DISK_MIN_FREE_GB = 2.0
DISK_MAX_USED_PERCENT = 90.0
SAVE_TIMEOUT = 30

[Print]
PRINTER = EPSON-L805-Series
MAX_PRINTS = None
PRINTER_WAIT_TIMEOUT = 5
PRINT_QUALITY_HP-Deskjet-2540 = Draft

[USB]
USB_EXPORT = True
USB_MIN_FREE_GB = 1.0
USB_COPY_TIMEOUT = 300

[DSLR_Liveview]
SHUTTERSPEED =
APERTURE =
FOCUSMODE =
ISO =

[DSLR_Capture]
SHUTTERSPEED =
APERTURE =
FOCUSMODE =
ISO =
"""
    parser = server._load_config_parser(base_config)

    with patch.object(server, '_load_config_parser', return_value=parser), \
         patch('libs.cups_utils.get_printer_options', return_value=parse_lpoptions_output(SAMPLE_LPOPTIONS_EPSON)):
        form_data = _build_full_form_data(
            server,
            {
                'Print__PRINTER': 'EPSON-L805-Series',
                'Print__PRINT_QUALITY': 'High',
                'Print__MEDIA_TYPE': 'PHOTOGLOSSY',
            },
        )
        updates, _ = server._collect_config_form_updates(form_data, parser)
        updated_text = server._apply_config_updates(base_config, updates)

        assert 'PRINT_QUALITY_EPSON-L805-Series = High' in updated_text
        assert 'MEDIA_TYPE_EPSON-L805-Series = PHOTOGLOSSY' in updated_text
        # Preserves previous printer preferences
        assert 'PRINT_QUALITY_HP-Deskjet-2540 = Draft' in updated_text


def test_web_server_rejects_invalid_printer_options(tmp_path):
    server = WebServer.__new__(WebServer)
    server.project_root = str(tmp_path)

    base_config = """[Global]
FULLSCREEN = False
SHARE = False
RINGLED = False
ADMIN_PASSWORD = admin
LANGUAGE = en

[Log]
LOG_RETENTION_DAYS = 14
LOG_MAX_FILES = 40

[StartScreen]
BACKGROUND_IMAGE = assets/backgrounds/bg_start.jpeg
TEXT_COLOR = #FFFFFF
SHOW_TITLE = True
TITLE =
SHOW_INSTRUCTIONS = True
INSTRUCTIONS =

[Camera]
CAMERA = auto

[Capture]
COUNTDOWN = 5
CAPTURE_TIMEOUT = 15
PROCESSING_TIMEOUT = 30
CALIBRATION = None
FILTERS = False
BLUR_CAMERA = False
PREVIEW_BLUR_REFRESH_FRAMES = 5
BLUR_IMAGES = False
BLUR_COLLAGE = False

[THUMBNAILS]
ASPECT_RATIO = 16:9
IMAGE_FIT_MODE = contain

[Review]
SLIDE_DURATION = 2.0

[Feedback]
ENABLED = False

[Storage]
DCIM_DIRECTORY = ./DCIM
DISK_MIN_FREE_GB = 2.0
DISK_MAX_USED_PERCENT = 90.0
SAVE_TIMEOUT = 30

[Print]
PRINTER = EPSON-L805-Series
MAX_PRINTS = None
PRINTER_WAIT_TIMEOUT = 5

[USB]
USB_EXPORT = True
USB_MIN_FREE_GB = 1.0
USB_COPY_TIMEOUT = 300

[DSLR_Liveview]
SHUTTERSPEED =
APERTURE =
FOCUSMODE =
ISO =

[DSLR_Capture]
SHUTTERSPEED =
APERTURE =
FOCUSMODE =
ISO =
"""
    parser = server._load_config_parser(base_config)

    with patch.object(server, '_load_config_parser', return_value=parser), \
         patch('libs.cups_utils.get_printer_options', return_value=parse_lpoptions_output(SAMPLE_LPOPTIONS_EPSON)):
        form_data = _build_full_form_data(
            server,
            {
                'Print__PRINTER': 'EPSON-L805-Series',
                'Print__PRINT_QUALITY': 'InvalidQualityValue',
                'Print__MEDIA_TYPE': 'PHOTOGLOSSY',
            },
        )
        with pytest.raises(ValueError, match="Invalid value 'InvalidQualityValue' for quality"):
            server._collect_config_form_updates(form_data, parser)


def test_trigger_print_and_reprint_include_cups_options(tmp_path):
    app = PhotoboothApp.__new__(PhotoboothApp)
    app.tmp_directory = str(tmp_path)
    app._print_state_uncertain = False
    app.PRINTER = 'EPSON-L805-Series'

    # Mock devices
    fake_device = MagicMock()
    fake_device._printer = MagicMock()
    fake_device._printer._name = 'EPSON-L805-Series'
    fake_device.has_printer.return_value = True
    fake_device.print.return_value = 'task-456'
    app.devices = fake_device

    # Mock stats store
    app.stats_store = MagicMock()
    app.stats_store.can_print.return_value = True

    # Mock print formats
    fake_format = MagicMock()
    fake_format.get_print_params.return_value = {'fit-to-page': 'True'}
    fake_format.uses_print_version.return_value = False
    app.print_formats = [fake_format]

    # Mock config
    app.config = MagicMock()
    app.config.get_printer_quality.return_value = 'High'
    app.config.get_printer_media_type.return_value = 'PHOTOGLOSSY'

    # Mock collages
    collage_path = tmp_path / 'collage.jpg'
    collage_path.write_text('fake_image')
    app.get_collage = MagicMock(return_value=str(collage_path))
    app._log_disk_space = MagicMock()

    with patch('libs.cups_utils.get_printer_options', return_value=parse_lpoptions_output(SAMPLE_LPOPTIONS_EPSON)):
        # 1. trigger_print
        app.trigger_print(copies=1, format=0)
        assert fake_device.print.called
        call_args = fake_device.print.call_args[0]
        sent_options = call_args[1]
        assert sent_options['copies'] == '1'
        assert sent_options['PrintQuality'] == 'High'
        assert sent_options['MediaType'] == 'PHOTOGLOSSY'
        assert sent_options['fit-to-page'] == 'True'

        # 2. trigger_reprint
        fake_device.print.reset_mock()
        app.trigger_reprint(str(collage_path), copies=2)
        assert fake_device.print.called
        reprint_args = fake_device.print.call_args[0]
        reprint_options = reprint_args[1]
        assert reprint_options['copies'] == '2'
        assert reprint_options['PrintQuality'] == 'High'
        assert reprint_options['MediaType'] == 'PHOTOGLOSSY'


def test_web_server_printer_options_api_endpoint(tmp_path):
    server = WebServer(save_directory=str(tmp_path), admin_password='admin')
    server.project_root = str(tmp_path)
    client = server.app.test_client()

    # 1. Unauthenticated request redirects
    res = client.get('/api/admin/printer-options?printer=EPSON-L805-Series')
    assert res.status_code in (302, 303, 401)

    # 2. Authenticated request
    with client.session_transaction() as sess:
        sess['is_admin_authenticated'] = True

    with patch('libs.cups_utils.get_printer_options', return_value=parse_lpoptions_output(SAMPLE_LPOPTIONS_EPSON)):
        res = client.get('/api/admin/printer-options?printer=EPSON-L805-Series')
        assert res.status_code == 200
        data = res.get_json()
        assert data['printer'] == 'EPSON-L805-Series'
        assert data['quality'] is not None
        assert data['quality']['name'] == 'PrintQuality'
        assert data['media_type'] is not None
        assert data['media_type']['name'] == 'MediaType'

    # 3. Request with printer=None
    res_none = client.get('/api/admin/printer-options?printer=None')
    assert res_none.status_code == 200
    data_none = res_none.get_json()
    assert data_none['printer'] is None
    assert data_none['quality'] is None
    assert data_none['media_type'] is None


def test_kivy_runtime_configparser_does_not_break_print(tmp_path):
    from kivy.config import ConfigParser as KivyConfigParser

    app = PhotoboothApp.__new__(PhotoboothApp)
    app.tmp_directory = str(tmp_path)
    app._print_state_uncertain = False
    app.PRINTER = 'auto'

    # Reproduce the exact Kivy runtime lifecycle: Kivy overrides self.config with KivyConfigParser
    app.config = KivyConfigParser()

    # Our project configuration is preserved in self.app_config
    mock_app_config = MagicMock()
    mock_app_config.get_printer.return_value = 'EPSON-L805-Series'
    mock_app_config.get_printer_quality.return_value = 'High'
    mock_app_config.get_printer_media_type.return_value = 'PHOTOGLOSSY'
    app.app_config = mock_app_config

    fake_device = MagicMock()
    fake_device._printer = MagicMock()
    fake_device._printer._name = 'EPSON-L805-Series'
    fake_device.has_printer.return_value = True
    fake_device.print.return_value = 'task-789'
    app.devices = fake_device

    app.stats_store = MagicMock()
    app.stats_store.can_print.return_value = True

    # Template with multiple original options (PageSize, print-scaling, fit-to-page)
    fake_format = MagicMock()
    fake_format.get_print_params.return_value = {
        'PageSize': '4x6in',
        'print-scaling': 'fit',
        'fit-to-page': 'True',
    }
    fake_format.uses_print_version.return_value = False
    app.print_formats = [fake_format]

    collage_path = tmp_path / 'collage.jpg'
    collage_path.write_text('fake_image')
    app.get_collage = MagicMock(return_value=str(collage_path))
    app._log_disk_space = MagicMock()

    with patch('libs.cups_utils.get_printer_options', return_value=parse_lpoptions_output(SAMPLE_LPOPTIONS_EPSON)):
        # 1. get_active_printer_options must succeed without raising AttributeError on KivyConfigParser
        active_opts = app.get_active_printer_options()
        assert active_opts == {'PrintQuality': 'High', 'MediaType': 'PHOTOGLOSSY'}

        # 2. trigger_print must preserve original template options and append quality, media_type, copies
        app.trigger_print(copies=1, format=0)
        assert fake_device.print.called
        sent_options = fake_device.print.call_args[0][1]
        assert sent_options['PageSize'] == '4x6in'
        assert sent_options['print-scaling'] == 'fit'
        assert sent_options['fit-to-page'] == 'True'
        assert sent_options['copies'] == '1'
        assert sent_options['PrintQuality'] == 'High'
        assert sent_options['MediaType'] == 'PHOTOGLOSSY'

        # 3. trigger_reprint must also preserve original template options and append quality, media_type, copies
        fake_device.print.reset_mock()
        app.trigger_reprint(str(collage_path), copies=2)
        assert fake_device.print.called
        reprint_options = fake_device.print.call_args[0][1]
        assert reprint_options['PageSize'] == '4x6in'
        assert reprint_options['print-scaling'] == 'fit'
        assert reprint_options['fit-to-page'] == 'True'
        assert reprint_options['copies'] == '2'
        assert reprint_options['PrintQuality'] == 'High'
        assert reprint_options['MediaType'] == 'PHOTOGLOSSY'
