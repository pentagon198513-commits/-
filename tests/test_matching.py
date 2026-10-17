"""Business-rule checks for matching marketplace order lines to a 1C catalog."""

import unittest

from supply_assistant.matching import Catalog, OrderLine, Product, match_line


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.first = Product(
            product_id="product-1",
            name="First product",
            article="00123",
            barcodes=("000987", "000988"),
        )
        self.second = Product(
            product_id="product-2",
            name="Second product",
            article="ARTICLE-B",
            barcodes=("BARCODE-B",),
        )
        self.catalog = self.make_catalog(self.first, self.second)

    @staticmethod
    def make_catalog(*products):
        return Catalog(
            organization_id="organization-1",
            cabinet_id="cabinet-1",
            products=products,
        )

    @staticmethod
    def make_line(**overrides):
        values = {
            "order_id": "order-1",
            "line_id": "line-1",
            "organization_id": "organization-1",
            "cabinet_id": "cabinet-1",
        }
        values.update(overrides)
        return OrderLine(**values)

    def assert_review(self, result, reason):
        self.assertEqual(result.status, "needs_review")
        self.assertEqual(result.reason, reason)
        self.assertIsNone(result.product)

    @staticmethod
    def candidate_keys(result):
        return {(product.product_id, product.variant_id) for product in result.candidates}

    def test_unique_article_matches(self):
        result = match_line(self.make_line(article="00123"), self.catalog)

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.reason, "exact_match")
        self.assertEqual(result.product, self.first)

    def test_any_registered_barcode_can_match(self):
        for barcode in self.first.barcodes:
            with self.subTest(barcode=barcode):
                result = match_line(self.make_line(barcode=barcode), self.catalog)

                self.assertEqual(result.status, "matched")
                self.assertEqual(result.product, self.first)

    def test_two_identifiers_agree_on_one_product(self):
        result = match_line(
            self.make_line(article="00123", barcode="000987"), self.catalog
        )

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.reason, "exact_match")
        self.assertEqual(result.product, self.first)

    def test_intersection_can_resolve_two_individually_ambiguous_identifiers(self):
        selected = Product("selected", "Selected", "A", ("X",))
        same_article = Product("same-article", "Same article", "A", ("Y",))
        same_barcode = Product("same-barcode", "Same barcode", "B", ("X",))
        catalog = self.make_catalog(selected, same_article, same_barcode)

        result = match_line(self.make_line(article="A", barcode="X"), catalog)

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.product, selected)

    def test_conflicting_identifiers_require_review(self):
        result = match_line(
            self.make_line(article="00123", barcode="BARCODE-B"), self.catalog
        )

        self.assert_review(result, "conflicting_identifiers")

    def test_missing_supplied_identifier_does_not_fall_back_to_other_identifier(self):
        cases = (
            {"article": "unknown", "barcode": "000987"},
            {"article": "00123", "barcode": "unknown"},
        )
        for identifiers in cases:
            with self.subTest(**identifiers):
                result = match_line(self.make_line(**identifiers), self.catalog)

                self.assert_review(result, "not_found")
                self.assertEqual(self.candidate_keys(result), {("product-1", None)})

    def test_unknown_identifiers_require_review(self):
        cases = (
            {"article": "unknown"},
            {"barcode": "unknown"},
            {"article": "unknown", "barcode": "also-unknown"},
        )
        for identifiers in cases:
            with self.subTest(**identifiers):
                result = match_line(self.make_line(**identifiers), self.catalog)

                self.assert_review(result, "not_found")
                self.assertEqual(result.candidates, ())

    def test_no_identifier_requires_review(self):
        result = match_line(self.make_line(), self.catalog)

        self.assert_review(result, "missing_identifier")
        self.assertEqual(result.candidates, ())

    def test_scope_mismatch_takes_precedence_even_without_identifiers(self):
        scopes = (
            {"organization_id": "another-organization"},
            {"cabinet_id": "another-cabinet"},
            {
                "organization_id": "another-organization",
                "cabinet_id": "another-cabinet",
            },
        )
        for scope in scopes:
            for identifiers in ({}, {"article": "00123", "barcode": "000987"}):
                with self.subTest(scope=scope, identifiers=identifiers):
                    line = self.make_line(**scope, **identifiers)
                    result = match_line(line, self.catalog)

                    self.assert_review(result, "scope_mismatch")

    def test_shared_article_across_variants_requires_review(self):
        small = Product("shirt", "Shirt small", "SHIRT", ("SMALL",), "small")
        large = Product("shirt", "Shirt large", "SHIRT", ("LARGE",), "large")
        catalog = self.make_catalog(small, large)

        result = match_line(self.make_line(article="SHIRT"), catalog)

        self.assert_review(result, "ambiguous_match")
        self.assertEqual(
            self.candidate_keys(result), {("shirt", "small"), ("shirt", "large")}
        )

    def test_barcode_selects_variant_when_article_is_shared(self):
        small = Product("shirt", "Shirt small", "SHIRT", ("SMALL",), "small")
        large = Product("shirt", "Shirt large", "SHIRT", ("LARGE",), "large")
        catalog = self.make_catalog(small, large)

        result = match_line(
            self.make_line(article="SHIRT", barcode="LARGE"), catalog
        )

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.product, large)

    def test_shared_barcode_does_not_select_first_product(self):
        first = Product("first", "First", "A", ("SHARED",))
        second = Product("second", "Second", "B", ("SHARED",))
        catalog = self.make_catalog(first, second)

        result = match_line(self.make_line(barcode="SHARED"), catalog)

        self.assert_review(result, "ambiguous_match")
        self.assertEqual(self.candidate_keys(result), {("first", None), ("second", None)})

    def test_identical_identifier_pair_across_variants_is_ambiguous(self):
        first = Product("item", "First variant", "A", ("X",), "first")
        second = Product("item", "Second variant", "A", ("X",), "second")

        result = match_line(
            self.make_line(article="A", barcode="X"), self.make_catalog(first, second)
        )

        self.assert_review(result, "ambiguous_match")
        self.assertEqual(
            self.candidate_keys(result), {("item", "first"), ("item", "second")}
        )

    def test_repeated_barcode_inside_one_product_is_not_ambiguous(self):
        product = Product("item", "Item", barcodes=("X", "X"))

        result = match_line(self.make_line(barcode="X"), self.make_catalog(product))

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.product, product)

    def test_leading_zeros_are_significant_for_article_and_barcode(self):
        cases = ({"article": "123"}, {"barcode": "987"})
        for identifiers in cases:
            with self.subTest(**identifiers):
                result = match_line(self.make_line(**identifiers), self.catalog)

                self.assert_review(result, "not_found")
        self.assertEqual(self.first.article, "00123")
        self.assertEqual(self.first.barcodes[0], "000987")

    def test_case_and_whitespace_are_not_normalized(self):
        cases = (
            {"article": "article-b"},
            {"barcode": "barcode-b"},
            {"article": " ARTICLE-B"},
            {"barcode": "BARCODE-B "},
        )
        for identifiers in cases:
            with self.subTest(**identifiers):
                result = match_line(self.make_line(**identifiers), self.catalog)

                self.assert_review(result, "not_found")

    def test_product_name_is_not_used_as_article_or_barcode(self):
        for identifiers in (
            {"article": self.first.name},
            {"barcode": self.first.name},
        ):
            with self.subTest(**identifiers):
                result = match_line(self.make_line(**identifiers), self.catalog)

                self.assert_review(result, "not_found")

    def test_empty_catalog_cannot_match(self):
        result = match_line(self.make_line(article="00123"), self.make_catalog())

        self.assert_review(result, "not_found")
        self.assertEqual(result.candidates, ())


