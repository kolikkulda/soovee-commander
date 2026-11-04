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
