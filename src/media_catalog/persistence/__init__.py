"""Internal persistence components behind the CatalogWriter facade.

Components in this package receive the caller's ``CatalogDatabase`` and use its
connection. They never own transactions: no component calls ``commit``,
``executescript``, or opens a replacement connection.
"""
