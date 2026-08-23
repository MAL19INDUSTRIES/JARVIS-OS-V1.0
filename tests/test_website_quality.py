import base64
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from actions import website_builder as builder
from actions.website_assets import generate_website_assets
from actions.website_quality import audit_source


class WebsiteQualityTests(unittest.TestCase):
    def test_static_audit_flags_missing_accessibility_foundations(self):
        issues = audit_source(
            {"src/App.tsx": "export default()=> <div><img src='/x.png'/></div>", "src/index.css": ".x{color:red}"},
            [{"name": "Home", "path": "/"}, {"name": "Work", "path": "/work"}],
        )
        codes = {item["code"] for item in issues if item["severity"] == "major"}
        self.assertTrue({"missing-main", "missing-h1", "missing-image-alt", "missing-focus", "missing-reduced-motion", "missing-route"}.issubset(codes))

    def test_static_audit_accepts_a_semantic_responsive_source(self):
        issues = audit_source(
            {
                "src/App.tsx": "export default()=> <main><h1>Studio</h1><a href='/work'>Work</a><img src='/hero.webp' alt='Designer reviewing a prototype'/></main>",
                "src/index.css": "a:focus-visible{outline:2px solid currentColor}@media(prefers-reduced-motion:reduce){*{animation:none}}",
            },
            [{"name": "Home", "path": "/"}, {"name": "Work", "path": "/work"}],
        )
        self.assertFalse([item for item in issues if item["severity"] == "major"])

    def test_direction_preview_rejects_css_injection(self):
        self.assertEqual(builder._safe_css_color("red;}</style><script>", "#123456"), "#123456")
        self.assertEqual(builder._safe_css_color("oklch(70% .12 80)", "#123456"), "oklch(70% .12 80)")

    def test_asset_generation_saves_optimized_local_webp(self):
        raw = io.BytesIO()
        Image.new("RGB", (64, 32), "#8a5a3c").save(raw, "PNG")
        encoded = base64.b64encode(raw.getvalue()).decode()
        result = SimpleNamespace(output_image=SimpleNamespace(data=encoded), candidates=[])
        client = SimpleNamespace(interactions=SimpleNamespace(create=lambda **_kwargs: result))
        with (
            tempfile.TemporaryDirectory() as temp,
            patch("memory.config_manager.get_gemini_key", return_value="test-key"),
            patch("google.genai.Client", return_value=client),
        ):
            manifest, warnings = generate_website_assets(
                [{"id": "hero", "prompt": "A quiet ceramic studio", "alt": "Hands shaping clay", "aspect_ratio": "16:9"}],
                Path(temp),
            )
            self.assertFalse(warnings)
            self.assertEqual(manifest[0]["path"], "/assets/hero.webp")
            self.assertTrue((Path(temp) / "public" / "assets" / "hero.webp").is_file())

    def test_asset_generation_fails_without_leaving_placeholder(self):
        client = SimpleNamespace(interactions=SimpleNamespace(create=lambda **_kwargs: SimpleNamespace(output_image=None, candidates=[])))
        with (
            tempfile.TemporaryDirectory() as temp,
            patch("memory.config_manager.get_gemini_key", return_value="test-key"),
            patch("google.genai.Client", return_value=client),
        ):
            manifest, warnings = generate_website_assets(
                [{"id": "hero", "prompt": "A quiet ceramic studio", "alt": "Hands shaping clay"}],
                Path(temp),
            )
            self.assertEqual(manifest, [])
            self.assertIn("returned no image", warnings[0])
            self.assertFalse((Path(temp) / "public" / "assets" / "hero.webp").exists())


if __name__ == "__main__":
    unittest.main()
