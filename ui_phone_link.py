"""Spacious desktop pairing workspace for JARVIS Phone Link."""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.phone_link import PhoneLinkError, PhoneLinkService


def _qr_pixmap(value: str, size: int = 252) -> QPixmap:
    import cv2

    encoder = cv2.QRCodeEncoder_create()
    data = encoder.encode(value)
    if data is None:
        raise PhoneLinkError("The QR code could not be generated.")
    height, width = data.shape[:2]
    image = QImage(
        data.data,
        width,
        height,
        int(data.strides[0]),
        QImage.Format.Format_Grayscale8,
    ).copy()
    return QPixmap.fromImage(image).scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )


class PhoneLinkQrDialog(QDialog):
    """Focused, window-modal QR step with no surrounding dashboard noise."""

    paired = pyqtSignal(object)
    pairing_ready = pyqtSignal(object)

    def __init__(
        self,
        service: PhoneLinkService,
        pairing,
        known_device_ids: set[str],
        palette: dict[str, str],
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self._pairing = pairing
        self._known_device_ids = set(known_device_ids)
        self.colors = dict(palette)
        self.setObjectName("phoneQrDialog")
        self.setWindowTitle("Scan to connect iPhone")
        self.setAccessibleName("Phone Link QR pairing")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setFixedSize(432, 548)
        self._build()
        self.refresh_theme(palette)
        self._set_pairing(pairing)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def _button(self, text: str, *, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("primary", primary)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(42)
        button.setMinimumWidth(116)
        button.setFont(QFont("Space Grotesk", 10, QFont.Weight.DemiBold))
        return button

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)
        identity = QVBoxLayout()
        identity.setSpacing(2)
        marker = QLabel("PHONE LINK  /  STEP 02")
        marker.setObjectName("qrMarker")
        marker.setFont(QFont("JetBrains Mono", 8, QFont.Weight.Medium))
        identity.addWidget(marker)
        heading = QLabel("Scan to connect")
        heading.setObjectName("qrHeading")
        heading.setFont(QFont("Space Grotesk", 18, QFont.Weight.DemiBold))
        identity.addWidget(heading)
        header.addLayout(identity)
        header.addStretch(1)
        close = QPushButton("×")
        close.setObjectName("qrClose")
        close.setAccessibleName("Close QR pairing")
        close.setToolTip("Close QR pairing (Esc)")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setFixedSize(40, 40)
        close.setFont(QFont("Space Grotesk", 18, QFont.Weight.Medium))
        close.clicked.connect(self.reject)
        header.addWidget(close)
        root.addLayout(header)

        self._qr = QLabel()
        self._qr.setObjectName("qrCode")
        self._qr.setFixedSize(284, 284)
        self._qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr.setAccessibleName("Single-use Phone Link QR code")
        root.addWidget(self._qr, 0, Qt.AlignmentFlag.AlignHCenter)

        self._instruction = QLabel("Open Camera on your iPhone and scan")
        self._instruction.setObjectName("qrInstruction")
        self._instruction.setFont(QFont("Space Grotesk", 12, QFont.Weight.DemiBold))
        self._instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._instruction)

        self._detail = QLabel("Single-use code  ·  Expires in 2:00")
        self._detail.setObjectName("qrDetail")
        self._detail.setFont(QFont("JetBrains Mono", 8, QFont.Weight.Medium))
        self._detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._detail)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)
        cancel = self._button("CANCEL")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self._refresh = self._button("NEW CODE", primary=True)
        self._refresh.clicked.connect(self._renew)
        self._refresh.hide()
        actions.addWidget(self._refresh)
        actions.addStretch(1)
        root.addLayout(actions)

    def open(self) -> None:
        self._timer.start()
        super().open()
        QTimer.singleShot(0, self._center_on_parent)

    def reject(self) -> None:
        self._timer.stop()
        super().reject()

    def accept(self) -> None:
        self._timer.stop()
        super().accept()

    def _center_on_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        frame = self.frameGeometry()
        frame.moveCenter(parent.window().frameGeometry().center())
        self.move(frame.topLeft())

    def _set_pairing(self, pairing) -> None:
        self._pairing = pairing
        self._qr.setPixmap(_qr_pixmap(pairing.url, 252))
        self._instruction.setText("Open Camera on your iPhone and scan")
        self._detail.setText("Single-use code  ·  Expires in 2:00")
        self._refresh.hide()

    def _renew(self) -> None:
        try:
            pairing = self.service.create_pairing()
            self._set_pairing(pairing)
            self.pairing_ready.emit({"state": "ready", "url": pairing.url})
        except Exception as exc:
            self._instruction.setText("Could not create a new code")
            self._detail.setText(str(exc))

    def _tick(self) -> None:
        devices = self.service.devices()
        ids = {str(item.get("id")) for item in devices}
        new_ids = ids - self._known_device_ids
        if new_ids:
            linked = next(item for item in devices if str(item.get("id")) in new_ids)
            self._known_device_ids = ids
            self.paired.emit(linked)
            self.accept()
            return
        self._known_device_ids = ids
        remaining = max(0, int(self._pairing.expires_at - time.time()))
        self._detail.setText(
            f"Single-use code  ·  Expires in {remaining // 60}:{remaining % 60:02d}"
        )
        if remaining <= 0:
            self._instruction.setText("This code has expired")
            self._detail.setText("Create a fresh code to continue")
            self._refresh.show()

    def refresh_theme(self, palette: dict[str, str]) -> None:
        self.colors = dict(palette)
        c = self.colors
        self.setStyleSheet(f"""
            QDialog#phoneQrDialog {{
                background: {c['PANEL']};
                border: 1px solid {c['BORDER_B']};
                border-radius: 12px;
            }}
            QLabel {{ background: transparent; }}
            QLabel#qrMarker {{ color: {c['TEXT_MED']}; letter-spacing: 2px; }}
            QLabel#qrHeading, QLabel#qrInstruction {{ color: {c['WHITE']}; }}
            QLabel#qrDetail {{ color: {c['TEXT_MED']}; }}
            QLabel#qrCode {{
                background: #f8fcff;
                border: 12px solid #f8fcff;
                border-radius: 8px;
            }}
            QPushButton {{
                background: transparent; color: {c['TEXT_MED']};
                border: 1px solid {c['BORDER']}; border-radius: 6px;
                padding: 0 14px;
            }}
            QPushButton:hover, QPushButton:focus {{
                color: {c['WHITE']}; border-color: {c['PRI']};
                background: {c['PRI_GHO']};
            }}
            QPushButton:focus {{ border: 2px solid {c['PRI']}; }}
            QPushButton:pressed {{ background: {c['DARK']}; }}
            QPushButton[primary="true"] {{
                color: {c['BG']}; background: {c['PRI']}; border-color: {c['PRI']};
            }}
            QPushButton[primary="true"]:hover {{
                color: {c['BG']}; background: {c['ENERGY']};
            }}
            QPushButton#qrClose {{
                color: {c['TEXT_MED']}; border-color: transparent;
                padding: 0; border-radius: 6px;
            }}
            QPushButton#qrClose:hover, QPushButton#qrClose:focus {{
                color: {c['WHITE']}; border-color: {c['BORDER_B']};
            }}
        """)