class CatalogValidationTests(unittest.TestCase):
    def test_duplicate_product_and_variant_key_is_rejected(self):
        for variant_id in (None, "variant-1"):
            with self.subTest(variant_id=variant_id):
                first = Product("item", "First", "A", ("X",), variant_id)
                duplicate = Product("item", "Different details", "B", ("Y",), variant_id)

                with self.assertRaises(ValueError):
                    Catalog("organization", "cabinet", (first, duplicate))

    def test_distinct_variants_of_same_product_are_allowed(self):
        products = (
            Product("item", "Base item"),
            Product("item", "Variant one", variant_id="one"),
            Product("item", "Variant two", variant_id="two"),
        )

        catalog = Catalog("organization", "cabinet", products)

        self.assertEqual(catalog.products, products)

    def test_barcode_list_becomes_an_independent_tuple(self):
        barcodes = ["001", "002"]
        product = Product("item", "Item", barcodes=barcodes)
        barcodes.append("003")

        self.assertEqual(product.barcodes, ("001", "002"))

    def test_product_list_becomes_an_independent_tuple(self):
        product = Product("item", "Item")
        products = [product]
        catalog = Catalog("organization", "cabinet", products)
        products.clear()

        self.assertEqual(catalog.products, (product,))

    def test_bare_string_and_non_string_barcodes_are_rejected(self):
        for barcodes in ("00123", [123], ("00123", 456), {"00123"}):
            with self.subTest(barcodes=barcodes):
                with self.assertRaises(ValueError):
                    Product("item", "Item", barcodes=barcodes)

    def test_numeric_product_identifiers_are_rejected(self):
        for field in ("product_id", "article", "variant_id"):
            values = {"product_id": "item", "name": "Item", field: 123}
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    Product(**values)

    def test_numeric_catalog_scope_is_rejected(self):
        for field in ("organization_id", "cabinet_id"):
            values = {
                "organization_id": "organization",
                "cabinet_id": "cabinet",
                "products": (),
            }
            values[field] = 123
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    Catalog(**values)

    def test_numeric_order_identifiers_are_rejected(self):
        for field in (
            "order_id",
            "line_id",
            "organization_id",
            "cabinet_id",
            "article",
            "barcode",
        ):
            values = {
                "order_id": "order",
                "line_id": "line",
                "organization_id": "organization",
                "cabinet_id": "cabinet",
                field: 123,
            }
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    OrderLine(**values)


if __name__ == "__main__":
    unittest.main()
