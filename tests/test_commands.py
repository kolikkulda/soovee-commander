import copy
import json

import pytest

from soovee_commander.commands import defaults, normalize_key, validate_config


def test_added_editor_commands_preserve_existing_custom_shortcuts():
    old = defaults()
    old['keys'] = {identity: aliases for identity, aliases in old['keys'].items()
                   if not identity.startswith('editor_') or identity in ('editor_save', 'editor_close')}
    old['keys']['editor_save'] = ['Ctrl+F']
    old['keys']['editor_close'] = ['F3']
    result = validate_config(old)
    assert result['keys']['editor_save'] == ['Ctrl+F']
    assert result['keys']['editor_close'] == ['F3']
    assert 'Ctrl+F' not in result['keys']['editor_find']
    assert result['keys']['editor_find_next'] == []


def test_default_and_total_commander_profiles_validate():
    normal = validate_config(defaults())
    tc = validate_config(defaults("tc"))
    assert normal["keys"]["rename"] == ["F2", "Shift+F6"]
    assert "F2" in tc["keys"]["refresh"]
    assert tc["keys"]["rename"] == ["Shift+F6"]
    assert tc["keys"]["new_tab_background"] == ["Ctrl+Shift+T", "Meta+Shift+T"]


def test_collision_is_rejected_before_applying_any_change():
    config = defaults()
    config["keys"]["rename"] = ["F5"]
    with pytest.raises(ValueError, match="assigned to both"):
        validate_config(config)


@pytest.mark.parametrize("value", ["", "NotAKey", "Ctrl+K, Ctrl+R", None, "x" * 101])
def test_invalid_or_multi_step_shortcut_is_rejected(value):
    with pytest.raises(ValueError):
        normalize_key(value)


def test_unmodified_global_letter_would_not_break_path_typing():
    config = defaults()
    config["keys"]["rename"] = ["R"]
    with pytest.raises(ValueError, match="path editing"):
        validate_config(config)


def test_export_import_retains_key_aliases_and_bar_customizations():
    config = defaults()
    config["keys"]["rename"] = ["F9", "Shift+F6"]
    config["bottom"] = [{"command": "rename", "label": "Moje přejmenování"}, {"command": "view", "label": ""}]
    config["top"] = []
    assert validate_config(json.loads(json.dumps(config))) == config


def test_unknown_bar_command_cannot_execute_an_external_program():
    config = defaults()
    config["top"] = [{"command": "run_shell", "label": "something"}]
    with pytest.raises(ValueError):
        validate_config(config)


def test_file_panel_keys_are_not_menu_shortcuts_on_macos(monkeypatch):
    """On macOS text after a tab becomes a native menu key equivalent that would
    swallow Return, Backspace or Space in dialogs; show it as plain text there."""
    from PySide6.QtGui import QKeySequence
    from soovee_commander import commands
    key = QKeySequence('Return')
    monkeypatch.setattr(commands.sys, 'platform', 'darwin')
    assert '\t' not in commands.menu_text('Open item', key) and commands.menu_text('Open item', key).startswith('Open item  (')
    monkeypatch.setattr(commands.sys, 'platform', 'win32')
    assert commands.menu_text('Open item', key).startswith('Open item\t')
    assert commands.menu_text('Copy') == 'Copy'


def test_rename_works_on_shares_without_atomic_no_replace(tmp_path, monkeypatch):
    import pytest
    import soovee_commander.providers as providers
    monkeypatch.setattr(providers, 'rename_no_replace', lambda source, destination: False)   # SMB / NFS
    provider = providers.LocalProvider()
    (tmp_path / 'a.srt').write_text('a'); (tmp_path / 'taken.srt').write_text('keep')
    provider.rename(str(tmp_path / 'a.srt'), str(tmp_path / 'b.srt'))
    with pytest.raises(FileExistsError):
        provider.rename(str(tmp_path / 'b.srt'), str(tmp_path / 'taken.srt'))
    assert (tmp_path / 'taken.srt').read_text() == 'keep' and (tmp_path / 'b.srt').exists()
    (tmp_path / 'dir').mkdir()
    provider.rename(str(tmp_path / 'dir'), str(tmp_path / 'folder'))
    assert sorted(p.name for p in tmp_path.iterdir()) == ['b.srt', 'folder', 'taken.srt']
