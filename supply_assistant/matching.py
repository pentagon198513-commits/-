"""Exact item matching for an explicitly scoped 1C catalog snapshot."""

from dataclasses import dataclass
from typing import Literal


def _text(value: object, field: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}: ожидается непустая строка")


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    article: str | None = None
    barcodes: tuple[str, ...] = ()
    variant_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.product_id, "product_id")
        _text(self.name, "name")
        _text(self.article, "article", optional=True)
        _text(self.variant_id, "variant_id", optional=True)
        if not isinstance(self.barcodes, (tuple, list)):
            raise ValueError("barcodes: ожидается список строк")
        for barcode in self.barcodes:
            _text(barcode, "barcode")
        object.__setattr__(self, "barcodes", tuple(self.barcodes))

    @property
    def key(self) -> tuple[str, str | None]:
        return self.product_id, self.variant_id


@dataclass(frozen=True)
class Catalog:
    organization_id: str
    cabinet_id: str
    products: tuple[Product, ...]

    def __post_init__(self) -> None:
        _text(self.organization_id, "organization_id")
        _text(self.cabinet_id, "cabinet_id")
        if not isinstance(self.products, (tuple, list)):
            raise ValueError("products: ожидается список товаров")
        keys = set()
        for product in self.products:
            if not isinstance(product, Product):
                raise ValueError("products: каждый элемент должен быть Product")
            if product.key in keys:
                raise ValueError("products: повтор идентификатора товара и характеристики")
            keys.add(product.key)
        object.__setattr__(self, "products", tuple(self.products))


@dataclass(frozen=True)
class OrderLine:
    order_id: str
    line_id: str
    organization_id: str
    cabinet_id: str
    article: str | None = None
    barcode: str | None = None

    def __post_init__(self) -> None:
        for field in ("order_id", "line_id", "organization_id", "cabinet_id"):
            _text(getattr(self, field), field)
        _text(self.article, "article", optional=True)
        _text(self.barcode, "barcode", optional=True)


@dataclass(frozen=True)
class MatchResult:
    status: Literal["matched", "needs_review"]
    reason: str
    product: Product | None = None
    candidates: tuple[Product, ...] = ()


def match_line(line: OrderLine, catalog: Catalog) -> MatchResult:
    """Propose a match; never create products or write a mapping to 1C.

    Both supplied identifiers must agree. A missing or conflicting identifier
    is returned for review rather than silently ignored. Codes remain exact
    strings, including leading zeros, case and whitespace.
    """
    if (line.organization_id, line.cabinet_id) != (
        catalog.organization_id, catalog.cabinet_id
    ):
        return MatchResult("needs_review", "scope_mismatch")
    if line.article is None and line.barcode is None:
        return MatchResult("needs_review", "missing_identifier")

    candidate_sets = []
    if line.article is not None:
        candidate_sets.append({
            product.key for product in catalog.products
            if product.article == line.article
        })
    if line.barcode is not None:
        candidate_sets.append({
            product.key for product in catalog.products
            if line.barcode in product.barcodes
        })

    possible_keys = set.union(*candidate_sets)
    possible = tuple(p for p in catalog.products if p.key in possible_keys)
    if any(not candidates for candidates in candidate_sets):
        return MatchResult("needs_review", "not_found", candidates=possible)

    common_keys = set.intersection(*candidate_sets)
    if not common_keys:
        return MatchResult(
            "needs_review", "conflicting_identifiers", candidates=possible
        )

    common = tuple(p for p in catalog.products if p.key in common_keys)
    if len(common) > 1:
        return MatchResult("needs_review", "ambiguous_match", candidates=common)
    return MatchResult("matched", "exact_match", product=common[0], candidates=common)
