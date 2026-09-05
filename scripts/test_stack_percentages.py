"""Offline regression tests: percentage math, private-data boundaries and SVGs."""
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from generate_stack_percentages import (
    LANGUAGES, DataError, collect_bytes, render_stack, tenths_percent,
)


def totals(values):
    return dict(zip((name for name, _ in LANGUAGES), values))


def repository(repo_id, name, private=False, fork=False, owner="test-user"):
    return {"id": repo_id, "name": name, "private": private, "fork": fork,
            "owner": {"login": owner}, "language": "CSS"}


class StackPercentageTests(unittest.TestCase):
    def test_rounding_sums_to_one_hundred(self):
        self.assertEqual(tenths_percent(totals([1] * 6)), [167, 167, 167, 167, 166, 166])
        self.assertEqual(sum(tenths_percent(totals([3, 7, 11, 17, 23, 29]))), 1000)

    def test_missing_languages_are_not_given_invented_shares(self):
        self.assertEqual(tenths_percent(totals([1, 0, 0, 0, 0, 0])), [1000, 0, 0, 0, 0, 0])
        for values in ([0] * 6, [-1, 2, 0, 0, 0, 0]):
            with self.assertRaises(DataError):
                tenths_percent(totals(values))

    def test_tiny_share_and_svg_validity(self):
        svg = render_stack(totals([100000, 1, 0, 0, 0, 0]), True)
        root = ET.fromstring(svg)
        self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
        self.assertIn("&lt;0,1%", svg)
        self.assertIn("Públicos + privados accesibles", svg)
        self.assertIn("CSS y los demás lenguajes no forman parte del total", svg)
        for name, _ in LANGUAGES:
            self.assertIn(name, svg)

    def test_public_only_is_labeled(self):
        self.assertIn("Solo repositorios públicos", render_stack(totals([1] * 6), False))

    @patch("generate_stack_percentages.api_get")
    def test_merge_private_public_and_filter_forks_and_other_owners(self, get):
        public = repository(1, "public-sample")
        private = repository(2, "confidential-sample", private=True)

        def response(path, token):
            if path.startswith("/users/"):
                return [public, repository(3, "fork-sample", fork=True)]
            if path == "/user":
                self.assertEqual(token, "private-test-token")
                return {"login": "test-user"}
            if path.startswith("/user/repos?"):
                return [private, private, repository(4, "another-owner", private=True, owner="other")]
            if path.endswith("/public-sample/languages"):
                self.assertEqual(token, "public-test-token")
                return {"Go": 100, "PHP": 50, "CSS": 999999}
            if path.endswith("/confidential-sample/languages"):
                self.assertEqual(token, "private-test-token")
                return {"Rust": 150, "TypeScript": 200, "HTML": 999999}
            self.fail("Unexpected API request")

        get.side_effect = response
        values, private_included = collect_bytes("test-user", "public-test-token", "private-test-token")
        self.assertTrue(private_included)
        self.assertEqual(values, totals([100, 150, 200, 0, 50, 0]))
        self.assertEqual(tenths_percent(values), [200, 300, 400, 0, 100, 0])
        svg = render_stack(values, private_included)
        self.assertNotIn("confidential-sample", svg)
        self.assertNotIn("private-test-token", svg)
        self.assertEqual(get.call_count, 5)

    @patch("generate_stack_percentages.api_get")
    def test_no_private_token_no_private_request(self, get):
        get.side_effect = [[repository(1, "sample")], {"PHP": 100}]
        values, private_included = collect_bytes("test-user", "public-test-token", "")
        self.assertFalse(private_included)
        self.assertEqual(values["PHP"], 100)
        self.assertEqual(get.call_count, 2)

    @patch("generate_stack_percentages.api_get")
    def test_wrong_account_token_is_rejected(self, get):
        get.side_effect = [[], {"login": "other-account"}]
        with self.assertRaises(DataError):
            collect_bytes("test-user", "public-test-token", "private-test-token")

    @patch("generate_stack_percentages.api_get")
    def test_bad_language_response_is_rejected(self, get):
        get.side_effect = [[repository(1, "sample")], {"Go": "not-a-byte-count"}]
        with self.assertRaises(DataError):
            collect_bytes("test-user", "public-test-token", "")


if __name__ == "__main__":
    unittest.main()
