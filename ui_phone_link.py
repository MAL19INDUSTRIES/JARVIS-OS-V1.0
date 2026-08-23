"""Spacious desktop pairing workspace for JARVIS Phone Link."""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.phone_link import PhoneLinkError, PhoneLinkService


class PhoneLinkWorkspaceWidget(QWidget):
    close_requested = pyqtSignal()
    pairing_changed = pyqtSignal(object)

    def __init__(self, service: PhoneLinkService, palette: dict[str, str], parent=None):
        super().__init__(parent)
        self.service = service
        self.colors = dict(palette)
        self._pairing = None
        self._known_device_ids: set[str] = set()
        self._build()
        self.refresh_theme(palette)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def _button(self, text: str, *, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("primary", primary)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(42)
        button.setMinimumWidth(132)
        button.setFont(QFont("Space Grotesk", 10, QFont.Weight.DemiBold))
        return button

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 30)
        root.setSpacing(0)

        header = QHBoxLayout()
        header.setSpacing(12)
        identity = QVBoxLayout()
        identity.setSpacing(3)
        eyebrow = QLabel("PHONE LINK  /  LOCAL ACCESS")
        eyebrow.setObjectName("phoneEyebrow")
        eyebrow.setFont(QFont("JetBrains Mono", 8, QFont.Weight.Medium))
        title = QLabel("Connect your iPhone")
        title.setObjectName("phoneTitle")
        title.setFont(QFont("Space Grotesk", 20, QFont.Weight.DemiBold))
        identity.addWidget(eyebrow)
        identity.addWidget(title)
        header.addLayout(identity)
        header.addStretch(1)
        self._status = QLabel("NOT LINKED")
        self._status.setObjectName("phoneStatus")
        self._status.setFont(QFont("JetBrains Mono", 8, QFont.Weight.Medium))
        header.addWidget(self._status)
        self._close = self._button("CLOSE")
        self._close.setMinimumWidth(82)
        self._close.clicked.connect(self.close_requested)
        header.addWidget(self._close)
        root.addLayout(header)

        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._confirm_page = self._build_confirm_page()
        self._pair_page = self._build_pair_page()
        self._linked_page = self._build_linked_page()
        self._error_page = self._build_error_page()
        for page in (self._confirm_page, self._pair_page, self._linked_page, self._error_page):
            self._stack.addWidget(page)
        root.addWidget(self._stack, 1)

        footer = QLabel(
            "Same trusted Wi-Fi only  ·  Single-use QR  ·  Phone actions require your tap"
        )
        footer.setObjectName("phoneFootnote")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setFont(QFont("JetBrains Mono", 7, QFont.Weight.Medium))
        root.addWidget(footer)

    def _center_card(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page_lay = QVBoxLayout(page)
        page_lay.setContentsMargins(0, 28, 0, 28)
        page_lay.addStretch(1)
        card = QFrame(page)
        card.setObjectName("phoneCard")
        card.setMaximumWidth(560)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(42, 36, 42, 36)
        lay.setSpacing(18)
        page_lay.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        page_lay.addStretch(1)
        return page, lay

    def _build_confirm_page(self) -> QWidget:
        page, lay = self._center_card()
        marker = QLabel("01  /  PERMISSION")
        marker.setObjectName("phoneMarker")
        marker.setFont(QFont("JetBrains Mono", 8, QFont.Weight.Medium))
        marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(marker)
        question = QLabel("You want me to access your phone?")
        question.setObjectName("phoneQuestion")
        question.setFont(QFont("Space Grotesk", 24, QFont.Weight.DemiBold))
        question.setWordWrap(True)
        question.setMinimumHeight(72)
        question.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(question)
        explainer = QLabel(
            "JARVIS will create a temporary QR code. Scan it once to remember this iPhone."
        )
        explainer.setObjectName("phoneBody")
        explainer.setFont(QFont("Space Grotesk", 11))
        explainer.setWordWrap(True)
        explainer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(explainer)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)
        cancel = self._button("NOT NOW")
        cancel.clicked.connect(self.close_requested)
        actions.addWidget(cancel)
        allow = self._button("ALLOW + CREATE QR", primary=True)
        allow.setMinimumWidth(184)
        allow.clicked.connect(self.begin_pairing)
        actions.addWidget(allow)
        actions.addStretch(1)
        lay.addLayout(actions)
        return page

    def _build_pair_page(self) -> QWidget:
        page, lay = self._center_card()
        marker = QLabel("02  /  SCAN ON IPHONE")
        marker.setObjectName("phoneMarker")
        marker.setFont(QFont("JetBrains Mono", 8, QFont.Weight.Medium))
        marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(marker)
        self._qr = QLabel()
        self._qr.setObjectName("phoneQr")
        self._qr.setFixedSize(252, 252)
        self._qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr.setAccessibleName("Phone Link pairing QR code")
        lay.addWidget(self._qr, 0, Qt.AlignmentFlag.AlignHCenter)
        self._pair_title = QLabel("Open Camera and scan")
        self._pair_title.setObjectName("phoneQuestion")
        self._pair_title.setFont(QFont("Space Grotesk", 20, QFont.Weight.DemiBold))
        self._pair_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._pair_title)
        self._pair_detail = QLabel("This code expires in 2:00")
        self._pair_detail.setObjectName("phoneBody")
        self._pair_detail.setFont(QFont("JetBrains Mono", 8, QFont.Weight.Medium))
        self._pair_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._pair_detail)
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = self._button("CANCEL")
        cancel.clicked.connect(self.show_confirmation)
        actions.addWidget(cancel)
        self._refresh = self._button("NEW CODE", primary=True)
        self._refresh.clicked.connect(self.begin_pairing)
        actions.addWidget(self._refresh)
        actions.addStretch(1)
        lay.addLayout(actions)
        return page

    def _build_linked_page(self) -> QWidget:
        page, lay = self._center_card()
        marker = QLabel("LINK ACTIVE")
        marker.setObjectName("phoneSuccess")
        marker.setFont(QFont("JetBrains Mono", 8, QFont.Weight.Medium))
        marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(marker)
        self._device_title = QLabel("iPhone remembered")
        self._device_title.setObjectName("phoneQuestion")
        self._device_title.setFont(QFont("Space Grotesk", 24, QFont.Weight.DemiBold))
        self._device_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._device_title)
        self._device_detail = QLabel(
            "Open the saved Phone Link page on this Wi-Fi whenever JARVIS is running."
        )
        self._device_detail.setObjectName("phoneBody")
        self._device_detail.setFont(QFont("Space Grotesk", 11))
        self._device_detail.setWordWrap(True)
        self._device_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._device_detail)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self._revoke = self._button("REVOKE IPHONE")
        self._revoke.clicked.connect(self._revoke_current)
        actions.addWidget(self._revoke)
        another = self._button("LINK ANOTHER", primary=True)
        another.clicked.connect(self.show_confirmation)
        actions.addWidget(another)
        actions.addStretch(1)
        lay.addLayout(actions)
        return page

    def _build_error_page(self) -> QWidget:
        page, lay = self._center_card()
        marker = QLabel("PHONE LINK UNAVAILABLE")
        marker.setObjectName("phoneError")
        marker.setFont(QFont("JetBrains Mono", 8, QFont.Weight.Medium))
        marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(marker)
        self._error = QLabel("JARVIS could not start Phone Link.")
        self._error.setObjectName("phoneQuestion")
        self._error.setFont(QFont("Space Grotesk", 19, QFont.Weight.DemiBold))
        self._error.setWordWrap(True)
        self._error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._error)
        retry = self._button("TRY AGAIN", primary=True)
        retry.clicked.connect(self.begin_pairing)
        lay.addWidget(retry, 0, Qt.AlignmentFlag.AlignHCenter)
        return page

    def open_workspace(self) -> None:
        devices = self.service.devices()
        self._known_device_ids = {str(item.get("id")) for item in devices}
        if devices:
            self._show_linked(devices[-1])
        else:
            self.show_confirmation()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def show_confirmation(self) -> None:
        self._pairing = None
        self._status.setText("PERMISSION REQUIRED")
        self._stack.setCurrentWidget(self._confirm_page)

    def begin_pairing(self) -> None:
        try:
            self._pairing = self.service.create_pairing()
            self._qr.setPixmap(self._qr_pixmap(self._pairing.url))
            self._status.setText("WAITING FOR IPHONE")
            self._stack.setCurrentWidget(self._pair_page)
            self._refresh.setVisible(False)
            self._timer.start()
            self.pairing_changed.emit({"state": "ready", "url": self._pairing.url})
        except PhoneLinkError as exc:
            self._show_error(str(exc))
        except Exception as exc:
            self._show_error(f"QR generation failed: {exc}")

    def _qr_pixmap(self, value: str) -> QPixmap:
        import cv2

        encoder = cv2.QRCodeEncoder_create()
        data = encoder.encode(value)
        if data is None:
            raise PhoneLinkError("The QR code could not be generated.")
        height, width = data.shape[:2]
        image = QImage(data.data, width, height, int(data.strides[0]), QImage.Format.Format_Grayscale8).copy()
        return QPixmap.fromImage(image).scaled(
            228,
            228,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

    def _tick(self) -> None:
        devices = self.service.devices()
        ids = {str(item.get("id")) for item in devices}
        new_ids = ids - self._known_device_ids
        if new_ids:
            linked = next(item for item in devices if str(item.get("id")) in new_ids)
            self._known_device_ids = ids
            self._show_linked(linked)
            self.pairing_changed.emit({"state": "paired", "device": linked})
            return
        self._known_device_ids = ids
        if self._pairing and self._stack.currentWidget() is self._pair_page:
            remaining = max(0, int(self._pairing.expires_at - time.time()))
            self._pair_detail.setText(f"This code expires in {remaining // 60}:{remaining % 60:02d}")
            if remaining <= 0:
                self._pair_title.setText("This QR code expired")
                self._pair_detail.setText("Create a fresh single-use code to continue")
                self._refresh.setVisible(True)
                self._status.setText("CODE EXPIRED")

    def _show_linked(self, device: dict) -> None:
        self._pairing = None
        name = str(device.get("name") or "iPhone")
        self._device_title.setText(f"{name} remembered")
        self._device_detail.setText(
            "Open the saved Phone Link page on this Wi-Fi whenever JARVIS is running. "
            "iOS pauses the web connection when the phone is locked."
        )
        self._revoke.setProperty("device_id", str(device.get("id") or ""))
        self._status.setText("IPHONE LINKED")
        self._stack.setCurrentWidget(self._linked_page)

    def _revoke_current(self) -> None:
        device_id = str(self._revoke.property("device_id") or "")
        if device_id and self.service.revoke_device(device_id):
            self._known_device_ids.discard(device_id)
        devices = self.service.devices()
        if devices:
            self._show_linked(devices[-1])
        else:
            self.show_confirmation()
        self.pairing_changed.emit({"state": "revoked", "device_id": device_id})

    def _show_error(self, message: str) -> None:
        self._error.setText(str(message))
        self._status.setText("UNAVAILABLE")
        self._stack.setCurrentWidget(self._error_page)

    def refresh_theme(self, palette: dict[str, str]) -> None:
        self.colors = dict(palette)
        c = self.colors
        self.setStyleSheet(f"""
            QWidget {{ background: {c['BG']}; color: {c['WHITE']}; }}
            QLabel {{ background: transparent; }}
            QLabel#phoneEyebrow, QLabel#phoneMarker {{ color: {c['TEXT_MED']}; letter-spacing: 2px; }}
            QLabel#phoneTitle, QLabel#phoneQuestion {{ color: {c['WHITE']}; }}
            QLabel#phoneStatus {{ color: {c['PRI']}; border: 1px solid {c['BORDER_B']}; border-radius: 11px; padding: 6px 10px; letter-spacing: 1px; }}
            QLabel#phoneBody, QLabel#phoneFootnote {{ color: {c['TEXT_MED']}; }}
            QLabel#phoneSuccess {{ color: {c['GREEN']}; letter-spacing: 2px; }}
            QLabel#phoneError {{ color: {c['RED']}; letter-spacing: 2px; }}
            QLabel#phoneQr {{ background: #ffffff; border: 12px solid #ffffff; border-radius: 8px; }}
            QFrame#phoneCard {{ background: {c['PANEL']}; border: 1px solid {c['BORDER_B']}; border-radius: 12px; }}
            QPushButton {{ background: transparent; color: {c['TEXT_MED']}; border: 1px solid {c['BORDER']}; border-radius: 6px; padding: 0 14px; }}
            QPushButton:hover, QPushButton:focus {{ color: {c['WHITE']}; border-color: {c['PRI']}; background: {c['PRI_GHO']}; }}
            QPushButton[primary="true"] {{ color: {c['BG']}; background: {c['PRI']}; border-color: {c['PRI']}; }}
            QPushButton[primary="true"]:hover {{ color: {c['BG']}; background: {c['ENERGY']}; }}
        """)
