import unittest

from scripts.check_linear_pr import validate


def pr(title="SCO-1 Test", body="Fixes SCO-1", base="main"):
    return {"title": title, "body": body, "base": {"ref": base}}


class ContractTests(unittest.TestCase):
    def test_main_closing_and_stacked_partial(self):
        self.assertEqual(validate(pr()), [])
        self.assertEqual(validate(pr(body="Part of SCO-1", base="feature/base")), [])

    def test_bad_links(self):
        self.assertTrue(validate(pr(title="No card")))
        self.assertTrue(validate(pr(body="Fixes SCO-2")))
        self.assertTrue(validate(pr(title="SCO-1 SCO-2", body="Fixes SCO-1")))
        self.assertTrue(validate(pr(body="Fixes SCO-1", base="feature/base")))

    def test_unrelated_and_untrusted_text_do_not_close(self):
        self.assertEqual(validate(pr(body="Part of SCO-1\nRelates to SCO-2")), [])
        self.assertTrue(validate(pr(body="<!-- Fixes SCO-1 -->")))

    def test_all_noncanonical_or_secondary_closing_magic_fails(self):
        self.assertTrue(validate(pr(title="SCO-50 Test", body="Part of SCO-50\nThis completes SCO-51")))
        self.assertTrue(validate(pr(title="SCO-50 Test", body="Fixes SCO-50, SCO-51")))
        self.assertTrue(validate(pr(title="SCO-50 Test", body="Fixing SCO-50", base="feature/base")))
        self.assertTrue(validate(pr(title="SCO-50 Test", body="Fixes [SCO-50](https://linear.app/x/issue/SCO-50)")))
        self.assertTrue(validate(pr(title="SCO-50 Test", body="Part of SCO-50\nFixes SCO-50, SCO-51")))
        self.assertTrue(validate(pr(title="SCO-50 Test", body="Part of SCO-50\nNote: Fixes SCO-50.")))


if __name__ == "__main__":
    unittest.main()
