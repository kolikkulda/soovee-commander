"""Small vector-drawn toolbar symbols, rendered for the active palette."""
from functools import lru_cache
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap


@lru_cache(maxsize=256)
def toolbar_icon(command, color):
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(2)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    def lines(points):
        path = QPainterPath(QPointF(*points[0]))
        for point in points[1:]:
            path.lineTo(*point)
        painter.drawPath(path)
    if command in ("back", "forward"):
        x = 1 if command == "back" else -1
        lines([(12 + x * 4, 5), (12 - x * 4, 12), (12 + x * 4, 19)])
        lines([(12 - x * 4, 12), (12 + x * 7, 12)])
    elif command == "refresh":
        painter.drawArc(QRectF(4, 4, 16, 16), 60 * 16, 290 * 16)
        lines([(15, 3), (19, 5.3), (16.5, 9)])
    elif command == "new_file":
        lines([(14, 3), (6, 3), (6, 21), (18, 21), (18, 7), (14, 3), (14, 7), (18, 7)])
        lines([(12, 11), (12, 17)])
        lines([(9, 14), (15, 14)])
    elif command == "copy":
        painter.drawRoundedRect(QRectF(8, 8, 12, 13), 2, 2)
        lines([(5, 16), (4, 16), (4, 3), (15, 3), (15, 5)])
    elif command == "move":
        lines([(3, 8), (3, 20), (21, 20), (21, 9), (11, 9), (9, 6), (3, 6), (3, 8)])
        lines([(8, 14.5), (16, 14.5)])
        lines([(13, 11.5), (16, 14.5), (13, 17.5)])
    elif command in ("delete", "delete_permanent"):
        lines([(4, 6), (20, 6)])
        lines([(9, 6), (9, 3), (15, 3), (15, 6)])
        lines([(6, 6), (7, 21), (17, 21), (18, 6)])
        lines([(10, 10), (10, 17)])
        lines([(14, 10), (14, 17)])
    elif command in ("rename", "multi_rename"):
        painter.drawRoundedRect(QRectF(2, 7, 20, 10), 2, 2)
        lines([(13, 4), (13, 20)])
        lines([(11, 4), (15, 4)])
        lines([(11, 20), (15, 20)])
        lines([(5, 12), (9, 12)])
    elif command == "mkdir":
        lines([(3, 8), (3, 20), (21, 20), (21, 9), (11, 9), (9, 6), (3, 6), (3, 8)])
        lines([(12, 11.5), (12, 17.5)])
        lines([(9, 14.5), (15, 14.5)])
    elif command == "properties":
        painter.drawEllipse(QRectF(3, 3, 18, 18))
        lines([(12, 11), (12, 17)])
        painter.drawPoint(QPointF(12, 7.5))
    elif command == "extract":
        lines([(4, 7), (12, 3), (20, 7), (20, 17), (12, 21), (4, 17), (4, 7)])
        lines([(12, 8), (12, 16)])
        lines([(9, 13), (12, 16), (15, 13)])
    elif command == "clipboard_paste":
        painter.drawRoundedRect(QRectF(5, 5, 14, 16), 2, 2)
        painter.drawRoundedRect(QRectF(9, 3, 6, 4), 1, 1)
        lines([(9, 12), (15, 12)])
        lines([(9, 16), (13, 16)])
    elif command == "swap":
        lines([(4, 8), (20, 8), (16, 4)])
        lines([(20, 16), (4, 16), (8, 20)])
    elif command == "same_path":
        painter.drawRoundedRect(QRectF(3, 4, 7, 16), 1, 1)
        painter.drawRoundedRect(QRectF(14, 4, 7, 16), 1, 1)
        lines([(7, 12), (17, 12)])
        lines([(14, 9), (17, 12), (14, 15)])
    elif command == "pack":
        lines([(4, 7), (12, 3), (20, 7), (12, 11), (4, 7), (4, 17), (12, 21), (20, 17), (20, 7)])
        lines([(12, 11), (12, 21)])
        lines([(8, 5), (16, 9)])
    elif command == "local":
        painter.drawRoundedRect(QRectF(3, 5, 18, 12), 1, 1)
        lines([(9, 21), (15, 21)])
        lines([(12, 17), (12, 21)])
    elif command == "settings":
        for x, y in ((5, 9), (12, 15), (19, 7)):
            lines([(x, 3), (x, y - 2)])
            lines([(x, y + 2), (x, 21)])
            painter.drawEllipse(QPointF(x, y), 2, 2)
    elif command == "home":
        lines([(3, 11), (12, 3), (21, 11)])
        lines([(6, 9), (6, 21), (10, 21), (10, 15), (14, 15), (14, 21), (18, 21), (18, 9)])
    elif command == "update":
        lines([(12, 3), (12, 15)])
        lines([(7, 10), (12, 15), (17, 10)])
        lines([(4, 16), (4, 21), (20, 21), (20, 16)])
    elif command == "appearance":
        painter.drawEllipse(QRectF(3, 3, 18, 18))
        painter.setBrush(QColor(color))
        path = QPainterPath()
        path.moveTo(12, 3)
        path.arcTo(QRectF(3, 3, 18, 18), 90, -180)
        path.closeSubpath()
        painter.drawPath(path)
    elif command == "devices":
        painter.drawRoundedRect(QRectF(2, 4, 13, 10), 1, 1)
        lines([(5, 17), (12, 17)])
        lines([(8, 14), (8, 17)])
        painter.drawRoundedRect(QRectF(16, 9, 6, 12), 1, 1)
    elif command == "connect":
        painter.drawEllipse(QRectF(3, 3, 18, 18))
        painter.drawEllipse(QRectF(8, 3, 8, 18))
        lines([(3, 12), (21, 12)])
    else:
        # A recognizable fallback for user-added commands; their full names
        # remain available through accessible labels and tooltips.
        painter.drawRoundedRect(QRectF(3, 3, 18, 18), 3, 3)
        painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
        painter.drawText(QRectF(3, 3, 18, 18), Qt.AlignmentFlag.AlignCenter, command.replace("_", " ")[:2].upper())
    painter.end()
    return QIcon(pixmap)
