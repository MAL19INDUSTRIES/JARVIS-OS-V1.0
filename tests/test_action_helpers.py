import tempfile
import unittest
import base64
import asyncio
import json
from email import message_from_bytes
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image

from actions import (
    browser_control,
    email_control,
    file_controller,
    file_processor,
    instagram_browser,
    jarvis_file_stamp,
    media_control,
    open_app,
    reminder,
    screen_processor,
    send_message,
    web_search,
)


class ActionHelperTests(unittest.TestCase):
    def test_browser_url_normalization_defaults_to_https(self):
        self.assertEqual(browser_control._normalize_url("example.com"), "https://example.com")
        self.assertEqual(browser_control._normalize_url("http://localhost:8000"), "http://localhost:8000")

    def test_open_app_normalization_removes_polite_noise(self):
        self.assertEqual(open_app._normalize("Please open Google Chrome"), "Google Chrome")

    def test_successful_macos_direct_launch_has_no_artificial_post_wait(self):
        completed = MagicMock(returncode=0)
        with (
            patch.object(open_app.subprocess, "run", return_value=completed),
            patch.object(open_app.time, "sleep") as sleep,
        ):
            self.assertTrue(open_app._launch_macos("Safari"))
        sleep.assert_not_called()

    def test_reminder_sanitization_removes_shell_sensitive_characters(self):
        self.assertEqual(reminder._sanitise("hello\n'world'\\"), "hello world")

    def test_screen_compression_returns_valid_image(self):
        source = BytesIO()
        Image.new("RGB", (40, 20), "blue").save(source, format="PNG")
        data, mime = screen_processor._compress(source.getvalue(), "PNG")
        self.assertTrue(data)
        self.assertIn(mime, {"image/png", "image/jpeg"})

    def test_screen_capture_avoids_png_encode_decode_round_trip(self):
        shot = SimpleNamespace(size=(2, 1), rgb=b"\x00\x00\x00\xff\xff\xff")
        capture = MagicMock()
        capture.monitors = [{}, {"width": 2, "height": 1}]
        capture.grab.return_value = shot
        context = MagicMock()
        context.__enter__.return_value = capture
        context.__exit__.return_value = False

        with patch.object(screen_processor.mss, "mss", return_value=context), \
             patch.object(screen_processor.mss.tools, "to_png") as to_png:
            data, mime = screen_processor._capture_screen()

        self.assertTrue(data)
        self.assertEqual(mime, "image/jpeg")
        to_png.assert_not_called()

    def test_direct_vision_client_is_reused(self):
        client = MagicMock()
        with patch.object(screen_processor, "_direct_client", None), \
             patch.object(screen_processor, "_direct_client_key", ""), \
             patch.object(screen_processor, "_get_api_key", return_value="test-key"), \
             patch.object(screen_processor.genai, "Client", return_value=client) as factory:
            self.assertIs(screen_processor._get_direct_client(), client)
            self.assertIs(screen_processor._get_direct_client(), client)

        factory.assert_called_once_with(api_key="test-key")

    def test_screen_analysis_hands_finished_result_to_speech(self):
        player = MagicMock()
        speak = MagicMock(return_value=True)
        with patch.object(screen_processor, "_last_capture_time", 0.0), \
             patch.object(screen_processor, "_capture_screen", return_value=(b"image", "image/jpeg")), \
             patch.object(screen_processor, "_direct_vision_answer", return_value="The settings panel is open."):
            result = screen_processor.screen_process(
                {"angle": "screen", "text": "What do you see?"},
                player=player,
                speak=speak,
            )
        self.assertEqual(result, "The settings panel is open.")
        speak.assert_called_once_with("The settings panel is open.")
        player.show_vision_preview.assert_called_once_with("screen", b"image", "image/jpeg")
        player.hide_vision_preview.assert_called_once()
        self.assertGreaterEqual(player.hide_vision_preview.call_args.args[0], 2200)
        player.write_log.assert_not_called()

    def test_screen_capture_failure_is_spoken(self):
        speak = MagicMock(return_value=True)
        with patch.object(screen_processor, "_last_capture_time", 0.0), \
             patch.object(screen_processor, "_capture_screen", side_effect=RuntimeError("permission denied")):
            result = screen_processor.screen_process(
                {"angle": "screen", "text": "What do you see?"},
                speak=speak,
            )
        self.assertIn("permission denied", result)
        speak.assert_called_once_with(result)

    def test_file_type_detection_uses_content_extension_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            path.write_text("name,value\na,1\n", encoding="utf-8")
            self.assertEqual(file_processor._detect_type(path), "csv")

    def test_file_controller_opens_file_with_default_macos_app(self):
        completed = MagicMock(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.pdf"
            target.write_bytes(b"pdf")
            with (
                patch.object(file_controller, "_OS", "Darwin"),
                patch.object(file_controller, "_is_safe_path", return_value=True),
                patch.object(file_controller.subprocess, "run", return_value=completed) as run,
            ):
                result = file_controller.file_controller({"action": "open", "path": str(target)})
        self.assertEqual(result, "Opened file: report.pdf")
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["open", str(target)])

    def test_email_prepare_requires_separate_approval(self):
        email_control._clear_pending_email()
        with (
            patch.object(email_control, "_run_osascript") as script,
            patch.object(email_control, "_gmail_web_prepare", return_value="GMAIL_WEB_DRAFT_READY") as compose,
        ):
            result = email_control.email_control({
                "action": "prepare",
                "to": "Alex <alex@example.com>",
                "subject": "Project update",
                "body": "The presentation is ready.",
            })
        self.assertTrue(result.startswith("EMAIL_APPROVAL_REQUIRED|"))
        pending = email_control._get_pending_email()
        self.assertEqual(pending["to"], "alex@example.com")
        self.assertEqual(pending["delivery"], "gmail_web")
        self.assertIn("visibly typed", result)
        compose.assert_called_once()
        script.assert_not_called()

    def test_gmail_prepare_failure_does_not_create_pending_email(self):
        email_control._clear_pending_email()
        with patch.object(
            email_control,
            "_gmail_web_prepare",
            return_value="Gmail requires a browser sign-in. Sign in, then ask me to prepare the email again.",
        ):
            result = email_control.email_control({
                "action": "prepare",
                "to": "alex@example.com",
                "subject": "Project update",
                "body": "The presentation is ready.",
            })
        self.assertIn("requires a browser sign-in", result)
        self.assertEqual(email_control._get_pending_email(), {})

    def test_visible_gmail_approval_uses_browser_send_not_gmail_api(self):
        draft = {
            "to": "alex@example.com",
            "cc": "",
            "bcc": "",
            "subject": "Project update",
            "body": "The presentation is ready.",
            "provider": "gmail",
            "browser": "chrome",
            "delivery": "gmail_web",
        }
        email_control._set_pending_email(draft)
        with (
            patch.object(email_control, "_gmail_web_send", return_value="Email sent through the visible Gmail compose window to alex@example.com.") as web_send,
            patch.object(email_control, "_send_gmail") as api_send,
        ):
            result = email_control.email_control({"action": "approve", "provider": "gmail"})
        self.assertIn("visible Gmail compose window", result)
        web_send.assert_called_once_with(draft)
        api_send.assert_not_called()

    def test_cancel_visible_gmail_draft_discards_compose_window(self):
        draft = {
            "to": "alex@example.com",
            "cc": "",
            "bcc": "",
            "subject": "Project update",
            "body": "The presentation is ready.",
            "provider": "gmail",
            "browser": "chrome",
            "delivery": "gmail_web",
        }
        email_control._set_pending_email(draft)
        with patch.object(email_control, "_gmail_web_cancel", return_value=True) as discard:
            result = email_control.email_control({"action": "cancel"})
        self.assertIn("visible Gmail draft was discarded", result)
        discard.assert_called_once_with(draft)
        self.assertEqual(email_control._get_pending_email(), {})

    def test_visible_gmail_typing_uses_fast_default_delay(self):
        locator = MagicMock()
        locator.click = AsyncMock()
        locator.fill = AsyncMock()
        locator.press_sequentially = AsyncMock()
        asyncio.run(email_control._type_visible(locator, "Fast typing"))
        locator.press_sequentially.assert_awaited_once_with("Fast typing", delay=3)

    def test_visible_gmail_compose_recovers_once_after_interruption(self):
        with (
            patch.object(
                email_control,
                "_gmail_web_prepare_once",
                new=AsyncMock(side_effect=[RuntimeError("stale field"), "GMAIL_WEB_DRAFT_READY"]),
            ) as prepare_once,
            patch.object(
                email_control,
                "_gmail_web_cancel_async",
                new=AsyncMock(return_value=True),
            ) as discard,
        ):
            result = asyncio.run(email_control._gmail_web_prepare_async(
                object(),
                {"to": "alex@example.com", "subject": "Status", "body": "Ready."},
            ))
        self.assertEqual(result, "GMAIL_WEB_DRAFT_READY")
        self.assertEqual(prepare_once.await_count, 2)
        discard.assert_awaited_once()

    def test_gmail_sign_in_prefills_connected_account_without_password_access(self):
        hidden = MagicMock()
        hidden.count = AsyncMock(return_value=0)
        account_tile = MagicMock()
        account_tile.count = AsyncMock(return_value=1)
        account_tile.first.is_visible = AsyncMock(return_value=True)
        account_tile.first.click = AsyncMock()
        email_field = MagicMock()
        email_field.fill = AsyncMock()
        next_button = MagicMock()
        next_button.click = AsyncMock()
        page = MagicMock()
        page.url = "https://mail.google.com/mail/u/0/#inbox"
        page.get_by_role.return_value = hidden
        page.get_by_text.side_effect = lambda text, **_kwargs: (
            account_tile if text == "operator@gmail.com" else hidden
        )
        with (
            patch.object(email_control, "_gmail_account", return_value="operator@gmail.com"),
            patch.object(
                email_control,
                "_first_visible",
                new=AsyncMock(side_effect=[email_field, next_button]),
            ),
        ):
            signed_in = asyncio.run(email_control._assist_gmail_sign_in(page, timeout_seconds=0.1))
        self.assertTrue(signed_in)
        email_field.fill.assert_awaited_once_with("operator@gmail.com")
        next_button.click.assert_awaited_once()

    def test_email_approval_sends_exact_pending_draft_on_macos(self):
        email_control._set_pending_email({
            "to": "alex@example.com",
            "cc": "",
            "bcc": "",
            "subject": "Project update",
            "body": "The presentation is ready.",
            "provider": "apple_mail",
        })
        completed = MagicMock(returncode=0, stdout="SENT\n", stderr="")
        with (
            patch.object(email_control, "_SYSTEM", "Darwin"),
            patch.object(email_control, "_run_osascript", return_value=completed) as script,
        ):
            result = email_control.email_control({"action": "approve", "provider": "apple_mail"})
        self.assertEqual(result, "Email sent to alex@example.com.")
        self.assertEqual(email_control._get_pending_email(), {})
        self.assertEqual(script.call_args.args[1:], (
            "alex@example.com", "", "", "Project update", "The presentation is ready."
        ))

    def test_email_inbox_formats_message_ids_without_body_content(self):
        raw = (
            "message-1" + email_control._FIELD_SEPARATOR
            + "Alex <alex@example.com>" + email_control._FIELD_SEPARATOR
            + "Status" + email_control._FIELD_SEPARATOR
            + "Thursday, August 6, 2026" + email_control._FIELD_SEPARATOR
            + "false" + email_control._RECORD_SEPARATOR
        )
        completed = MagicMock(returncode=0, stdout=raw, stderr="")
        with (
            patch.object(email_control, "_SYSTEM", "Darwin"),
            patch.object(email_control, "_run_osascript", return_value=completed),
        ):
            result = email_control.email_control({"action": "inbox", "limit": 5, "provider": "apple_mail"})
        self.assertIn("[UNREAD] Status", result)
        self.assertIn("Message ID: message-1", result)
        self.assertNotIn("email body", result.lower())

    def test_gmail_inbox_uses_real_gmail_query_and_metadata(self):
        service = MagicMock()
        messages = service.users.return_value.messages.return_value
        messages.list.return_value.execute.return_value = {"messages": [{"id": "gmail-1"}]}
        messages.get.return_value.execute.return_value = {
            "id": "gmail-1",
            "labelIds": ["INBOX", "UNREAD"],
            "payload": {"headers": [
                {"name": "From", "value": "Alex <alex@example.com>"},
                {"name": "Subject", "value": "Status update"},
                {"name": "Date", "value": "Thu, 6 Aug 2026 10:00:00 -0700"},
            ]},
        }
        with patch.object(email_control, "_gmail_service", return_value=service):
            result = email_control.email_control({"action": "unread", "provider": "gmail", "limit": 5})
        self.assertIn("Unread Gmail inbox", result)
        self.assertIn("Status update", result)
        messages.list.assert_called_once_with(
            userId="me", q="in:inbox is:unread", maxResults=5, includeSpamTrash=False
        )

    def test_gmail_read_extracts_plain_text_without_marking_message_read(self):
        service = MagicMock()
        messages = service.users.return_value.messages.return_value
        encoded = base64.urlsafe_b64encode(b"This is the Gmail body.").decode("ascii")
        messages.get.return_value.execute.return_value = {
            "id": "gmail-2",
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "From", "value": "Alex <alex@example.com>"},
                    {"name": "To", "value": "operator@gmail.com"},
                    {"name": "Subject", "value": "Hello"},
                    {"name": "Date", "value": "Thu, 6 Aug 2026 10:00:00 -0700"},
                ],
                "body": {"data": encoded},
            },
        }
        with patch.object(email_control, "_gmail_service", return_value=service):
            result = email_control.email_control({
                "action": "read", "provider": "gmail", "message_id": "gmail-2"
            })
        self.assertIn("This is the Gmail body.", result)
        messages.get.assert_called_once_with(userId="me", id="gmail-2", format="full")

    def test_gmail_approval_sends_rfc_message_and_clears_pending_draft(self):
        email_control._set_pending_email({
            "to": "alex@example.com",
            "cc": "team@example.com",
            "bcc": "",
            "subject": "Project update",
            "body": "The presentation is ready.",
            "provider": "gmail",
        })
        service = MagicMock()
        send = service.users.return_value.messages.return_value.send
        send.return_value.execute.return_value = {"id": "sent-1"}
        with patch.object(email_control, "_gmail_service", return_value=service):
            result = email_control.email_control({"action": "approve", "provider": "gmail"})
        self.assertEqual(result, "Email sent through Gmail to alex@example.com.")
        self.assertEqual(email_control._get_pending_email(), {})
        raw = send.call_args.kwargs["body"]["raw"]
        decoded = base64.urlsafe_b64decode(raw.encode("ascii"))
        message = message_from_bytes(decoded)
        self.assertEqual(message["To"], "alex@example.com")
        self.assertEqual(message["Cc"], "team@example.com")
        self.assertEqual(message["Subject"], "Project update")

    def test_gmail_connect_stores_refresh_credentials_in_secret_store(self):
        class MemoryStore:
            def __init__(self):
                self.values = {}
            def set(self, key, value):
                self.values[key] = value
            def get(self, key):
                return self.values.get(key)
            def delete(self, key):
                self.values.pop(key, None)

        with tempfile.TemporaryDirectory() as directory:
            client_path = Path(directory) / "client_secret_test.json"
            client_path.write_text(json.dumps({"installed": {
                "client_id": "client-id.apps.googleusercontent.com",
                "client_secret": "desktop-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }}), encoding="utf-8")
            credentials = MagicMock()
            credentials.to_json.return_value = json.dumps({
                "token": "access", "refresh_token": "refresh", "client_id": "client-id",
                "client_secret": "desktop-secret", "token_uri": "https://oauth2.googleapis.com/token",
                "scopes": list(email_control.GMAIL_SCOPES),
            })
            flow = MagicMock()
            flow.run_local_server.return_value = credentials
            flow_class = MagicMock()
            flow_class.from_client_secrets_file.return_value = flow
            service = MagicMock()
            service.users.return_value.getProfile.return_value.execute.return_value = {
                "emailAddress": "operator@gmail.com"
            }
            store = MemoryStore()
            with (
                patch.object(email_control, "_gmail_dependencies", return_value=(MagicMock(), MagicMock(), flow_class, MagicMock(return_value=service))),
                patch.object(email_control, "_secret_store", return_value=store),
            ):
                result = email_control.email_control({
                    "action": "connect", "provider": "gmail", "credentials_path": str(client_path)
                })
        self.assertIn("Gmail connected: operator@gmail.com", result)
        self.assertIn(email_control._GMAIL_TOKEN_KEY, store.values)
        flow.run_local_server.assert_called_once()

    def test_file_controller_does_not_open_missing_file(self):
        with (
            patch.object(file_controller, "_is_safe_path", return_value=True),
            patch.object(file_controller.subprocess, "run") as run,
        ):
            result = file_controller.file_controller({"action": "open", "path": "/missing/jarvis-file.txt"})
        self.assertIn("Not found", result)
        run.assert_not_called()

    def test_spotify_stop_pauses_and_rewinds_on_macos(self):
        completed = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch.object(media_control, "_SYSTEM", "Darwin"),
            patch.object(media_control, "_run_osascript", return_value=completed) as script,
        ):
            result = media_control.media_control({"action": "stop", "platform": "spotify"})
        self.assertEqual(result, "Spotify stopped.")
        apple_script = script.call_args.args[0]
        self.assertIn("pause", apple_script)
        self.assertIn("player position to 0", apple_script)

    def test_spotify_plain_query_opens_search_without_false_playback_claim(self):
        with (
            patch.object(media_control, "_SYSTEM", "Darwin"),
            patch.object(media_control, "_open_uri", return_value=(True, "")) as open_uri,
        ):
            result = media_control.media_control({
                "action": "play",
                "platform": "spotify",
                "query": "Daft Punk One More Time",
            })
        self.assertIn("Select a result", result)
        open_uri.assert_called_once_with("spotify:search:Daft%20Punk%20One%20More%20Time")

    def test_spotify_link_is_played_directly_on_macos(self):
        completed = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch.object(media_control, "_SYSTEM", "Darwin"),
            patch.object(media_control, "_run_osascript", return_value=completed) as script,
        ):
            result = media_control.media_control({
                "action": "play_query",
                "platform": "spotify",
                "query": "https://open.spotify.com/track/123456?si=test",
            })
        self.assertIn("Playing", result)
        self.assertEqual(script.call_args.args[1], "spotify:track:123456")

    def test_web_search_formatter_handles_empty_results(self):
        result = web_search._format_ddg("missing query", [])
        self.assertIn("No", result)

    def test_outgoing_message_normalization_adds_terminal_punctuation(self):
        normalized = send_message.normalize_outgoing_message_text("hello there")
        self.assertTrue(normalized.endswith("."))

    def test_short_platform_alias_does_not_capture_signal(self):
        self.assertIs(send_message._resolve_platform("Signal"), send_message._send_signal)
        self.assertIs(send_message._resolve_platform("IG"), send_message._send_instagram)
        self.assertIs(
            send_message._resolve_platform("send on Instagram"),
            send_message._send_instagram,
        )

    def test_instagram_approval_rejects_a_changed_chat(self):
        controller = instagram_browser._InstagramBrowser()
        controller._pending = {
            "recipient": "Alex",
            "message": "Hello there.",
            "url": "https://www.instagram.com/direct/t/original/",
        }
        page = SimpleNamespace(url="https://www.instagram.com/direct/t/different/")
        with (
            patch.object(controller, "_open_inbox", return_value=page),
            patch.object(controller, "_login_required", return_value=False),
            patch.object(controller, "_dismiss_interruptions"),
            patch.object(controller, "_send_composer") as send,
        ):
            result = controller._send_draft()
        self.assertIn("chat changed", result)
        send.assert_not_called()

    def test_instagram_approval_rejects_an_edited_draft(self):
        controller = instagram_browser._InstagramBrowser()
        controller._pending = {
            "recipient": "Alex",
            "message": "Hello there.",
            "url": "https://www.instagram.com/direct/t/original/",
        }
        page = SimpleNamespace(url="https://www.instagram.com/direct/t/original/")
        with (
            patch.object(controller, "_open_inbox", return_value=page),
            patch.object(controller, "_login_required", return_value=False),
            patch.object(controller, "_dismiss_interruptions"),
            patch.object(controller, "_composer_text", return_value="Edited text"),
            patch.object(controller, "_send_composer") as send,
        ):
            result = controller._send_draft()
        self.assertIn("no longer matches", result)
        send.assert_not_called()

    def test_reply_draft_requires_approval_before_send(self):
        send_message._clear_pending_message()
        prepared = send_message.prepare_message_reply({
            "action": "prepare",
            "platform": "iMessage",
            "receiver": "Alex",
            "message_text": "I will call you later",
        })
        self.assertTrue(prepared.startswith("MESSAGE_APPROVAL_REQUIRED|"))
        with patch.object(send_message, "send_message", return_value="Message sent to Alex via iMessage.") as direct_send:
            result = send_message.prepare_message_reply({"action": "approve"})
        self.assertIn("Message sent", result)
        direct_send.assert_called_once()
        self.assertEqual(send_message._get_pending_message(), {})

    def test_instagram_send_prepares_then_approves_visible_draft(self):
        send_message._clear_pending_message()
        with patch.object(
            send_message,
            "_resolve_platform",
            return_value=lambda _receiver, _message: "Draft typed in the open Instagram chat. Awaiting your approval to send.",
        ):
            prepared = send_message.send_message({
                "action": "send",
                "platform": "Instagram",
                "receiver": "Alex",
                "message_text": "Hello there",
            })
        self.assertIn("Awaiting your approval", prepared)
        self.assertEqual(send_message._get_pending_message()["receiver"], "Alex")

        with patch.object(send_message, "send_open_browser_draft", return_value="Message sent to Alex via Instagram.") as approve:
            result = send_message.send_message({"action": "approve", "platform": "Instagram"})
        self.assertIn("Message sent", result)
        approve.assert_called_once()
        self.assertEqual(send_message._get_pending_message(), {})

    def test_pending_message_can_be_cancelled_without_sending(self):
        send_message._set_pending_message("iMessage", "Alex", "Not yet")
        result = send_message.prepare_message_reply({"action": "cancel"})
        self.assertEqual(result, "Pending message cancelled.")
        self.assertEqual(send_message._get_pending_message(), {})

    def test_file_stamp_is_idempotent(self):
        target = Path("sample.py")
        once = jarvis_file_stamp.stamp_text_content("print('ok')\n", target, "QA")
        twice = jarvis_file_stamp.stamp_text_content(once, target, "QA")
        self.assertEqual(once, twice)

    def test_sidecar_metadata_contains_no_secret_value(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "binary.bin"
            target.write_bytes(b"data")
            sidecar = jarvis_file_stamp.write_sidecar_metadata(target, "QA artifact")
            text = sidecar.read_text(encoding="utf-8")
            self.assertIn("JARVIS FILE PROVENANCE", text)
            self.assertNotIn("GEMINI_API_KEY", text)


if __name__ == "__main__":
    unittest.main()
