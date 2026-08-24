import asyncio
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from api.database import SessionLocal, init_db
from api.models import (
    AnswerCacheEntry,
    ChatMessage,
    MemoryEntry,
    TaskRecord,
    User,
    UserConfig,
    UserSecret,
)
from api.security import create_access_token, decode_access_token, hash_password, verify_password
from api.server import app
from api.websocket_client import WebSocketClient
from core.tenant import tenant_scope
from memory.memory_manager import load_memory, update_memory


class HostedApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        cls.context = cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def setUp(self):
        self.email = f"operator-{uuid.uuid4().hex}@example.com"
        response = self.client.post("/auth/signup", json={
            "email": self.email,
            "password": "correct-horse-battery-staple",
            "display_name": "Morgan",
        })
        self.assertEqual(response.status_code, 201, response.text)
        session = response.json()
        self.user_id = session["user"]["id"]
        self.access_token = session["access_token"]
        self.headers = {"Authorization": f"Bearer {session['access_token']}"}

    def tearDown(self):
        with SessionLocal.begin() as db:
            for model in (
                AnswerCacheEntry, TaskRecord, ChatMessage, UserConfig,
                MemoryEntry, UserSecret,
            ):
                db.execute(delete(model).where(model.user_id == self.user_id))
            db.execute(delete(User).where(User.id == self.user_id))

    def test_password_hash_and_jwt_round_trip(self):
        encoded = hash_password("correct-horse-battery-staple")
        self.assertNotIn("correct-horse", encoded)
        self.assertTrue(verify_password("correct-horse-battery-staple", encoded))
        self.assertFalse(verify_password("incorrect-password", encoded))
        token = create_access_token(self.user_id)
        self.assertEqual(decode_access_token(token)["sub"], self.user_id)

    def test_gemini_key_is_encrypted_and_user_status_updates(self):
        raw_key = "AIza" + "A" * 35
        response = self.client.post(
            "/me/gemini-key",
            headers=self.headers,
            json={"api_key": raw_key, "validate": False},
        )
        self.assertEqual(response.status_code, 200, response.text)
        with SessionLocal() as db:
            row = db.scalar(select(UserSecret).where(UserSecret.user_id == self.user_id))
            self.assertIsNotNone(row)
            self.assertNotIn(raw_key, row.encrypted_value)
        me = self.client.get("/auth/me", headers=self.headers)
        self.assertTrue(me.json()["gemini_configured"])

        from actions.presentation_maker import _api_key

        with tenant_scope(self.user_id):
            self.assertEqual(_api_key(), raw_key)

    def test_memory_is_scoped_by_tenant(self):
        with tenant_scope(self.user_id):
            update_memory({"identity": {"name": {"value": "Morgan"}}})
            self.assertEqual(load_memory()["identity"]["name"]["value"], "Morgan")

        other_id = str(uuid.uuid4())
        with SessionLocal.begin() as db:
            db.add(User(
                id=other_id,
                email=f"other-{uuid.uuid4().hex}@example.com",
                display_name="Other",
                password_hash=hash_password("another-secure-password"),
            ))
        try:
            with tenant_scope(other_id):
                self.assertNotIn("name", load_memory()["identity"])
        finally:
            with SessionLocal.begin() as db:
                db.execute(delete(User).where(User.id == other_id))

    def test_status_and_cloud_actions_are_authenticated(self):
        self.assertEqual(self.client.get("/status").status_code, 401)
        status_response = self.client.get("/status", headers=self.headers)
        self.assertEqual(status_response.json()["state"], "OFFLINE")
        actions = self.client.get("/actions", headers=self.headers).json()["actions"]
        names = {action["name"] for action in actions}
        self.assertIn("web_search", names)
        self.assertNotIn("open_app", names)

    def test_ios_chat_returns_confirmed_native_action_without_the_mac(self):
        response = self.client.post(
            "/chat",
            headers=self.headers,
            json={
                "message": "Text Sam saying I am on my way",
                "client_kind": "ios",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["handoff"]["kind"], "message-contact")
        self.assertEqual(payload["handoff"]["contact"], "Sam")
        self.assertEqual(payload["handoff"]["copy"], "I am on my way")
        history = self.client.get("/chat/history", headers=self.headers)
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(
            [item["role"] for item in history.json()[-2:]],
            ["user", "assistant"],
        )

    def test_web_chat_does_not_receive_an_ios_handoff(self):
        response = self.client.post(
            "/chat",
            headers=self.headers,
            json={"message": "Open the camera"},
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIsNone(response.json().get("handoff"))

    def test_account_can_be_deleted_from_the_mobile_app(self):
        response = self.client.delete("/auth/account", headers=self.headers)
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(self.client.get("/auth/me", headers=self.headers).status_code, 401)
        with SessionLocal() as db:
            self.assertIsNone(db.get(User, self.user_id))

    def test_cloud_action_worker_keeps_tenant_context(self):
        import main
        from core.tenant import get_current_user_id

        jarvis = main.JarvisLive.__new__(main.JarvisLive)
        jarvis.cloud_safe = True
        jarvis.ui = SimpleNamespace(
            set_state=lambda _state: None,
            muted=False,
        )
        call = SimpleNamespace(id="tenant-call", name="web_search", args={"query": "test"})

        with patch.object(main, "web_search_action", side_effect=lambda **_kwargs: get_current_user_id()):
            with tenant_scope(self.user_id):
                response = asyncio.run(jarvis._execute_tool(call))

        self.assertEqual(response.response["result"], self.user_id)

    def test_authenticated_websocket_streams_engine_events(self):
        raw_key = "AIza" + "B" * 35
        response = self.client.post(
            "/me/gemini-key",
            headers=self.headers,
            json={"api_key": raw_key, "validate": False},
        )
        self.assertEqual(response.status_code, 200, response.text)

        class FakeLiveEngine:
            def __init__(self, client, **_kwargs):
                self.client = client
                self.stopped = threading.Event()

            async def run(self):
                self.client.set_state("LISTENING")
                while not self.stopped.is_set():
                    await asyncio.sleep(0.01)

            async def send_text(self, text):
                self.client.write_log(f"Jarvis: Echo: {text}")
                return True

            async def send_audio_chunk(self, _data, _mime_type="audio/pcm;rate=16000"):
                return True

            def request_shutdown(self):
                self.stopped.set()

            def _get_current_voice(self):
                return "puck"

        import main

        with patch.object(main, "JarvisLive", FakeLiveEngine):
            with self.client.websocket_connect(f"/ws?token={self.access_token}") as socket:
                received = [socket.receive_json(), socket.receive_json()]
                self.assertEqual({event["type"] for event in received}, {"ready", "status"})
                socket.send_json({"type": "text", "content": "status report"})
                message = socket.receive_json()
                self.assertEqual(message["type"], "message")
                self.assertEqual(message["content"], "Echo: status report")
                socket.send_json({"type": "close"})
                self.assertEqual(socket.receive()["type"], "websocket.close")


class FakeWebSocket:
    def __init__(self):
        self.events = []

    async def send_json(self, event):
        self.events.append(event)


class WebSocketAdapterTests(unittest.TestCase):
    def test_adapter_serializes_status_text_and_audio(self):
        async def run():
            socket = FakeWebSocket()
            client = WebSocketClient(socket)
            sender = asyncio.create_task(client.send_events())
            client.set_state("LISTENING")
            client.write_log("Jarvis: Online.")
            client.send_audio(b"\x01\x02")
            await asyncio.sleep(0)
            await client.close()
            await sender
            return socket.events

        events = asyncio.run(run())
        self.assertEqual([event["type"] for event in events], ["status", "message", "audio"])
        self.assertEqual(events[-1]["data"], "AQI=")


if __name__ == "__main__":
    unittest.main()
