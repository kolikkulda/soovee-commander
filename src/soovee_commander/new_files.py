"""New-file types: plain text formats, minimal valid office documents and user templates.

Office documents are generated from the smallest part set their applications
accept, without third-party libraries. User templates are ordinary files in a
templates folder; a new file is a copy with the chosen name.
"""
from dataclasses import dataclass
import io
import os
from pathlib import Path
import zipfile
from xml.sax.saxutils import escape

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                               QLineEdit, QVBoxLayout)

from .i18n import tr
from .dialog_kit import StandardDialog


@dataclass(frozen=True)
class FileType:
    key: str
    title: str
    extension: str
    default_name: str
    text: bool = True
    executable: bool = False


TYPES = (
    FileType("text", 'Text document', ".txt", 'New text document'),
    FileType("markdown", 'Markdown document', ".md", 'New document'),
    FileType("empty", 'Empty file without extension', "", 'New file'),
    FileType("html", 'HTML page', ".html", 'index'),
    FileType("json", 'JSON data', ".json", 'data'),
    FileType("csv", 'CSV table', ".csv", 'table'),
    FileType("python", 'Python script', ".py", 'script', executable=True),
    *((FileType("batch", 'Batch script', ".bat", 'script'),) if os.name == "nt" else
      (FileType("shell", 'Shell script', ".sh", 'script', executable=True),)),
    FileType("docx", 'Word document', ".docx", 'New document', text=False),
    FileType("xlsx", 'Excel workbook', ".xlsx", 'New workbook', text=False),
    FileType("odt", 'OpenDocument text', ".odt", 'New document', text=False),
    FileType("ods", 'OpenDocument spreadsheet', ".ods", 'New spreadsheet', text=False),
)
BY_KEY = {item.key: item for item in TYPES}


def templates_folder():
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base or Path.home() / ".soovee-commander") / "Templates"


