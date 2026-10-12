import unittest
from decimal import Decimal

from billing.share import mailto_url, phone_digits, qr_svg, upi_uri, valid_upi_id, whatsapp_url


class ShareTests(unittest.TestCase):
    def test_phone(self):
        self.assertEqual(phone_digits("98765 43210"), "919876543210")
        self.assertEqual(phone_digits("+91-98765-43210"), "919876543210")
        self.assertEqual(phone_digits("09876543210"), "919876543210")
        self.assertIsNone(phone_digits("12345"))
        self.assertIsNone(phone_digits(""))

    def test_whatsapp_and_mail(self):
        url = whatsapp_url("98765 43210", "Hi & bye")
        self.assertEqual(url, "https://wa.me/919876543210?text=Hi%20%26%20bye")
        self.assertTrue(whatsapp_url("", "x").startswith("https://wa.me/?text="))
        self.assertEqual(mailto_url("a@b.com", "Bill 1", "Total 5"), "mailto:a%40b.com?subject=Bill%201&body=Total%205")

    def test_upi(self):
        self.assertTrue(valid_upi_id("shop@okaxis"))
        self.assertTrue(valid_upi_id("9876543210@ybl"))
        self.assertFalse(valid_upi_id("no-at-sign"))
        self.assertFalse(valid_upi_id("a b@upi"))
        uri = upi_uri("shop@okaxis", "My Shop", Decimal("1180"), "INV/26-27/0001")
        self.assertEqual(uri, "upi://pay?pa=shop%40okaxis&pn=My%20Shop&am=1180.00&cu=INR&tn=INV%2F26-27%2F0001")

    def test_qr_is_svg_or_empty(self):
        svg = qr_svg("upi://pay?pa=a@b")
        self.assertTrue(svg == "" or svg.lstrip().startswith("<svg"))


if __name__ == "__main__":
    unittest.main()
