"""English source messages with external UTF-8 translation catalogs."""
import json
from pathlib import Path
import re
from string import Formatter

_language = "en"
_catalog = {}
_patterns = None
LANGUAGES = (("en", "English"), ("cs", "Czech"))


def set_language(language):
    global _language, _catalog, _patterns
    _language = language if language in {key for key, _ in LANGUAGES} else "en"
    _catalog = {}
    if _language != "en":
        try:
            value = json.loads((Path(__file__).parent / "locales" / (_language + ".json")).read_text(encoding="utf-8"))
            if isinstance(value, dict):
                _catalog = {key: text for key, text in value.items() if isinstance(key, str) and isinstance(text, str)}
        except (OSError, ValueError):
            pass
    _patterns = None
    # Filename classification is cached, but localized labels must not outlive
    # their language. Filenames and user-supplied labels are never translated.
    import sys
    for module, name in (("filetypes", "kind"), ("filemodel", "display_cell")):
        loaded = sys.modules.get("soovee_commander." + module)
        function = getattr(loaded, name, None)
        if hasattr(function, "cache_clear"):
            function.cache_clear()
    return _language


def current_language():
    return _language


def ui_retranslator():
    """Capture the current catalog before changing languages, preserving fields."""
    catalog = dict(_catalog)
    if _language == 'en':
        catalog = json.loads((Path(__file__).parent / 'locales/cs.json').read_text(encoding='utf-8'))
        catalog = {source: source for source in catalog}
    direct = {old: source for source, old in catalog.items()}
    patterns = []
    for source, old in catalog.items():
        if not re.search(r'\{v\d+\}', old):
            continue
        pieces, fields = [], set()
        try:
            for literal, field, spec, conversion in Formatter().parse(old):
                pieces.append(re.escape(literal))
                if field is not None:
                    if not re.fullmatch(r'v\d+', field):
                        raise ValueError('Unsupported field')
                    pieces.append('(?P=' + field + ')' if field in fields else '(?P<' + field + '>.*?)')
                    fields.add(field)
            patterns.append((re.compile(''.join(pieces), re.DOTALL), source))
        except ValueError:
            continue

    def translate(text):
        if not text:
            return text
        # Shortcuts are presentation suffixes, never part of a source message.
        body, separator, shortcut = text.partition('\t')
        if not separator and text.endswith(')') and '  (' in text:   # macOS menu label "Title  (key)"
            body, separator, shortcut = text.rpartition('  (')
        if body in direct:
            return tr(direct[body]) + separator + shortcut
        for pattern, source in patterns:
            try:
                match = pattern.fullmatch(body)
                if match:
                    return tr(source).format(**match.groupdict()) + separator + shortcut
            except (ValueError, KeyError):
                continue
        if '\n' in text:
            return '\n'.join(translate(line) for line in text.split('\n'))
        for prefix in ('▤  ', '▧  ', '◎  '):
            if text.startswith(prefix):
                return prefix + translate(text[len(prefix):])
        return text
    return translate


def retranslate_widgets(root, translate):
    """Update chrome only: paths, tabs, lists, editors and logs keep their data."""
    from PySide6.QtCore import QObject, QSignalBlocker
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit, QTabWidget, QWidget, QComboBox
    for obj in [root, *root.findChildren(QObject)]:
        if obj.property('userContent') or obj.objectName() == 'crumbButton':
            continue
        if isinstance(obj, QWidget):
            obj.setToolTip(translate(obj.toolTip()))
            obj.setWindowTitle(translate(obj.windowTitle()))
            obj.setAccessibleName(translate(obj.accessibleName()))
        if isinstance(obj, (QLabel, QAbstractButton, QAction)):
            obj.setText(translate(obj.text()))
        if isinstance(obj, QLineEdit):
            obj.setPlaceholderText(translate(obj.placeholderText()))
        if isinstance(obj, QTabWidget):
            for index in range(obj.count()):
                obj.setTabText(index, translate(obj.tabText(index)))
        if isinstance(obj, QComboBox) and obj.property('translatedItems'):
            with QSignalBlocker(obj):
                for index in range(obj.count()):
                    obj.setItemText(index, translate(obj.itemText(index)))


def tr(message):
    if not isinstance(message, str) or _language == "en":
        return message
    direct = _catalog.get(message)
    if direct is not None:
        return direct
    # Core exceptions/progress may arrive as already formatted English strings.
    # Exact full-message patterns preserve their interpolated filenames/paths.
    global _patterns
    if _patterns is None:
        _patterns = []
        for source, target in _catalog.items():
            if not re.search(r"\{v\d+\}", source):
                continue
            pieces, fields = [], []
            try:
                for literal, field, spec, conversion in Formatter().parse(source):
                    pieces.append(re.escape(literal))
                    if field is not None:
                        if not re.fullmatch(r"v\d+", field):
                            raise ValueError("Not a generated message field")
                        pieces.append("(?P<" + field + ">.*?)" if field not in fields else "(?P=" + field + ")")
                        fields.append(field)
                _patterns.append((re.compile("^" + "".join(pieces) + "$", re.DOTALL), target))
            except ValueError:
                continue
    for pattern, target in _patterns:
        match = pattern.fullmatch(message)
        if match:
            try:
                return target.format(**match.groupdict())
            except (KeyError, ValueError):
                return message
    return message


def install_qt_translations(app):
    from PySide6.QtCore import QTranslator
    old = getattr(app, "_stereo_translator", None)
    if old is not None:
        app.removeTranslator(old)
        old.deleteLater()
        app._stereo_translator = None
    if _language == "en":
        return
    class CatalogTranslator(QTranslator):
        def translate(self, context, sourceText, disambiguation=None, n=-1):
            return _catalog.get(sourceText, _catalog.get(sourceText.replace("&", "")))
    translator = CatalogTranslator(app)
    app.installTranslator(translator)
    app._stereo_translator = translator
