"""Read normalized local JSON and print matching proposals."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .matching import Catalog, OrderLine, Product, match_line


MESSAGES = {
    "exact_match": "Найдено одно точное соответствие.",
    "scope_mismatch": "Организация или кабинет строки не совпадает с каталогом.",
    "missing_identifier": "В строке не указан артикул или штрихкод.",
    "not_found": "Хотя бы один из переданных кодов не найден в каталоге.",
    "conflicting_identifiers": "Артикул и штрихкод указывают на разные товары.",
    "ambiguous_match": "Найдено несколько товаров или характеристик; нужен выбор.",
}


def load_request(path: Path) -> tuple[Catalog, tuple[OrderLine, ...]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or set(data) != {"catalog", "lines"}:
        raise ValueError("Ожидается объект с полями catalog и lines")
    catalog_data = data["catalog"]
    if not isinstance(catalog_data, dict):
        raise ValueError("catalog: ожидается объект")
    products = catalog_data.get("products")
    if not isinstance(products, list):
        raise ValueError("catalog.products: ожидается список")
    catalog = Catalog(**{
        **catalog_data,
        "products": tuple(Product(**row) for row in products),
    })
    if not isinstance(data["lines"], list) or not data["lines"]:
        raise ValueError("lines: нужен непустой список строк заказов")
    lines = tuple(OrderLine(**row) for row in data["lines"])
    keys = {
        (line.organization_id, line.cabinet_id, line.order_id, line.line_id)
        for line in lines
    }
    if len(keys) != len(lines):
        raise ValueError("lines: повтор одной строки заказа в одном кабинете")
    return catalog, lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Локальная проверка сопоставления товаров по JSON. Без подключения к 1С."
    )
    parser.add_argument("input", type=Path, help="JSON в формате examples/matching.json")
    args = parser.parse_args()
    try:
        catalog, lines = load_request(args.input)
    except (OSError, UnicodeError, TypeError, ValueError) as error:
        print(f"Ошибка входных данных: {error}", file=sys.stderr)
        return 1

    results = []
    matched = 0
    for line in lines:
        result = match_line(line, catalog)
        matched += result.status == "matched"
        results.append({
            "order_id": line.order_id,
            "line_id": line.line_id,
            "organization_id": line.organization_id,
            "cabinet_id": line.cabinet_id,
            **asdict(result),
            "message": MESSAGES[result.reason],
        })
    print(json.dumps({
        "summary": {"matched": matched, "needs_review": len(lines) - matched},
        "results": results,
    }, ensure_ascii=False, indent=2))
    return 0 if matched == len(lines) else 2


if __name__ == "__main__":
    raise SystemExit(main())
