import os
import re
import subprocess
from kivy.logger import Logger

# Standard timeout in seconds for CUPS subprocess calls to prevent blocking
CUPS_COMMAND_TIMEOUT = 5

# Common driver choice label mappings
KNOWN_MEDIA_TYPE_LABELS = {
    'PLAIN': 'Plain Paper',
    'EULTRAGLOSSY': 'Ultra Glossy',
    'EPREMGLOSS': 'Premium Glossy',
    'EPSGLOS': 'Glossy',
    'PHOTOGLOSSY': 'Photo Glossy',
    'EMATTE': 'Matte',
    'EPQIJ': 'Photo Quality Ink Jet',
    'PHOTOSTICKERS': 'Photo Stickers',
    'CD_DVD': 'CD / DVD',
    'CD_DVD_PREVIEW': 'CD / DVD (Preview)',
    'ENVELOPE': 'Envelope',
    'CARDSTOCK': 'Cardstock',
    'TRANSPARENCY': 'Transparency',
    'RECYCLED': 'Recycled',
    'LABELS': 'Labels',
    'GLOSSY': 'Glossy',
    'MATTE': 'Matte',
}

KNOWN_QUALITY_LABELS = {
    'DRAFT': 'Draft',
    'FASTDRAFT': 'Fast Draft',
    'NORMAL': 'Normal',
    'STANDARD': 'Standard',
    'HIGH': 'High',
    'BEST': 'Best',
    'PHOTO': 'Photo',
    'MAX': 'Maximum',
}


def format_choice_label(option_type, choice_value):
    """Generate a clean, user-friendly label for a CUPS option choice value."""
    if not choice_value:
        return ''
    clean_val = str(choice_value).strip()
    upper_val = clean_val.upper()

    if option_type == 'quality' and upper_val in KNOWN_QUALITY_LABELS:
        return KNOWN_QUALITY_LABELS[upper_val]
    if option_type == 'media_type' and upper_val in KNOWN_MEDIA_TYPE_LABELS:
        return KNOWN_MEDIA_TYPE_LABELS[upper_val]

    # General fallback: replace underscores/dashes and format nicely
    formatted = clean_val.replace('_', ' ').replace('-', ' ')
    if formatted.isupper():
        return formatted.title()
    return formatted


def get_available_printers():
    """
    Query available CUPS printers and system default destination using `lpstat -p -d`.
    Returns dict: {'printers': [list of names], 'default': default_printer_name or None}
    """
    env = {**os.environ, 'LC_ALL': 'C'}
    try:
        proc = subprocess.run(
            ['lpstat', '-p', '-d'],
            env=env,
            capture_output=True,
            text=True,
            timeout=CUPS_COMMAND_TIMEOUT,
        )
    except FileNotFoundError:
        Logger.warning('cups_utils: lpstat command not found')
        return {'printers': [], 'default': None}
    except subprocess.TimeoutExpired:
        Logger.warning('cups_utils: lpstat -p -d timed out after %ss', CUPS_COMMAND_TIMEOUT)
        return {'printers': [], 'default': None}
    except Exception as exc:
        Logger.warning('cups_utils: error executing lpstat: %s', exc)
        return {'printers': [], 'default': None}

    if proc.returncode != 0 and not proc.stdout:
        Logger.warning('cups_utils: lpstat failed with exit code %s: %s', proc.returncode, proc.stderr.strip())
        return {'printers': [], 'default': None}

    printers = []
    default_printer = None

    # Parse stdout
    # Typical lines:
    # printer EPSON-L805-Series is idle. ...
    # printer L805-Series disabled since ...
    # system default destination: EPSON-L805-Series
    printer_re = re.compile(r'^\s*(?:printer|la impresora)\s+([^\s:]+)', re.IGNORECASE)
    default_re = re.compile(r'^\s*(?:system default destination|destino predeterminado(?: del sistema)?):\s*([^\s]+)', re.IGNORECASE)

    for line in proc.stdout.splitlines():
        p_match = printer_re.match(line)
        if p_match:
            p_name = p_match.group(1).strip()
            if p_name and p_name not in printers:
                printers.append(p_name)
            continue
        d_match = default_re.match(line)
        if d_match:
            default_printer = d_match.group(1).strip()

    return {'printers': printers, 'default': default_printer}


