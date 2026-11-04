import ast
import json
from pathlib import Path
from string import Formatter

from soovee_commander.i18n import set_language, tr


def test_translation_placeholders_and_filename_values_are_preserved():
    try:
        set_language("cs")
        filename = 'literal {v0} $(do-not-execute).txt'
        translated = tr("Preview · {v0}").format(v0=filename)
        assert filename in translated and translated != "Preview · " + filename
        assert tr("A message without a translation") == "A message without a translation"
    finally:
        set_language("en")
    assert tr("Rename") == "Rename"


def test_catalog_templates_match_english_fields_and_source_messages_are_english():
    root = Path(__file__).parents[1] / "src" / "soovee_commander"
    catalog = json.loads((root / "locales" / "cs.json").read_text(encoding='utf-8'))
    for source, target in catalog.items():
        # Literal help strings containing {files}, etc. are not interpolated.
        if "{v0}" in source:
            source_fields = {field for _, field, _, _ in Formatter().parse(source) if field is not None}
            target_fields = {field for _, field, _, _ in Formatter().parse(target) if field is not None}
            assert source_fields == target_fields, source
    for file in root.rglob("*.py"):
        for node in ast.walk(ast.parse(file.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not any(c in node.value for c in "ěščřžýáíéůúťďňĚŠČŘŽÝÁÍÉŮÚŤĎŇ"), (file.name, node.value)
