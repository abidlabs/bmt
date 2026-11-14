"""Registry of the kinds of things bmt can make."""

from __future__ import annotations

from ..core import Product
from .base import Kind
from .cards import CardsKind

KINDS: dict[str, Kind] = {k.id: k for k in [CardsKind()]}


def get_kind(kind_id: str) -> Kind:
    try:
        return KINDS[kind_id]
    except KeyError:
        raise ValueError(f"Unknown kind {kind_id!r}. Known kinds: {', '.join(sorted(KINDS))}") from None


def all_products() -> list[Product]:
    return [p for k in KINDS.values() for p in k.products]


def find_product(product_id: str) -> tuple[Kind, Product]:
    for kind in KINDS.values():
        for p in kind.products:
            if p.id == product_id:
                return kind, p
    known = ", ".join(p.id for p in all_products())
    raise ValueError(f"Unknown product {product_id!r}. Known products: {known}")
