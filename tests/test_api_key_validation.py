import unittest
from unittest.mock import patch

from core.api_key_validator import (
    ApiKeyValidationResult,
    _basic_key_check,
    validate_gemini_api_key,
)
from core.secret_store import NoopSecretStore
from core.secret_store import KeyringSecretStore


class GeminiApiKeyGateTests(unittest.TestCase):
    def test_foreign_provider_keys_are_rejected_before_network_validation(self):
        for key in ("sk-proj-" + "a" * 40, "sk-ant-" + "a" * 40):
            with self.subTest(key=key[:8]), patch(
                "core.api_key_validator._validate_with_gemini"
            ) as online_check:
                result = validate_gemini_api_key(key)
                self.assertFalse(result.valid)
                self.assertIn("Gemini", result.message)
                online_check.assert_not_called()

    def test_gemini_shaped_key_still_requires_online_verification(self):
        key = "AIza" + "a" * 32
        self.assertIsNone(_basic_key_check(key))
        with patch(
            "core.api_key_validator._validate_with_gemini",
            return_value=ApiKeyValidationResult(False, "API key is not valid."),
        ) as online_check:
            result = validate_gemini_api_key(key)
        self.assertFalse(result.valid)
        online_check.assert_called_once()

    def test_new_opaque_auth_key_shape_is_not_rejected_by_legacy_prefix_rules(self):
        key = "auth_" + "Z9xY8wV7uT6sR5qP4nM3kL2jH1gF0dC"
        self.assertIsNone(_basic_key_check(key))

    def test_locked_keychain_is_treated_as_unavailable_not_fatal(self):
        store = KeyringSecretStore.__new__(KeyringSecretStore)
        store.service = "jarvis"
        store._keyring = type(
            "BrokenKeyring",
            (),
            {"get_password": staticmethod(lambda *_: (_ for _ in ()).throw(RuntimeError("locked")))},
        )()
        self.assertIsNone(store.get("gemini_api_key"))

    def test_remembered_key_can_be_removed_after_failed_validation(self):
        store = NoopSecretStore()
        store.set("gemini_api_key", "bad")
        store.delete("gemini_api_key")
        self.assertIsNone(store.get("gemini_api_key"))


if __name__ == "__main__":
    unittest.main()
