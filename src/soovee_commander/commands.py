"""One command registry for menus, shortcuts and configurable command bars."""
from .i18n import tr
from dataclasses import dataclass
import json
import sys

from .command_help import HELP

from PySide6.QtCore import QTimer, QObject, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence


@dataclass(frozen=True)
class Command:
    id: str
    title: str
    keys: tuple = ()
    scope: str = "window"


COMMANDS = (
    Command("about", "About Soovee Commander…"),
    Command("about_qt", "About Qt…"),
    Command("devices", "Soovee Transfers · Devices"),
    Command("center_panels", "Equal panels (50:50)", ("Ctrl+Shift+E", "Meta+Shift+E")),
    Command("open_with", 'Open with…'),
    Command("file_associations", 'Custom file associations…'),
    Command("columns", 'Configure columns…'),
    Command("panel_appearance", 'Panel appearance…'),
    Command("properties", 'Properties…', ("Alt+Return",), "files"),
    Command("reveal", 'Reveal in Finder / Explorer'),
    Command("move_tab_other", "Move tab to the other panel"),
    Command("copy_details", "Copy file details"),
    Command("extract", "Extract archives…", ("Alt+F9",)),
    Command("copy_names", 'Copy filenames'),
    Command("open", 'Open item', ("Return", "Enter"), "files"),
    Command("parent", 'Parent folder', ("Backspace", "Ctrl+PgUp"), "files"),
    Command("root", 'Root of drive or location', ("Ctrl+\\", "Meta+\\"), "files"),
    Command("enter_directory", 'Enter folder / archive', ("Ctrl+PgDown",), "files"),
    Command("switch_panel", 'Switch left / right panel', ("Tab",), "files"),
    Command("toggle_mark", 'Toggle selection and advance cursor', ("Space", "Ins"), "files"),
    Command("clipboard_copy", 'Copy files to clipboard', ("Ctrl+C", "Meta+C"), "files"),
    Command("clipboard_cut", "Cut files", ("Ctrl+X", "Meta+X"), "files"),
    Command("clipboard_paste", 'Paste files', ("Ctrl+V", "Meta+V"), "files"),
    Command("delete_permanent", 'Delete permanently without Trash', ("Shift+Del",), "files"),
    Command("search", 'Search files and contents…', ("Alt+F7",)),
    Command("multi_rename", 'Multi-rename…', ("Ctrl+M", "Meta+M")),
    Command("undo_rename", 'Undo multi-rename'),
    Command("compare_dirs", 'Compare and synchronize folders…'),
    Command("compare_files", 'Compare file contents…'),
    Command("auto_sizes", 'Calculate folder sizes automatically in the background'),
    Command("folder_sizes", 'Calculate sizes of selected folders', ("Alt+Shift+Return",)),
    Command("rename_tab", 'Name tab…'),
    Command("lock_tab", 'Lock / unlock tab path'),
    Command("view", 'Preview', ("F3",)),
    Command("edit", 'Edit', ("F4",)),
    Command("rename", 'Rename', ("F2", "Shift+F6")),
    Command("copy", 'Copy', ("F5",)),
    Command("move", 'Move', ("F6",)),
    Command("mkdir", 'New folder', ("F7",)),
    Command("delete", 'Delete', ("F8", "Del"), "files"),
    Command("pack", 'Create archive…', ("Alt+F5",)),
    Command("refresh", 'Refresh panel', ("Ctrl+R", "Meta+R")),
    Command("auto_refresh", 'Refresh panels automatically'),
    Command("new_file", 'New file…', ("Shift+F4",)),
    Command("templates_folder", 'Open templates folder'),
    Command("sort_added", 'Sort by date added'),
    Command("folders_first", 'Folders always first'),
    # Cmd+Q quits on macOS, so the TC quick view key uses the Control key there.
    Command("quick_view", 'Quick view in the other panel', ("Meta+Q",) if sys.platform == "darwin" else ("Ctrl+Q",)),
    Command("internal_previews", 'Use built-in previews'),
    Command("back", 'Back in history', ("Alt+Left",)),
    Command("forward", 'Forward in history', ("Alt+Right",)),
    Command("focus_path", 'Enter / paste path', ("Ctrl+L", "Meta+L")),
    Command("filter", 'Quick filter', ("Ctrl+F", "Meta+F")),
    Command("copy_paths", 'Copy full paths of selection', ("Ctrl+Shift+C", "Meta+Shift+C")),
    Command("copy_directory", 'Copy folder path'),
    Command("paste_path", 'Paste and open path', ("Ctrl+Shift+V", "Meta+Shift+V")),
    Command("new_tab", 'New tab', ("Ctrl+T", "Meta+T")),
    Command("new_tab_background", 'New background tab'),
    Command("open_dir_newtab", 'Folder under cursor in new tab', ("Ctrl+Up",), "files"),
    Command("open_dir_other_tab", 'Folder under cursor in a tab in the other panel', ("Ctrl+Shift+Up",), "files"),
    Command("close_tab", 'Close tab', ("Ctrl+W", "Meta+W")),
    Command("reopen_tab", 'Reopen closed tab', ("Ctrl+Shift+T", "Meta+Shift+T")),
    Command("next_tab", 'Next tab', ("Ctrl+Tab",)),
    Command("previous_tab", 'Previous tab', ("Ctrl+Shift+Tab",)),
    Command("close_other_tabs", 'Close other tabs'),
    Command("select_all", 'Select all', ("Ctrl+A", "Meta+A"), "files"),
    Command("clear_selection", 'Clear selection', (), "files"),
    Command("invert_selection", 'Invert selection', ("*",), "files"),
    Command("swap", "Swap panels", ("Ctrl+U", "Meta+U")),
    Command("same_path", 'Same path in the other panel'),
    Command("sort_name", 'Sort by name', ("Ctrl+F3",)),
    Command("sort_extension", 'Sort by extension', ("Ctrl+F4",)),
    Command("sort_date", 'Sort by date', ("Ctrl+F5",)),
    Command("sort_size", 'Sort by size', ("Ctrl+F6",)),
    Command("left_drive", 'Choose drive in left panel', ("Alt+F1",)),
    Command("right_drive", 'Choose drive in right panel', ("Alt+F2",)),
    Command("context_menu", 'Item context menu', ("Shift+F10",), "files"),
    Command("history_menu", 'Folder history', ("Alt+Down",), "files"),
    Command("home", 'Home'),
    Command("local", 'Local disk'),
    Command("choose_directory", 'Open folder…'),
    Command("connect", 'Connect to server…'),
    Command("settings", 'Settings…', ("Ctrl+,", "Meta+,")),
    Command("shortcuts_help", 'Keyboard shortcuts…', ("F1",)),
    Command("install_update", 'Install update…'),
    Command("quit", 'Quit application'),
    Command("external_settings", 'External commands and plugins…'),
    Command("external_1", 'External command 1'),
    Command("external_2", 'External command 2'),
    Command("external_3", 'External command 3'),
    Command("external_4", 'External command 4'),
    Command("external_5", 'External command 5'),
    Command("external_6", 'External command 6'),
    Command("external_7", 'External command 7'),
    Command("external_8", 'External command 8'),
    Command("external_9", 'External command 9'),
    Command("external_10", 'External command 10'),
    Command("external_11", 'External command 11'),
    Command("external_12", 'External command 12'),
    Command("external_13", 'External command 13'),
    Command("external_14", 'External command 14'),
    Command("external_15", 'External command 15'),
    Command("external_16", 'External command 16'),
    Command("editor_save", 'Editor: save', ("Ctrl+S", "Meta+S"), "editor"),
    Command("diagnostic_log", 'Diagnostic log…'),
    Command("panel_scrolling", 'Panel scrolling…'),
    Command("editor_save_as", 'Editor: save as', ("Ctrl+Shift+S", "Meta+Shift+S"), "editor"),
    Command("editor_find", 'Editor/viewer: find', ("Ctrl+F", "Meta+F"), "editor"),
    Command("editor_replace", 'Editor: replace', ("Ctrl+H", "Meta+Alt+F"), "editor"),
    Command("editor_find_next", 'Editor/viewer: next match', ("F3",), "editor"),
    Command("editor_find_previous", 'Editor/viewer: previous match', ("Shift+F3",), "editor"),
    Command("editor_goto", 'Editor/viewer: go to line', ("Ctrl+G", "Meta+G"), "editor"),
    Command("editor_undo", 'Editor: undo', ("Ctrl+Z", "Meta+Z"), "editor"),
    Command("editor_redo", 'Editor: redo', ("Ctrl+Shift+Z", "Meta+Shift+Z"), "editor"),
    Command("editor_zoom_in", 'Editor/viewer: zoom in', ("Ctrl+=", "Meta+="), "editor"),
    Command("editor_zoom_out", 'Editor/viewer: zoom out', ("Ctrl+-", "Meta+-"), "editor"),
    Command("editor_close", 'Editor: close', ("Esc",), "editor"),
)
BY_ID = {command.id: command for command in COMMANDS}
DEFAULT_TOP = ["back", "forward", "refresh", "swap", "same_path", "pack", "local", "settings"]
DEFAULT_BOTTOM = ["rename", "view", "edit", "copy", "move", "mkdir", "delete"]