class PhoneLinkWorkspaceWidget(QWidget):
    close_requested = pyqtSignal()
    pairing_changed = pyqtSignal(object)

    def __init__(self, service: PhoneLinkService, palette: dict[str, str], parent=None):
        super().__init__(parent)
        self.service = service
        self.colors = dict(palette)
        self._pairing = None
        self._qr_dialog: PhoneLinkQrDialog | None = None
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
        self._linked_page = self._build_linked_page()
        self._error_page = self._build_error_page()
        for page in (self._confirm_page, self._linked_page, self._error_page):
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
        self._set_modal_background(False)
        dialog = self._qr_dialog
        self._qr_dialog = None
        if dialog is not None:
            dialog.reject()
            dialog.deleteLater()

    def show_confirmation(self) -> None:
        self._pairing = None
        self._status.setText("PERMISSION REQUIRED")
        self._stack.setCurrentWidget(self._confirm_page)

    def begin_pairing(self) -> None:
        try:
            self._pairing = self.service.create_pairing()
            self._status.setText("WAITING FOR IPHONE")
            self._stack.setCurrentWidget(self._confirm_page)
            self._timer.start()
            previous = self._qr_dialog
            self._qr_dialog = None
            if previous is not None:
                previous.reject()
                previous.deleteLater()
            self._qr_dialog = PhoneLinkQrDialog(
                self.service,
                self._pairing,
                self._known_device_ids,
                self.colors,
                self.window(),
            )
            self._qr_dialog.paired.connect(self._dialog_paired)
            self._qr_dialog.pairing_ready.connect(self.pairing_changed)
            self._qr_dialog.finished.connect(self._dialog_finished)
            self._set_modal_background(True)
            self._qr_dialog.open()
            self.pairing_changed.emit({"state": "ready", "url": self._pairing.url})
        except PhoneLinkError as exc:
            self._set_modal_background(False)
            self._show_error(str(exc))
        except Exception as exc:
            self._set_modal_background(False)
            self._show_error(f"QR generation failed: {exc}")

    def _dialog_paired(self, device: object) -> None:
        linked = device if isinstance(device, dict) else {}
        self._known_device_ids.add(str(linked.get("id") or ""))
        self._show_linked(linked)
        self.pairing_changed.emit({"state": "paired", "device": linked})

    def _dialog_finished(self, _result: int) -> None:
        self._set_modal_background(False)
        dialog = self._qr_dialog
        self._qr_dialog = None
        if dialog is not None:
            dialog.deleteLater()
        if self._stack.currentWidget() is self._confirm_page:
            self._status.setText("PERMISSION REQUIRED")

    def _set_modal_background(self, active: bool) -> None:
        if active:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.34)
            self.setGraphicsEffect(effect)
        else:
            self.setGraphicsEffect(None)

    def _tick(self) -> None:
        devices = self.service.devices()
        ids = {str(item.get("id")) for item in devices}
        new_ids = ids - self._known_device_ids
        if new_ids:
            if self._qr_dialog is not None:
                self._known_device_ids = ids
                return
            linked = next(item for item in devices if str(item.get("id")) in new_ids)
            self._known_device_ids = ids
            self._show_linked(linked)
            self.pairing_changed.emit({"state": "paired", "device": linked})
            return
        self._known_device_ids = ids

    def _show_linked(self, device: dict) -> None:
        self._pairing = None
        name = str(device.get("name") or "iPhone")
        self._device_title.setText(f"{name} remembered")
        self._device_detail.setText(
            "Launch JARVIS from the iPhone Home Screen whenever this Mac is running—no "
            "new QR needed. If you did not save it yet, use Safari’s Share button and "
            "choose Add to Home Screen."
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
        if self._qr_dialog is not None:
            self._qr_dialog.refresh_theme(palette)
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
            QFrame#phoneCard {{ background: {c['PANEL']}; border: 1px solid {c['BORDER_B']}; border-radius: 12px; }}
            QPushButton {{ background: transparent; color: {c['TEXT_MED']}; border: 1px solid {c['BORDER']}; border-radius: 6px; padding: 0 14px; }}
            QPushButton:hover, QPushButton:focus {{ color: {c['WHITE']}; border-color: {c['PRI']}; background: {c['PRI_GHO']}; }}
            QPushButton[primary="true"] {{ color: {c['BG']}; background: {c['PRI']}; border-color: {c['PRI']}; }}
            QPushButton[primary="true"]:hover {{ color: {c['BG']}; background: {c['ENERGY']}; }}
        """)