def parse_lpoptions_output(output_text):
    """
    Parse the standard output of `lpoptions -p <name> -l`.
    Each line follows: OptionName[/OptionLabel]: val1 *val2 val3 ...
    Returns dict: {option_name: {'name': str, 'label': str, 'choices': [list of dicts], 'default': str or None}}
    """
    options = {}
    if not output_text:
        return options

    for line in output_text.splitlines():
        line = line.strip()
        if not line or ':' not in line:
            continue

        header, choices_part = line.split(':', 1)
        header = header.strip()
        choices_part = choices_part.strip()

        if '/' in header:
            opt_name, opt_label = header.split('/', 1)
            opt_name = opt_name.strip()
            opt_label = opt_label.strip()
        else:
            opt_name = header
            opt_label = header

        raw_choices = choices_part.split()
        choices_list = []
        default_val = None

        for item in raw_choices:
            if item.startswith('*'):
                val = item[1:]
                is_default = True
                default_val = val
            else:
                val = item
                is_default = False

            choices_list.append({
                'value': val,
                'is_default': is_default,
            })

        options[opt_name] = {
            'name': opt_name,
            'label': opt_label,
            'choices': choices_list,
            'default': default_val or (choices_list[0]['value'] if choices_list else None),
            'values': [c['value'] for c in choices_list],
        }

    return options


def get_printer_options(printer_name):
    """
    Execute `lpoptions -p <printer_name> -l` and parse options.
    Returns dict of options or empty dict on error.
    """
    if not printer_name or printer_name.lower() in ('none', 'auto'):
        return {}

    env = {**os.environ, 'LC_ALL': 'C'}
    try:
        proc = subprocess.run(
            ['lpoptions', '-p', printer_name, '-l'],
            env=env,
            capture_output=True,
            text=True,
            timeout=CUPS_COMMAND_TIMEOUT,
        )
    except FileNotFoundError:
        Logger.warning('cups_utils: lpoptions command not found')
        return {}
    except subprocess.TimeoutExpired:
        Logger.warning('cups_utils: lpoptions -p %s -l timed out after %ss', printer_name, CUPS_COMMAND_TIMEOUT)
        return {}
    except Exception as exc:
        Logger.warning('cups_utils: error executing lpoptions for %s: %s', printer_name, exc)
        return {}

    if proc.returncode != 0:
        Logger.warning('cups_utils: lpoptions failed for %s (exit %s): %s', printer_name, proc.returncode, proc.stderr.strip())
        return {}

    return parse_lpoptions_output(proc.stdout)