def defaults(profile="stereo"):
    keys = {command.id: list(command.keys) for command in COMMANDS}
    if profile == "tc":
        keys["refresh"] = ["F2", "Ctrl+R", "Meta+R"]
        keys["rename"] = ["Shift+F6"]
        keys["filter"] = ["Ctrl+S", "Meta+S"]
        keys["focus_path"] = []
        keys["reopen_tab"] = []
        keys["new_tab_background"] = ["Ctrl+Shift+T", "Meta+Shift+T"]
    return {"schema": 1, "keys": keys,
            "top": [{"command": key, "label": ""} for key in DEFAULT_TOP],
            "bottom": [{"command": key, "label": ""} for key in DEFAULT_BOTTOM]}


def normalize_key(text):
    if not isinstance(text, str) or len(text) > 100:
        raise ValueError(tr('Invalid keyboard shortcut.'))
    sequence = QKeySequence.fromString(text.strip(), QKeySequence.SequenceFormat.PortableText)
    if sequence.isEmpty() or sequence.count() != 1 or sequence[0].key() == Qt.Key.Key_unknown:
        raise ValueError(tr('Invalid shortcut: {v0}. Use a single key combination.').format(v0=text))
    return sequence.toString(QKeySequence.SequenceFormat.PortableText)


def validate_config(config):
    if not isinstance(config, dict) or config.get("schema") != 1 or not isinstance(config.get("keys"), dict):
        raise ValueError(tr('Invalid controls configuration file.'))
    result = defaults()
    explicit = set()
    for identity, aliases in config['keys'].items():
        if identity in BY_ID and isinstance(aliases, list):
            for alias in aliases:
                explicit.add((BY_ID[identity].scope == 'editor', normalize_key(alias)))
    used = {}
    for command in COMMANDS:
        aliases = config["keys"].get(command.id, list(command.keys))
        if not isinstance(aliases, list) or len(aliases) > 8:
            raise ValueError(tr('Command {v0}: at most 8 shortcuts are allowed.').format(v0=command.title))
        normalized = []
        for alias in aliases:
            key = normalize_key(alias)
            # New commands must not steal a user's older custom binding or
            # make an otherwise valid saved profile fall back to all defaults.
            if command.id not in config['keys'] and (command.scope == 'editor', key) in explicit:
                continue
            if key in normalized:
                continue
            for scope, title in used.get(key, []):
                if (scope == "editor") == (command.scope == "editor"):
                    raise ValueError(tr('Shortcut {v0} is assigned to both “{v1}” and “{v2}”.').format(v0=key, v1=title, v2=command.title))
            sequence = QKeySequence.fromString(key, QKeySequence.SequenceFormat.PortableText)[0]
            if command.scope in ("window", "editor") and sequence.keyboardModifiers() == Qt.KeyboardModifier.NoModifier:
                if not (Qt.Key.Key_F1 <= sequence.key() <= Qt.Key.Key_F35 or
                        (command.id == "editor_close" and sequence.key() == Qt.Key.Key_Escape)):
                    raise ValueError(tr('Shortcut {v0} for “{v1}” needs Ctrl, Alt, Shift or Meta to avoid blocking path editing.').format(v0=key, v1=command.title))
            used.setdefault(key, []).append((command.scope, command.title))
            normalized.append(key)
        result["keys"][command.id] = normalized
    for name in ("top", "bottom"):
        items = config.get(name, result[name])
        if not isinstance(items, list) or len(items) > 16:
            raise ValueError(tr('A command bar may have at most 16 buttons.'))
        clean = []
        for item in items:
            if not isinstance(item, dict) or item.get("command") not in BY_ID or not isinstance(item.get("label", ""), str):
                raise ValueError(tr('Invalid button in settings.'))
            if BY_ID[item["command"]].scope == "editor":
                raise ValueError(tr('Editor commands belong in the editor window, not on the file manager bars.'))
            label = item.get("label", "").strip()
            if len(label) > 50 or any(c in label for c in "\r\n\t"):
                raise ValueError(tr('Button labels may have at most 50 characters and no line breaks.'))
            clean.append({"command": item["command"], "label": label})
        result[name] = clean
    return result


