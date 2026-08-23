import unittest

from core.graphics_capability import score_graphics_capability


class GraphicsCapabilityTests(unittest.TestCase):
    def _score(self, **overrides):
        values = {
            "system": "Darwin",
            "physical_cores": 4,
            "logical_cores": 8,
            "ram_gb": 16,
            "gpu_name": "Intel Iris Plus Graphics 645",
            "vram_mb": 1536,
        }
        values.update(overrides)
        return score_graphics_capability(**values)

    def test_2019_intel_macbook_pro_resolves_medium_low(self):
        result = self._score()
        self.assertEqual(result.quality, "medium_low")
        self.assertEqual(result.gpu_class, "integrated")

    def test_constrained_device_resolves_very_low(self):
        result = self._score(
            physical_cores=2,
            logical_cores=4,
            ram_gb=4,
            gpu_name="Intel HD Graphics 4000",
            vram_mb=512,
        )
        self.assertEqual(result.quality, "very_low")

    def test_capable_discrete_gpu_resolves_ultra(self):
        result = self._score(
            system="Windows",
            physical_cores=8,
            logical_cores=16,
            ram_gb=32,
            gpu_name="NVIDIA GeForce RTX 4070",
            vram_mb=8192,
        )
        self.assertEqual(result.quality, "ultra")

    def test_apple_silicon_auto_mode_is_capped_for_sustained_mac_thermals(self):
        result = self._score(
            physical_cores=10,
            logical_cores=10,
            ram_gb=16,
            gpu_name="Apple M2 Pro",
            vram_mb=None,
        )
        self.assertEqual(result.quality, "high_low")

    def test_unknown_gpu_is_capped_at_medium(self):
        result = self._score(
            physical_cores=16,
            logical_cores=32,
            ram_gb=64,
            gpu_name="GPU unavailable",
            vram_mb=None,
        )
        self.assertEqual(result.quality, "medium")

    def test_hardware_fingerprint_is_stable(self):
        self.assertEqual(self._score().fingerprint, self._score().fingerprint)


if __name__ == "__main__":
    unittest.main()