def user_templates():
    folder = templates_folder()
    try:
        return sorted((p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")), key=lambda p: p.name.casefold())
    except OSError:
        return []


def _zip(parts, *, stored_first=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if stored_first:  # OpenDocument requires an uncompressed leading mimetype.
            archive.writestr(zipfile.ZipInfo(stored_first[0]), stored_first[1], compress_type=zipfile.ZIP_STORED)
        for name, data in parts.items():
            archive.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_PACKAGE_RELS = (_XML + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="{}"/>'
                 '</Relationships>')


def _docx():
    return _zip({
        "[Content_Types].xml": _XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>',
        "_rels/.rels": _PACKAGE_RELS.format("word/document.xml"),
        "word/document.xml": _XML + '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p/><w:sectPr/></w:body></w:document>',
    })


def _xlsx():
    return _zip({
        "[Content_Types].xml": _XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>',
        "_rels/.rels": _PACKAGE_RELS.format("xl/workbook.xml"),
        "xl/workbook.xml": _XML + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": _XML + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>',
        "xl/worksheets/sheet1.xml": _XML + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>',
    })


def _opendocument(kind):
    mimetype = f"application/vnd.oasis.opendocument.{kind}"
    body = '<office:text><text:p/></office:text>' if kind == "text" else \
        '<office:spreadsheet><table:table table:name="Sheet1"><table:table-row><table:table-cell/></table:table-row></table:table></office:spreadsheet>'
    return _zip({
        "content.xml": _XML + '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
            f'office:version="1.2"><office:body>{body}</office:body></office:document-content>',
        "META-INF/manifest.xml": _XML + '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
            f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{mimetype}"/>'
            '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
            '</manifest:manifest>',
    }, stored_first=("mimetype", mimetype))


def content(key, name):
    """Initial bytes for a built-in type; name is the chosen filename."""
    title = escape(Path(name).stem or name)
    newline = "\r\n" if os.name == "nt" else "\n"
    if key == "markdown":
        return f"# {Path(name).stem}{newline}{newline}".encode()
    if key == "html":
        return newline.join(['<!doctype html>', '<html lang="en">', '<head>', '  <meta charset="utf-8">',
                             '  <meta name="viewport" content="width=device-width, initial-scale=1">',
                             f'  <title>{title}</title>', '</head>', '<body>', '', '</body>', '</html>', '']).encode()
    if key == "json":
        return ("{}" + newline).encode()
    if key == "python":
        return newline.join(['#!/usr/bin/env python3', '', '', 'def main():', '    pass', '', '',
                             'if __name__ == "__main__":', '    main()', '']).encode()
    if key == "shell":
        return b"#!/bin/sh\nset -eu\n\n"
    if key == "batch":
        return b"@echo off\r\n\r\n"
    if key == "docx":
        return _docx()
    if key == "xlsx":
        return _xlsx()
    if key in ("odt", "ods"):
        return _opendocument("text" if key == "odt" else "spreadsheet")
    return b""


class NewFileDialog(StandardDialog):
    """Choose a type (or user template) and a name; the extension follows the type."""

    def __init__(self, parent, key="text", existing=()):
        super().__init__(parent, tr('New file'), tr('New file'),
                         tr('The file is created in the current folder. An existing file is never replaced.'),
                         icon="new_file", action=tr('Create'))
        self.existing = {name.casefold() for name in existing}
        layout = self.body
        form = QFormLayout()
        self.kind = QComboBox()
        self.kind.setProperty('translatedItems', True)
        for item in TYPES:
            self.kind.addItem(tr(item.title) + (f"  ({item.extension})" if item.extension else ""), item.key)
        for template in user_templates():
            self.kind.addItem(tr('Template: {v0}').format(v0=template.name), "template:" + str(template))
        form.addRow(tr('Type:'), self.kind)
        self.name = QLineEdit()
        form.addRow(tr('Name:'), self.name)
        layout.addLayout(form)
        self.open_editor = QCheckBox(tr('Open in the editor after creating (text files)'))
        self.open_editor.setChecked(True)
        layout.addWidget(self.open_editor)
        self.warning = QLabel()
        self.warning.setObjectName('muted')
        layout.addWidget(self.warning)
        self._previous_extension = None
        self.kind.currentIndexChanged.connect(self.kind_changed)
        self.name.textChanged.connect(self.validate)
        index = self.kind.findData(key)
        self.kind.setCurrentIndex(max(0, index))
        self.kind_changed()

    def selected(self):
        data = self.kind.currentData()
        if data.startswith("template:"):
            path = Path(data.split(":", 1)[1])
            return None, path
        return BY_KEY[data], None

    def kind_changed(self, *args):
        file_type, template = self.selected()
        suffix = template.suffix if template else file_type.extension
        name = self.name.text()
        stem = name[:-len(self._previous_extension)] if self._previous_extension and name.endswith(self._previous_extension) else name
        if not name or self._previous_extension is None:
            stem = tr(file_type.default_name) if file_type else template.stem
        candidate, number = stem + suffix, 2
        while candidate.casefold() in self.existing:
            candidate, number = f"{stem} ({number}){suffix}", number + 1
        self.name.setText(candidate)
        self._previous_extension = suffix
        text = bool(file_type and file_type.text) or bool(template and template.suffix.lower() in {".txt", ".md", ".csv", ".json", ".html", ".xml", ".py", ".sh"})
        self.open_editor.setEnabled(text)  # The caller reads isEnabled(); visibility only reflects it.
        self.open_editor.setVisible(text)
        self.name.setFocus()
        self.name.setSelection(0, len(candidate) - len(suffix) if suffix and candidate.endswith(suffix) else len(candidate))

    def validate(self, *args):
        name = self.name.text().strip()
        problem = ""
        if not name:
            problem = tr('Enter a filename.')
        elif name in (".", "..") or any(c in name for c in '/\\\0') or (os.name == "nt" and any(c in name for c in '<>:"|?*')):
            problem = tr('The name contains characters that are not allowed in filenames.')
        elif name.casefold() in self.existing:
            problem = tr('An item with this name already exists.')
        self.warning.setText(problem)
        self.ok.setEnabled(not problem)