def menu_text(title, key=None):
    """Menu label for a command whose key is handled by the file panel itself.

    Qt turns text after a tab into a real menu shortcut. On macOS that becomes
    a native key equivalent that also fires while a dialog is open, so Return,
    Backspace, Space or Cmd+C would never reach the dialog's text field. There
    the key is shown as plain text instead.
    """
    if key is None:
        return title
    label = key.toString(QKeySequence.SequenceFormat.NativeText)
    return f"{title}  ({label})" if sys.platform == "darwin" else f"{title}\t{label}"


class CommandRegistry(QObject):
    changed = Signal()

    def __init__(self, window, callbacks):
        super().__init__(window)
        self.window, self.callbacks = window, callbacks
        self.actions = {}
        self.config = defaults()
        for spec in COMMANDS:
            action = QAction(tr(spec.title), window)
            action.setObjectName("command_" + spec.id)
            # Run after the native menu has finished handling the key: a modal dialog opened
            # inside macOS menu key handling does not receive Return/Enter.
            action.triggered.connect(lambda checked=False, command=spec.id: QTimer.singleShot(0, lambda: self.execute(command)))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            if spec.scope == "window":
                window.addAction(action)
            self.actions[spec.id] = action
        self.load_error = None
        try:
            stored = window.settings.value("controls", "")
            if stored:
                self.config = validate_config(json.loads(stored))
                if not window.settings.value("controls_f2_bar_migrated", False, type=bool):
                    old_bottom = [{"command": key, "label": ""} for key in ("view", "edit", "copy", "move", "mkdir", "delete")]
                    if self.config["bottom"] == old_bottom:
                        self.config["bottom"].insert(0, {"command": "rename", "label": ""})
                        window.settings.setValue("controls", json.dumps(self.config, ensure_ascii=False))
                if not window.settings.value("controls_refresh_bar_migrated", False, type=bool):
                    # Earlier default bar without Refresh: add it next to history navigation.
                    old_top = [{"command": key, "label": ""} for key in DEFAULT_TOP if key != "refresh"]
                    if self.config["top"] == old_top:
                        self.config["top"].insert(2, {"command": "refresh", "label": ""})
                        window.settings.setValue("controls", json.dumps(self.config, ensure_ascii=False))
        except (ValueError, TypeError) as exc:
            self.load_error = str(exc)
        self.apply(self.config, persist=False)
        window.settings.setValue("controls_f2_bar_migrated", True)
        window.settings.setValue("controls_refresh_bar_migrated", True)

    def apply(self, config, persist=True):
        valid = validate_config(config)
        self.config = valid
        self.file_key_map = {key: spec.id for spec in COMMANDS if spec.scope == "files" for key in valid["keys"][spec.id]}
        self.managed_file_keys = {normalize_key(key) for spec in COMMANDS if spec.scope == "files" for key in spec.keys}
        for spec in COMMANDS:
            action = self.actions[spec.id]
            keys = [QKeySequence.fromString(key, QKeySequence.SequenceFormat.PortableText) for key in valid["keys"][spec.id]]
            action.setShortcuts(keys if spec.scope == "window" else [])
            action.setText(menu_text(tr(spec.title), keys[0] if keys and spec.scope != "window" else None))
            if spec.id in HELP:
                action.setStatusTip(tr(HELP[spec.id]))
        if persist:
            self.window.settings.setValue("controls", json.dumps(valid, ensure_ascii=False))
            self.window.settings.sync()
        self.changed.emit()

    def execute(self, command):
        callback = self.callbacks.get(command)
        if callback:
            callback()

    def key_label(self, command):
        keys = self.config["keys"][command]
        return QKeySequence.fromString(keys[0], QKeySequence.SequenceFormat.PortableText).toString(QKeySequence.SequenceFormat.NativeText) if keys else ""

    def button_label(self, item, include_key=True):
        title = item.get("label") or tr(BY_ID[item["command"]].title).rstrip("…")
        key = self.key_label(item["command"]) if include_key else ""
        return f"{key}  {title}" if key else title

    def dispatch_file_key(self, event):
        combination = event.keyCombination()
        modifiers = combination.keyboardModifiers() & ~Qt.KeyboardModifier.KeypadModifier
        from PySide6.QtCore import QKeyCombination
        key = QKeySequence(QKeyCombination(modifiers, combination.key())).toString(QKeySequence.SequenceFormat.PortableText)
        if key in self.file_key_map:
            self.execute(self.file_key_map[key])
            event.accept()
            return True
        if key in self.managed_file_keys:
            event.accept()  # Removed bindings must not fall back to hidden QTreeView defaults.
            return True
        return False
