"""Contract for the temporary libzstd1 security overlay on distroless images (#1743)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ("services/device-agent/Dockerfile", "services/telegram-gateway/Dockerfile")


class LibzstdOverlayTests(unittest.TestCase):
    def test_overlay_pins_exact_debian_fix_and_lands_in_the_runtime(self) -> None:
        for path in IMAGES:
            with self.subTest(path=path):
                text = (ROOT / path).read_text(encoding="utf-8")
                self.assertIn("ARG LIBZSTD1_VERSION=1.5.7+dfsg-1+deb13u1", text)
                self.assertIn('test "$(dpkg-deb -f "$deb" Version)" = "$LIBZSTD1_VERSION"', text)
                self.assertIn('test "$(dpkg-deb -f "$deb" Architecture)" = "$(dpkg --print-architecture)"', text)
                self.assertIn("md5sum --quiet -c var/lib/dpkg/status.d/libzstd1.md5sums", text)
                runtime = text.split("FROM gcr.io/distroless/base-debian13:nonroot", 1)[1]
                self.assertIn("COPY --from=libzstd-fix /opt/libzstd/root/ /", runtime)
                # The overlay is the library package only: no other package or tool enters the runtime.
                self.assertEqual(re.findall(r"apt-get download \"([^\"]+)\"", text), ["libzstd1=${LIBZSTD1_VERSION}"])
                self.assertNotIn("apt-get install", text)


if __name__ == "__main__":
    unittest.main()
