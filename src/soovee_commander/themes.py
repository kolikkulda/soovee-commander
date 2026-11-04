"""Complete, contrasting Qt palettes; the same controls work in every theme."""
from PySide6.QtGui import QColor, QPalette
from pathlib import Path

THEMES = {
    "soovee_light": dict(name='Soovee · daylight', bg='#f1f4f9', surface='#ffffff', alternate='#f7f9fd', text='#172b46',
                        muted='#53657c', border='#bccadc', accent='#245ed6', selected='#245ed6', selected_text='#ffffff',
                        header='#eaf0f8', title='#e3ecfc', hover='#e9f0fd', button='#ffffff', input='#ffffff',
                        sidebar='#eaf0f8', archive='#8b4b00', disabled='#74859c', active_text='#172b46', primary_text='#ffffff'),
    "soovee": dict(name='Soovee · midnight', bg="#0a1122", surface="#111d34", alternate="#15243d", text="#edf5ff",
                   muted="#a8b9d3", border="#425c80", accent="#1adce6", selected="#34458f", selected_text="#ffffff",
                   header="#1c2d4b", title="#15345a", hover="#223c5c", button="#1b2e4c", input="#0c172b",
                   sidebar="#101d35", archive="#ffcf80", disabled="#8095b2", active_text="#ffffff", primary_text="#061522"),
    "light": dict(name='Commander · light', bg="#e8edf3", surface="#ffffff", alternate="#f2f5f9", text="#192c42",
                  muted="#50647a", border="#899bb0", accent="#205cb0", selected="#215eaf", selected_text="#ffffff",
                  header="#dbe5f1", title="#1e4f89", hover="#e1ecfb", button="#f7f9fc", input="#ffffff",
                  sidebar="#dce5ef", archive="#8c4d00", disabled="#718095", active_text="#ffffff", primary_text="#ffffff"),
    "slate": dict(name='Salamander · slate', bg="#aebdcd", surface="#e5ecf3", alternate="#d8e2ed", text="#172b40",
                  muted="#3d536c", border="#647d99", accent="#254f7a", selected="#315f8d", selected_text="#ffffff",
                  header="#b9cadc", title="#2c4d70", hover="#cfdfef", button="#dbe5ef", input="#f4f7fb",
                  sidebar="#97aec5", archive="#824800", disabled="#52687e", active_text="#ffffff", primary_text="#ffffff"),
    "dark": dict(name='Commander · dark', bg="#111923", surface="#1c2938", alternate="#233346", text="#edf2f9",
                 muted="#b0bfd2", border="#657c96", accent="#68aaff", selected="#285e9b", selected_text="#ffffff",
                 header="#30445c", title="#245180", hover="#344e6d", button="#2c3e54", input="#122130",
                 sidebar="#1e3044", archive="#ffd18b", disabled="#90a2b9", active_text="#ffffff", primary_text="#102136"),
}


