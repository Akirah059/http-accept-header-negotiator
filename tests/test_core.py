import unittest
from http_accept_header_negotiator import AcceptHeaderNegotiator, parse_accept, negotiate


class TestParseAccept(unittest.TestCase):
    def test_simple_single(self):
        ranges = parse_accept("text/html")
        self.assertEqual(len(ranges), 1)
        self.assertEqual(ranges[0].type, "text")
        self.assertEqual(ranges[0].subtype, "html")
        self.assertAlmostEqual(ranges[0].q, 1.0)

    def test_multiple_with_q(self):
        ranges = parse_accept("text/html;q=0.9, application/json;q=0.8")
        self.assertEqual(len(ranges), 2)
        # Higher q comes first
        self.assertEqual(ranges[0].type, "text")
        self.assertAlmostEqual(ranges[0].q, 0.9)

    def test_wildcard_type(self):
        ranges = parse_accept("*/*, text/*, text/plain")
        # Most specific first
        self.assertEqual(ranges[0].type, "text")
        self.assertEqual(ranges[0].subtype, "plain")
        self.assertEqual(ranges[1].subtype, "*")
        self.assertEqual(ranges[2].type, "*")

    def test_q_truncation(self):
        # q has at most 3 decimal places per RFC; extra digits truncated
        ranges = parse_accept("text/html;q=0.9999")
        self.assertAlmostEqual(ranges[0].q, 0.999, places=4)

    def test_q_above_one_clamped(self):
        ranges = parse_accept("text/html;q=5")
        self.assertAlmostEqual(ranges[0].q, 1.0)

    def test_q_below_zero_clamped(self):
        ranges = parse_accept("text/html;q=-1")
        self.assertAlmostEqual(ranges[0].q, 0.0)

    def test_invalid_q_falls_back_to_default(self):
        ranges = parse_accept("text/html;q=abc")
        self.assertAlmostEqual(ranges[0].q, 1.0)

    def test_params_preserved(self):
        ranges = parse_accept("text/html;charset=utf-8;q=0.9")
        self.assertEqual(ranges[0].params, [("charset", "utf-8")])
        self.assertAlmostEqual(ranges[0].q, 0.9)

    def test_quoted_param_with_comma(self):
        ranges = parse_accept('text/html;charset="utf-8,ascii", application/json')
        self.assertEqual(len(ranges), 2)
        self.assertEqual(ranges[0].params, [("charset", "utf-8,ascii")])

    def test_language_header(self):
        ranges = parse_accept("en-US,en;q=0.9,fr;q=0.8")
        self.assertEqual(ranges[0].type, "en-us")
        self.assertAlmostEqual(ranges[1].q, 0.9)

    def test_empty_header(self):
        ranges = parse_accept("")
        self.assertEqual(len(ranges), 0)

    def test_whitespace_only(self):
        ranges = parse_accept("   ")
        self.assertEqual(len(ranges), 0)

    def test_empty_entries_ignored(self):
        ranges = parse_accept("text/html, , application/json")
        self.assertEqual(len(ranges), 2)


class TestNegotiate(unittest.TestCase):
    def test_exact_match(self):
        result = negotiate("text/html", ["application/json", "text/html"])
        self.assertEqual(result, "text/html")

    def test_wildcard_match(self):
        result = negotiate("text/*", ["application/json", "text/html"])
        self.assertEqual(result, "text/html")

    def test_star_star_match(self):
        result = negotiate("*/*", ["application/json", "text/html"])
        # First offered wins when all are equally acceptable
        self.assertEqual(result, "application/json")

    def test_q_factor_selection(self):
        result = negotiate("text/html;q=0.8, application/json;q=0.9", ["text/html", "application/json"])
        self.assertEqual(result, "application/json")

    def test_q_zero_excluded(self):
        result = negotiate("text/html;q=0, application/json;q=0.9", ["text/html", "application/json"])
        self.assertEqual(result, "application/json")

    def test_no_acceptable_returns_none(self):
        result = negotiate("text/html", ["application/json"])
        self.assertIsNone(result)

    def test_empty_header_returns_first_offered(self):
        result = negotiate("", ["text/html", "application/json"])
        self.assertEqual(result, "text/html")

    def test_offered_order_breaks_ties(self):
        # Both text/html and application/json have q=1.0, no specificity
        # difference. First offered wins.
        r1 = negotiate("text/html, application/json", ["text/html", "application/json"])
        r2 = negotiate("text/html, application/json", ["application/json", "text/html"])
        self.assertEqual(r1, "text/html")
        self.assertEqual(r2, "application/json")

    def test_specificity_beats_q(self):
        # text/html is more specific than text/* even though text/* is listed first
        result = negotiate("text/*, text/html", ["text/html"])
        self.assertEqual(result, "text/html")

    def test_language_negotiation(self):
        result = negotiate("en-US,en;q=0.9,fr;q=0.8", ["fr", "en"])
        self.assertEqual(result, "en")

    def test_encoding_negotiation(self):
        result = negotiate("gzip, br;q=0.8, identity;q=0", ["br", "gzip", "identity"])
        self.assertEqual(result, "gzip")


class TestAcceptHeaderNegotiator(unittest.TestCase):
    def test_select_matches_negotiate(self):
        header = "text/html;q=0.9, application/json;q=0.8"
        neg = AcceptHeaderNegotiator(header)
        self.assertEqual(negotiate(header, ["text/html", "application/json"]), neg.select(["text/html", "application/json"]))

    def test_repeated_select_does_not_mutate(self):
        neg = AcceptHeaderNegotiator("text/html, application/json")
        first = neg.select(["text/html", "application/json"])
        second = neg.select(["application/json", "text/html"])
        self.assertEqual(first, "text/html")
        self.assertEqual(second, "application/json")

    def test_ranges_property_returns_copy(self):
        neg = AcceptHeaderNegotiator("text/html")
        r1 = neg.ranges
        r1.clear()
        r2 = neg.ranges
        self.assertEqual(len(r2), 1)

    def test_empty_header_select(self):
        neg = AcceptHeaderNegotiator("")
        self.assertEqual(neg.select(["text/html"]), "text/html")
        self.assertIsNone(neg.select([]))


if __name__ == "__main__":
    unittest.main()
