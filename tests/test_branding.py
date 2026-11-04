"""Acceptance checks for readable branding and native icon transparency."""
from pathlib import Path

from PySide6.QtGui import QColor, QImage

from soovee_commander.themes import THEMES


def luminance(hex_color):
    color = QColor(hex_color)
    channels = [color.redF(), color.greenF(), color.blueF()]
    linear = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4 for channel in channels]
    return sum(channel * weight for channel, weight in zip(linear, [.2126, .7152, .0722]))


def contrast(a, b):
    bright, dark = sorted([luminance(a), luminance(b)], reverse=True)
    return (bright + .05) / (dark + .05)


def test_soovee_text_has_readable_contrast_on_its_actual_surfaces():
    theme = THEMES['soovee']
    for background in ['bg', 'surface', 'alternate', 'header', 'button', 'input']:
        assert contrast(theme['text'], theme[background]) >= 4.5, background
        assert contrast(theme['muted'], theme[background]) >= 4.5, background
    assert contrast(theme['selected_text'], theme['selected']) >= 4.5
    assert contrast(theme['primary_text'], theme['accent']) >= 4.5


def test_native_icon_corners_are_transparent_and_tile_is_opaque():
    root = Path(__file__).resolve().parents[1]
    image = QImage(str(root / 'src/soovee_commander/assets/soovee-commander-icon.png'))
    assert not image.isNull() and image.hasAlphaChannel()
    assert image.width() == image.height()
    for x, y in [(0, 0), (image.width() - 1, 0), (0, image.height() - 1), (image.width() - 1, image.height() - 1)]:
        assert image.pixelColor(x, y).alpha() <= 2  # A sub-percent residual shadow is invisible; an opaque square is not.
    assert image.pixelColor(image.width() // 2, image.height() // 2).alpha() >= 250
    thumbnail = image.scaled(256, 256)
    opaque = [(x, y) for y in range(256) for x in range(256) if thumbnail.pixelColor(x, y).alpha() > 128]
    width = max(x for x, y in opaque) - min(x for x, y in opaque) + 1
    height = max(y for x, y in opaque) - min(y for x, y in opaque) + 1
    assert .80 <= width / 256 <= .86
    assert .80 <= height / 256 <= .86


def test_canonical_and_legacy_module_commands_report_the_same_version():
    import os
    import subprocess
    import sys
    from soovee_commander import __version__
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / 'src'))
    for module in ('soovee_commander', 'stereo_commander'):
        result = subprocess.run([sys.executable, '-m', module, '--version'], env=environment,
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == __version__
