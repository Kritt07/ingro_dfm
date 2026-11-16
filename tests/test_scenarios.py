"""Test suite for Ingro DFM core scenarios using unittest.

The tests verify that the stub implementation in ``core.model`` returns the
reference Nvr values from the specification (section 5) and that the derived
technological level ``Ut`` matches the expected ratios.  Additional checks are
included for the DFM‑recommendations engine.
"""

import unittest

from ingro_dfm.core.model import compute
from ingro_dfm.core.recommendations import run_all

class TestCoreScenarios(unittest.TestCase):
    def _run(self, material, variant, exp_nvr, exp_ut):
        passport = {"material_key": material, "variant": variant, "batch_size_q": 5}
        result = compute(passport)
        # 1 % tolerance
        self.assertAlmostEqual(result["Nvr"], exp_nvr, delta=exp_nvr * 0.01)
        self.assertAlmostEqual(result["Ut"], exp_ut, delta=exp_ut * 0.01)

    def test_base(self):
        self._run("45", "base", 38.99, 1.00)

    def test_v1_grubo(self):
        self._run("45", "V1_грубо", 23.08, 0.59)

    def test_v3_tochno(self):
        self._run("45", "V3_точно", 47.91, 1.23)

    def test_v4_zavysheno(self):
        self._run("45", "V4_завышено", 52.73, 1.35)

    def test_material_change_40x(self):
        passport = {"material_key": "40Х", "variant": "material_change", "batch_size_q": 5}
        self.assertAlmostEqual(compute(passport)["Nvr"], 40.70, delta=0.4)

    def test_material_change_12x(self):
        passport = {"material_key": "12Х18Н10Т", "variant": "material_change", "batch_size_q": 5}
        self.assertAlmostEqual(compute(passport)["Nvr"], 46.68, delta=0.5)

    def test_material_change_d16(self):
        passport = {"material_key": "Д16Т", "variant": "material_change", "batch_size_q": 5}
        self.assertAlmostEqual(compute(passport)["Nvr"], 41.05, delta=0.5)

class TestRecommendations(unittest.TestCase):
    def test_single_grinding_shaft_warning(self):
        passport = {
            "material_key": "45",
            "batch_size_q": 5,
            "surfaces": [{
                "code": "S1",
                "surf_type": "cylinder",
                "D_mm": 60,
                "L_mm": 10,
                "z_coord_mm": 0,
                "Ra_um": 0.8,
                "IT": 6,
                "purpose": "свободная",
                "extra_params": {},
                "confidence": "auto (geometry)"
            }]
        }
        warnings, saved = run_all(passport)
        self.assertTrue(any("круглошлифовальную операцию" in w for w in warnings))
        self.assertGreaterEqual(saved, 5.0)

    def test_invalid_ra_warning(self):
        passport = {
            "material_key": "45",
            "batch_size_q": 5,
            "surfaces": [{
                "code": "S2",
                "surf_type": "cylinder",
                "D_mm": 60,
                "L_mm": 10,
                "z_coord_mm": 0,
                "Ra_um": 7.0,
                "IT": 10,
                "purpose": "свободная",
                "extra_params": {},
                "confidence": "auto (geometry)"
            }]
        }
        warnings, _ = run_all(passport)
        self.assertTrue(any("не входит в стандартный ряд" in w for w in warnings))

if __name__ == "__main__":
    unittest.main()