def stylesheet(key="light"):
    t = THEMES.get(key, THEMES["light"])
    css = """
QWidget { background: $bg; color: $text; font-family: 'Segoe UI', 'Arial'; font-size: 12px; }
QMainWindow { background: $bg; }
QLabel { background: transparent; }
QLabel#brand { font-size: 18px; font-weight: 700; letter-spacing: 1px; }
QLabel#subtitle, QLabel#muted { color: $muted; font-size: 11px; }
QLabel#dialogHeading { font-size: 19px; font-weight: 700; padding: 4px 0px; }
QGroupBox#toolCard { background: $surface; border: 1px solid $border; border-radius: 6px; margin-top: 10px; padding: 12px; padding-top: 18px; }
QGroupBox#toolCard::title { subcontrol-origin: margin; left: 12px; padding: 0px 5px; color: $text; font-weight: 600; }
QFrame#mainToolbar { background: transparent; border: none; }
QToolButton#toolbarButton { background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 4px; }
QToolButton#toolbarButton:hover { background: $hover; border-color: $border; }
QToolButton#toolbarButton:pressed, QToolButton#toolbarButton:checked { background: $header; border-color: $accent; }
QToolButton#toolbarButton::menu-indicator { width: 0px; }
QToolButton#connectServerButton { background: $accent; color: $primary_text; border: 1px solid $accent; border-radius: 5px; padding: 5px 10px; }
QToolButton#connectServerButton:hover { background: $accent; border-color: $text; }
QSplitter#panelSplitter::handle { background: $header; border-left: 1px solid $border; border-right: 1px solid $border; }
QSplitter#panelSplitter::handle:hover { background: $accent; }
QFrame#panel { background: $surface; border: 2px solid $border; border-radius: 3px; }
QFrame#panel[active="true"] { border: 2px solid $accent; }
QFrame#panelHeading { background: $header; border: none; }
QFrame#panel[active="true"] QFrame#panelHeading { background: $title; }
QLabel#panelTitle { color: $text; font-weight: 700; font-size: 11px; letter-spacing: 1px; }
QFrame#panel[active="true"] QLabel#panelTitle { color: $active_text; }
QLabel#badge { color: $muted; font-size: 10px; }
QFrame#diskSummary { background: transparent; border: none; }
QLabel#diskFree { color: $text; font-weight: 700; font-size: 11px; }
QLabel#diskDetails { color: $muted; font-size: 10px; }
QFrame#panel[active="true"] QLabel#diskFree, QFrame#panel[active="true"] QLabel#diskDetails { color: $active_text; }
QFrame#panel[active="true"] QLabel#badge { color: $active_text; }
QFrame#tabStrip { background: $header; border: none; border-bottom: 1px solid $border; }
QTabBar { background: transparent; }
QTabBar::tab { background: $header; color: $muted; border: 1px solid $border; border-bottom: none; padding: 6px 10px; min-width: 55px; max-width: 175px; margin-right: 3px; border-top-left-radius: 3px; border-top-right-radius: 3px; }
QTabBar::tab:selected { background: $surface; color: $text; border-top: 3px solid $accent; padding-top: 4px; font-weight: 700; }
QTabBar::tab:hover:!selected { background: $hover; }
QTabBar QToolButton { background: $button; border: 1px solid $border; }
QTabBar QToolButton#tabClose { background: transparent; color: $muted; border: none; padding: 0px; margin: 0px; min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px; border-radius: 4px; }
QTabBar QToolButton#tabClose:hover { background: $hover; color: $text; }
QTabBar QToolButton#tabClose:pressed { background: $header; }
QFrame#pathStrip, QFrame#breadcrumbs { background: $surface; border: none; }
QLineEdit { background: $input; border: 1px solid $border; border-radius: 3px; padding: 7px; color: $text; selection-background-color: $selected; selection-color: $selected_text; }
QLineEdit:focus { border: 1px solid $accent; }
QLineEdit#pathEdit { font-family: 'Menlo', 'Consolas', monospace; font-size: 11px; padding: 6px; }
QLineEdit#filterEdit { background: $alternate; border: none; border-top: 1px solid $border; border-bottom: 1px solid $border; border-radius: 0; padding: 5px 8px; font-size: 11px; }
QPushButton { background: $button; border: 1px solid $border; padding: 6px 10px; border-radius: 3px; }
QPushButton:hover { background: $hover; border-color: $accent; }
QPushButton:pressed, QPushButton:checked { background: $selected; color: $selected_text; }
QPushButton:disabled { color: $disabled; border-color: $border; }
QPushButton#primary { background: $accent; color: $primary_text; font-weight: 700; border-color: $accent; }
QPushButton#danger { background: #c93a3a; color: #ffffff; font-weight: 700; border-color: #c93a3a; }
QPushButton#danger:hover { background: #b02f2f; border-color: $text; }
QLabel#dialogSubtitle { color: $muted; font-size: 12px; }
QLabel#dialogIcon { background: $surface; border: 1px solid $border; border-radius: 10px; }
QFrame#dialogSeparator { color: $border; background: $border; max-height: 1px; border: none; }
QListWidget#dialogItems { background: $surface; border: 1px solid $border; border-radius: 6px; padding: 2px; }
QPushButton#pathButton { background: $button; padding: 5px 2px; }
QPushButton#compactButton { background: $button; padding: 3px 6px; font-size: 10px; }
QPushButton#driveButton { background: $button; padding: 3px 8px; font-size: 11px; font-weight: 600; text-align: left; }
QPushButton#crumbButton { background: transparent; color: $muted; border: none; padding: 3px 7px; font-size: 11px; }
QPushButton#crumbButton:hover { background: $hover; color: $text; }
QTreeView { background: $surface; alternate-background-color: $alternate; border: none; outline: none; }
QTreeView::item { height: 24px; padding: 1px 5px; border-bottom: 1px solid transparent; }
QTreeView::item:selected { background: $selected; color: $selected_text; }
QTreeView::item:hover:!selected { background: $hover; }
QTreeView::item:focus { border: 1px dotted $accent; }
QListView#fileTiles { background: $surface; border: none; }
QListWidget#settingsCategories { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 6px; outline: 0; }
QListWidget#settingsCategories::item { color: $text; padding: 8px 12px; margin: 1px 0px; border: none; border-radius: 6px; }
QListWidget#settingsCategories::item:selected { background: $selected; color: $selected_text; font-weight: 600; }
QListWidget#settingsCategories::item:hover:!selected { background: $hover; color: $text; }
QListView#fileTiles::item { padding: 6px; border: 1px solid transparent; border-radius: 5px; color: $text; }
QListView#fileTiles::item:selected { background: $selected; color: $selected_text; border-color: $accent; }
QListView#fileTiles::item:hover:!selected { background: $hover; }
QToolButton#viewModeCard { background: $surface; color: $text; border: 1px solid $border; border-radius: 8px; padding: 8px; }
QToolButton#viewModeCard:hover { background: $hover; border-color: $accent; }
QToolButton#viewModeCard:checked { background: $hover; border: 2px solid $accent; }
QHeaderView::section { background: $header; color: $text; border: none; border-right: 1px solid $border; border-bottom: 1px solid $border; padding: 6px 8px; font-size: 11px; font-weight: 600; }
QLabel#panelFooter { color: $text; background: $header; border-top: 1px solid $border; padding: 6px 9px; font-size: 11px; }
QFrame#panelFooterFrame { background: $header; }
QToolButton#columnScrollButton { background: $button; color: $text; border: 1px solid $border; border-radius: 4px; }
QToolButton#columnScrollButton:hover { background: $hover; border-color: $accent; }
QToolButton#columnScrollButton:disabled { color: $disabled; }
QTreeView#frozenName { border-right: 1px solid $border; }
QSplitter::handle { background: $bg; width: 9px; }
QFrame#sidebar { background: $sidebar; border: 1px solid $border; border-radius: 3px; }
QLabel#sectionLabel { color: $muted; font-size: 9px; font-weight: 700; letter-spacing: 1px; padding: 11px 7px 7px; }
QPushButton#navItem { background: transparent; border: none; text-align: left; color: $text; padding: 9px 8px; }
QPushButton#navItem:hover { background: $hover; }
QLabel#sidebarNote { color: $muted; font-size: 10px; padding: 8px; }
QPlainTextEdit { background: $input; color: $text; border: 1px solid $border; border-radius: 3px; font-family: 'Menlo', 'Consolas', monospace; font-size: 12px; selection-background-color: $selected; selection-color: $selected_text; }
QProgressBar { background: $header; border: 1px solid $border; border-radius: 2px; height: 5px; }
QProgressBar::chunk { background: $accent; }
QLabel#dialogHeading { font-size: 17px; font-weight: 600; padding: 8px 0 16px; }
QComboBox { background: $button; color: $text; border: 1px solid $border; border-radius: 3px; padding: 6px 8px; }
QComboBox QAbstractItemView { background: $surface; color: $text; selection-background-color: $selected; selection-color: $selected_text; }
QCheckBox { padding: 4px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid $border; border-radius: 3px; background: $input; }
QCheckBox::indicator:checked { border-color: $accent; background: $accent; image: url("$check_icon"); }
QCheckBox::indicator:hover { border-color: $accent; }
QMenuBar { background: $header; border-bottom: 1px solid $border; }
QMenuBar::item:selected { background: $hover; }
QMenu { background: $surface; color: $text; border: 1px solid $border; padding: 3px; }
QMenu::item { padding: 6px 18px; }
QMenu::item:selected { background: $selected; color: $selected_text; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; }
QScrollBar:vertical { background: $header; width: 11px; margin: 0; border: none; }
QScrollBar::handle:vertical { background: $border; min-height: 30px; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { background: $header; height: 11px; border: none; }
QScrollBar::handle:horizontal { background: $border; min-width: 30px; border-radius: 3px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QStatusBar { background: $header; color: $muted; border-top: 1px solid $border; font-size: 10px; }
"""
    if key == "soovee":
        css += """
QFrame#mainToolbar QCheckBox { background: transparent; }
QFrame#mainToolbar { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #102640, stop:0.6 #131e38, stop:1 #211d43); border: 1px solid #34496c; border-radius: 8px; padding: 4px; }
QFrame#panel { border-radius: 7px; }
QFrame#panel[active="true"] QFrame#panelHeading { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #123f59, stop:1 #292957); }
QFrame#panel[active="true"] { border-color: #1adce6; }
QTabBar::tab { border-top-left-radius: 5px; border-top-right-radius: 5px; }
QTabBar::tab:selected { background: #17334c; }
QToolButton#connectServerButton { border-radius: 7px; font-weight: 700; }
QLineEdit:focus { border-color: #1adce6; }
QPushButton { border-radius: 5px; }
QHeaderView::section { background: #1a2c48; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #18dae5, stop:0.6 #368cff, stop:1 #8054e9); }
"""
    if key.startswith('soovee'):
        css += """
QFrame#panel { border-width: 1px; border-radius: 9px; }
QFrame#panel[active="true"] { border: 1px solid $accent; }
QFrame#tabStrip { background: $bg; border: none; }
QTabBar { background: transparent; }
QHeaderView::section { padding: 8px 10px; border-right: 1px solid $border; }
QTreeView::item { height: 26px; padding: 1px 7px; }
QLineEdit#pathEdit { border-radius: 6px; padding: 7px 9px; }
QFrame#mainToolbar { border-radius: 9px; padding: 5px; }
"""
    if key == 'soovee_light':
        css += """
QFrame#mainToolbar { background: #ffffff; border: 1px solid #d0daea; }
QFrame#panelHeading { background: #eaf0f8; }
QFrame#panel[active="true"] QFrame#panelHeading { background: #e3ecfc; }
QPushButton { border-radius: 6px; }
QLineEdit { border-radius: 6px; }
"""
    check = 'check-dark.svg' if QColor(t['primary_text']).lightness() < 128 else 'check-light.svg'
    check_path = str(Path(__file__).parent / 'assets' / check).replace('\\', '/').replace('"', '\\"')
    css = css.replace('$check_icon', check_path)
    for name, value in sorted(t.items(), key=lambda item: -len(item[0])):
        css = css.replace("$" + name, value)
    return css


def apply_theme(app, key):
    t = THEMES.get(key, THEMES["light"])
    palette = QPalette()
    for role, color in [(QPalette.ColorRole.Window, t["bg"]), (QPalette.ColorRole.WindowText, t["text"]),
                        (QPalette.ColorRole.Base, t["surface"]), (QPalette.ColorRole.AlternateBase, t["alternate"]),
                        (QPalette.ColorRole.Text, t["text"]), (QPalette.ColorRole.Button, t["button"]),
                        (QPalette.ColorRole.ButtonText, t["text"]), (QPalette.ColorRole.Highlight, t["selected"]),
                        (QPalette.ColorRole.HighlightedText, t["selected_text"]),
                        (QPalette.ColorRole.ToolTipBase, t["surface"]), (QPalette.ColorRole.ToolTipText, t["text"])]:
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t["disabled"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t["disabled"]))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet(key))
