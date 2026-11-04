"""Built-in previews of common document types, shared by F3 and the quick view.

Every renderer works on bytes already read by the caller (bounded, on a
worker thread) and builds widgets on the GUI thread. Nothing is fetched from
the network: HTML and Markdown are shown without loading external resources.
Malformed files raise PreviewError, which the caller shows as a message.
"""
import csv
import io
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QMovie, QPainter, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QPushButton, QScrollArea, QSizePolicy, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .i18n import tr

# Group key → (menu title, extensions). Order is the order in settings menus.
GROUPS = {
    "images": ('Images', {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".ico", ".heic", ".heif"}),
    "svg": ('SVG drawings', {".svg"}),
    "pdf": ('PDF documents', {".pdf"}),
    "markdown": ('Markdown', {".md", ".markdown"}),
    "html": ('HTML pages (without external content)', {".html", ".htm"}),
    "tables": ('CSV and TSV tables', {".csv", ".tsv"}),
    "json": ('JSON data', {".json"}),
    "office": ('Word, Excel, PowerPoint and OpenDocument (text only)', {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"}),
}
# Formats that cannot be shown from a truncated prefix.
WHOLE_FILE = {"images", "svg", "pdf", "office", "json"}
PREVIEW_LIMIT = 64 * 1024 * 1024
MAX_ROWS, MAX_COLUMNS, MAX_NODES = 5000, 200, 20000
_ZIP_MEMBER_LIMIT = 64 * 1024 * 1024


class PreviewError(Exception):
    pass


def group_for(name):
    suffix = Path(name).suffix.lower()
    return next((key for key, (title, suffixes) in GROUPS.items() if suffix in suffixes), None)


def enabled_group(name, settings):
    group = group_for(name)
    if group and settings.value("internal_previews", True, type=bool) and settings.value("preview_" + group, True, type=bool):
        return group
    return None


def pdf_available():
    try:
        from PySide6 import QtPdf, QtPdfWidgets  # noqa: F401  Optional Qt add-on module.
        return True
    except ImportError:
        return False


def build(name, data, complete=True, *, settings=None, host=None):
    """Return a preview widget for name/data, None when the type has no preview."""
    group = enabled_group(name, settings) if settings is not None else group_for(name)
    if group is None:
        return None
    if group in WHOLE_FILE and not complete:
        raise PreviewError(tr('The file is larger than the preview limit of {v0} MB.').format(v0=PREVIEW_LIMIT // 1024 // 1024))
    try:
        return RENDERERS[group](name, data)
    except PreviewError:
        raise
    except (ValueError, KeyError, IndexError, zipfile.BadZipFile, ElementTree.ParseError, csv.Error, UnicodeError, RecursionError) as exc:
        raise PreviewError(tr('The file could not be read as {v0}: {v1}').format(v0=tr(GROUPS[group][0]), v1=exc)) from exc


class ImagePreview(QScrollArea):
    """Fits the picture to the available space; double-click toggles actual size."""

    def __init__(self, pixmap=None, movie=None):
        super().__init__()
        self.pixmap, self.movie, self.fit = pixmap, movie, True
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidgetResizable(False)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidget(self.label)
        if movie is not None:
            self.label.setMovie(movie)
            movie.start()
        self.update_image()

    def update_image(self):
        if self.movie is not None:
            size = self.movie.currentPixmap().size()
            if self.fit and size.width() > 0:
                size = size.scaled(self.viewport().size().boundedTo(size), Qt.AspectRatioMode.KeepAspectRatio)
            self.movie.setScaledSize(size)
            self.label.resize(size)
            return
        if self.pixmap is None:
            return
        target = self.pixmap if not self.fit else self.pixmap.scaled(
            self.viewport().size().boundedTo(self.pixmap.size()), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.label.setPixmap(target)
        self.label.resize(target.size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_image()

    def mouseDoubleClickEvent(self, event):
        self.fit = not self.fit
        self.update_image()


def _reader(data):
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    return buffer


def _image(name, data):
    buffer = _reader(data)
    QImageReader.setAllocationLimit(256)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.width() * size.height() > 64_000_000:
        raise PreviewError(tr('The image is too large to preview ({v0} × {v1} px).').format(v0=size.width(), v1=size.height()))
    if reader.supportsAnimation() and reader.imageCount() > 1:
        device = _reader(data)  # QMovie reads lazily; the device must outlive it.
        movie = QMovie(device)
        if movie.isValid():
            widget = ImagePreview(movie=movie)
            movie.setParent(widget)
            device.setParent(widget)
            widget.caption = f'{size.width()} × {size.height()} px · {tr("animation")}'
            return widget
    image = reader.read()
    if image.isNull():
        raise PreviewError(tr('The image could not be decoded: {v0}').format(v0=reader.errorString()))
    widget = ImagePreview(QPixmap.fromImage(image))
    widget.caption = f'{image.width()} × {image.height()} px'
    return widget


def _svg(name, data):
    from PySide6.QtSvg import QSvgRenderer
    renderer = QSvgRenderer(QByteArray(data))
    if not renderer.isValid():
        raise PreviewError(tr('The SVG drawing is not valid.'))
    size = renderer.defaultSize()
    if size.isEmpty():
        size = QSize(800, 600)
    size = size.scaled(QSize(2400, 2400), Qt.AspectRatioMode.KeepAspectRatio) if max(size.width(), size.height()) > 2400 or max(size.width(), size.height()) < 400 else size
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    widget = ImagePreview(QPixmap.fromImage(image))
    widget.caption = f'{renderer.defaultSize().width()} × {renderer.defaultSize().height()}'
    return widget


def _pdf(name, data):
    if not pdf_available():
        raise PreviewError(tr('PDF preview needs the Qt PDF module, which is not part of this build. Open the file in the system viewer.'))
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    document = QPdfDocument(widget)
    buffer = _reader(data)
    buffer.setParent(widget)  # The document reads lazily from this device.
    document.load(buffer)
    if document.status() == QPdfDocument.Status.Error or document.pageCount() == 0:
        raise PreviewError(tr('The PDF document could not be opened ({v0}).').format(v0=document.error().name))
    view = QPdfView(widget)
    view.setDocument(document)
    view.setPageMode(QPdfView.PageMode.MultiPage)
    view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
    row = QHBoxLayout()
    for label, mode in ((tr('Fit width'), QPdfView.ZoomMode.FitToWidth), (tr('Whole page'), QPdfView.ZoomMode.FitInView)):
        button = QPushButton(label)
        button.clicked.connect(lambda checked=False, value=mode: view.setZoomMode(value))
        row.addWidget(button)
    row.addStretch()
    layout.addLayout(row)
    layout.addWidget(view, 1)
    widget.caption = tr('{v0} pages').format(v0=document.pageCount())
    widget.document = document
    return widget


def _browser():
    browser = QTextBrowser()
    browser.setOpenLinks(False)  # Never navigate away or open external content from a preview.
    browser.setOpenExternalLinks(False)
    browser.setReadOnly(True)
    return browser


def _decode(data):
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("cp1250", errors="replace")


def _markdown(name, data):
    browser = _browser()
    browser.setMarkdown(_decode(data))
    browser.caption = tr('Formatted Markdown')
    return browser


class _NoResources(QTextBrowser):
    def loadResource(self, kind, url):
        return None  # Images, stylesheets and other referenced files stay unloaded.


def _html(name, data):
    browser = _NoResources()
    browser.setOpenLinks(False)
    browser.setOpenExternalLinks(False)
    browser.setHtml(_decode(data))
    browser.caption = tr('Simplified HTML without scripts or external content')
    return browser


def _table(rows, caption):
    rows = rows[:MAX_ROWS + 1]
    columns = min(MAX_COLUMNS, max((len(row) for row in rows), default=0))
    table = QTableWidget(max(0, len(rows) - 1), columns)
    if rows:
        table.setHorizontalHeaderLabels([str(value) for value in rows[0][:columns]] + [""] * (columns - len(rows[0][:columns])))
    for r, row in enumerate(rows[1:]):
        for c, value in enumerate(row[:columns]):
            item = QTableWidgetItem(str(value))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(r, c, item)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.resizeColumnsToContents()
    for c in range(columns):
        table.setColumnWidth(c, min(320, table.columnWidth(c)))
    table.caption = caption
    return table


def _csv(name, data):
    text = _decode(data)
    sample = text[:64 * 1024]
    if Path(name).suffix.lower() == ".tsv":
        dialect = csv.excel_tab
    else:
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
    rows = []
    for row in csv.reader(io.StringIO(text), dialect):
        rows.append(row)
        if len(rows) > MAX_ROWS:
            break
    shown = max(0, min(len(rows), MAX_ROWS + 1) - 1)
    caption = tr('{v0} rows').format(v0=shown) + (tr(' · first {v0} rows shown').format(v0=MAX_ROWS) if len(rows) > MAX_ROWS else "")
    return _table(rows, caption)


def _json(name, data):
    value = json.loads(_decode(data))
    tree = QTreeWidget()
    tree.setHeaderLabels([tr('Key'), tr('Value')])
    count = [0]

    def add(parent, key, item):
        count[0] += 1
        if count[0] > MAX_NODES:
            return
        node = QTreeWidgetItem(parent, [str(key), ""])
        if isinstance(item, dict):
            node.setText(1, tr('{v0} items').format(v0=len(item)))
            for child_key, child in item.items():
                add(node, child_key, child)
        elif isinstance(item, list):
            node.setText(1, tr('{v0} items').format(v0=len(item)))
            for index, child in enumerate(item):
                add(node, f"[{index}]", child)
        else:
            node.setText(1, json.dumps(item, ensure_ascii=False))

    add(tree, Path(name).name, value)
    tree.expandToDepth(1)
    tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    tree.caption = tr('JSON structure') + (tr(' · first {v0} values shown').format(v0=MAX_NODES) if count[0] > MAX_NODES else "")
    return tree


def _member(archive, name):
    info = archive.getinfo(name)
    if info.file_size > _ZIP_MEMBER_LIMIT:
        raise PreviewError(tr('The document part {v0} is too large to preview.').format(v0=name))
    return archive.read(info)


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _paragraphs(root, paragraph="p"):
    """Plain text of each paragraph element, including text inside nested runs."""
    return ["".join(element.itertext()) for element in root.iter() if _local(element.tag) == paragraph]


def _text_document(text, caption):
    browser = _browser()
    browser.setPlainText(text)
    browser.caption = caption
    return browser


def _xlsx_rows(archive):
    shared = []
    if "xl/sharedStrings.xml" in archive.namelist():
        for item in ElementTree.fromstring(_member(archive, "xl/sharedStrings.xml")):
            shared.append("".join(node.text or "" for node in item.iter() if _local(node.tag) == "t"))
    sheets = sorted(n for n in archive.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
    if not sheets:
        return [], 0
    root = ElementTree.fromstring(_member(archive, sheets[0]))
    rows = []
    for row in root.iter():
        if _local(row.tag) != "row":
            continue
        values = {}
        for cell in row:
            if _local(cell.tag) != "c":
                continue
            reference = "".join(ch for ch in cell.get("r", "") if ch.isalpha())
            column = 0
            for ch in reference:
                column = column * 26 + ord(ch.upper()) - 64
            value = next((node.text or "" for node in cell.iter() if _local(node.tag) in ("v", "t")), "")
            if cell.get("t") == "s" and value.isdigit() and int(value) < len(shared):
                value = shared[int(value)]
            values[max(0, column - 1) if reference else len(values)] = value
        if values and max(values) < 16384:
            rows.append([values.get(i, "") for i in range(max(values) + 1)])
        if len(rows) > MAX_ROWS:
            break
    return rows, len(sheets)


def _office(name, data):
    suffix = Path(name).suffix.lower()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if suffix == ".docx":
            root = ElementTree.fromstring(_member(archive, "word/document.xml"))
            return _text_document("\n".join(_paragraphs(root)), tr('Text of the Word document without formatting'))
        if suffix == ".pptx":
            slides = sorted((n for n in archive.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")),
                            key=lambda n: int("".join(ch for ch in Path(n).stem if ch.isdigit()) or 0))
            parts = []
            for number, slide in enumerate(slides, 1):
                lines = [line for line in _paragraphs(ElementTree.fromstring(_member(archive, slide))) if line.strip()]
                parts.append(f"— {tr('Slide {v0}').format(v0=number)} —\n" + "\n".join(lines))
            return _text_document("\n\n".join(parts), tr('Text of {v0} slides without layout').format(v0=len(slides)))
        if suffix == ".xlsx":
            rows, sheets = _xlsx_rows(archive)
            header = [chr(65 + i) if i < 26 else str(i + 1) for i in range(max((len(r) for r in rows), default=0))]
            return _table([header, *rows], tr('First sheet of {v0} · values without formulas or formatting').format(v0=sheets))
        root = ElementTree.fromstring(_member(archive, "content.xml"))
        if suffix == ".ods":
            table = next((t for t in root.iter() if _local(t.tag) == "table"), None)
            rows = []
            for row in (table.iter() if table is not None else ()):
                if _local(row.tag) == "table-row":
                    cells = []
                    for cell in row:
                        if _local(cell.tag) in ("table-cell", "covered-table-cell"):
                            text = "\n".join(_paragraphs(cell))
                            repeat = min(int(cell.get("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}number-columns-repeated", "1")), MAX_COLUMNS)
                            cells.extend([text] * repeat)
                    while cells and not cells[-1]:
                        cells.pop()
                    rows.append(cells)
                    if len(rows) > MAX_ROWS:
                        break
            while rows and not rows[-1]:
                rows.pop()
            header = [chr(65 + i) if i < 26 else str(i + 1) for i in range(max((len(r) for r in rows), default=0))]
            return _table([header, *rows], tr('First sheet · values without formulas or formatting'))
        lines = ["".join(e.itertext()) for e in root.iter() if _local(e.tag) in ("p", "h")]
        return _text_document("\n".join(lines), tr('Text of the document without formatting'))


RENDERERS = {"images": _image, "svg": _svg, "pdf": _pdf, "markdown": _markdown, "html": _html,
             "tables": _csv, "json": _json, "office": _office}


def message(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    label.setObjectName("muted")
    return label