def detect_printer_features(options_dict):
    """
    Identify Print Quality and Paper Type (Media Type) options from parsed options dictionary.
    Returns dict:
    {
        'quality': {
            'name': 'PrintQuality', # real CUPS option name
            'label': 'Quality Option',
            'default': 'Standard',
            'choices': [('Draft', 'Draft'), ('Standard', 'Standard'), ...]
        } or None,
        'media_type': {
            'name': 'MediaType', # real CUPS option name
            'label': 'Media Type',
            'default': 'PLAIN',
            'choices': [('PLAIN', 'Plain Paper'), ('PHOTOGLOSSY', 'Photo Glossy'), ...]
        } or None
    }
    """
    quality_candidate = None
    media_candidate = None

    # Priority lists for exact option name matching (case-insensitive)
    QUALITY_NAMES = ['printquality', 'quality', 'outputmode', 'print-quality', 'hpcolormode']
    MEDIA_NAMES = ['mediatype', 'media-type', 'media_type', 'papertype', 'paper-type']

    for name, opt in options_dict.items():
        name_lower = name.lower()
        label_lower = opt.get('label', '').lower()

        # Check Quality
        if not quality_candidate:
            if name_lower in QUALITY_NAMES:
                quality_candidate = opt
            elif any(q in name_lower for q in ('printquality', 'quality')) and 'color' not in name_lower:
                quality_candidate = opt
            elif 'quality' in label_lower or 'calidad' in label_lower:
                quality_candidate = opt

        # Check Media Type (ensure we don't accidentally pick PageSize or InputSlot)
        if not media_candidate:
            if 'pagesize' in name_lower or 'pagesize' in label_lower or 'inputslot' in name_lower:
                continue
            if name_lower in MEDIA_NAMES:
                media_candidate = opt
            elif any(m in name_lower for m in ('mediatype', 'papertype')):
                media_candidate = opt
            elif any(m in label_lower for m in ('media type', 'paper type', 'tipo de papel')):
                media_candidate = opt

    result = {'quality': None, 'media_type': None}

    if quality_candidate and quality_candidate.get('choices'):
        formatted_choices = [
            (c['value'], format_choice_label('quality', c['value']))
            for c in quality_candidate['choices']
        ]
        result['quality'] = {
            'name': quality_candidate['name'],
            'label': quality_candidate.get('label', 'Quality'),
            'default': quality_candidate.get('default'),
            'choices': formatted_choices,
            'raw_values': quality_candidate.get('values', []),
        }

    if media_candidate and media_candidate.get('choices'):
        formatted_choices = [
            (c['value'], format_choice_label('media_type', c['value']))
            for c in media_candidate['choices']
        ]
        result['media_type'] = {
            'name': media_candidate['name'],
            'label': media_candidate.get('label', 'Paper Type'),
            'default': media_candidate.get('default'),
            'choices': formatted_choices,
            'raw_values': media_candidate.get('values', []),
        }

    return result


def get_printer_features(printer_name):
    """Get detected features (quality, media_type) for a printer name."""
    options = get_printer_options(printer_name)
    return detect_printer_features(options)


def validate_printer_setting(printer_name, option_type, value):
    """
    Validate that value is accepted for option_type ('quality' or 'media_type') on printer_name.
    Returns normalized value if valid, or raises ValueError.
    """
    if not value:
        return None
    features = get_printer_features(printer_name)
    feature = features.get(option_type)
    if not feature:
        # Printer does not support this option
        raise ValueError(f"Printer '{printer_name}' does not support option '{option_type}'.")

    raw_values = feature.get('raw_values', [])
    if value not in raw_values:
        raise ValueError(
            f"Invalid value '{value}' for {option_type} on printer '{printer_name}'. Allowed: {', '.join(raw_values)}"
        )
    return value


def get_validated_cups_options(printer_name, quality_val=None, media_type_val=None):
    """
    Return dictionary of real CUPS options to pass to print commands,
    e.g. {'PrintQuality': 'High', 'MediaType': 'PHOTOGLOSSY'}.
    Only includes options that are valid for the given printer.
    """
    cups_options = {}
    if not printer_name or printer_name.lower() in ('none', 'auto'):
        return cups_options

    try:
        features = get_printer_features(printer_name)
    except Exception as exc:
        Logger.warning('cups_utils: failed to query printer features for %s: %s', printer_name, exc)
        return cups_options

    if quality_val and features.get('quality'):
        q_info = features['quality']
        if quality_val in q_info.get('raw_values', []):
            cups_options[q_info['name']] = str(quality_val)
        else:
            Logger.warning("cups_utils: configured quality '%s' not supported by %s (allowed: %s)",
                           quality_val, printer_name, q_info.get('raw_values'))

    if media_type_val and features.get('media_type'):
        m_info = features['media_type']
        if media_type_val in m_info.get('raw_values', []):
            cups_options[m_info['name']] = str(media_type_val)
        else:
            Logger.warning("cups_utils: configured media type '%s' not supported by %s (allowed: %s)",
                           media_type_val, printer_name, m_info.get('raw_values'))

    return cups_options
