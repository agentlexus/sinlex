"""Тесты лимитов STEP (TZ-step-upload-limits)."""

import unittest

from page_modules.upload_limits import (
    GLB_INLINE_MAX_BYTES,
    MAX_STEP_UPLOAD_BYTES,
    MAX_STEP_UPLOAD_MB,
    validate_step_upload,
)


class TestUploadLimits(unittest.TestCase):
    def test_max_mb(self):
        self.assertEqual(MAX_STEP_UPLOAD_MB, 6)

    def test_validate_ok(self):
        self.assertIsNone(validate_step_upload(b"x" * 1000))

    def test_validate_too_large(self):
        err = validate_step_upload(b"x" * (MAX_STEP_UPLOAD_BYTES + 1))
        self.assertIsNotNone(err)
        self.assertIn("6", err)

    def test_glb_inline_20mb(self):
        self.assertEqual(GLB_INLINE_MAX_BYTES, 20 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
