"""Isola testes antigos de persistência; paginação real tem suíte própria.

Esses cenários usam IDs curtos e queries Mock sem implementar o contrato RTDB.
"""

from unittest.mock import patch


def isolate_persistence(test, worker):
    worker.lookback_records = 0

    def pages(reference, size, *, after=None, **kwargs):
        query = reference.order_by_key()
        if after is not None:
            query = query.start_at(after)
        rows = query.get()
        if isinstance(rows, dict):
            rows = {key: value for key, value in rows.items()
                    if after is None or key > after}
            if rows:
                yield rows

    for name, replacement in (
        ("validate_key", lambda key: key),
        ("last_key", lambda reference: None if not isinstance(
            reference.order_by_key().get(), dict,
        ) else max(reference.order_by_key().get(), default=None)),
        ("iter_pages", pages),
    ):
        mock = patch(f"app.worker.etl_worker.{name}", replacement)
        mock.start()
        test.addCleanup(mock.stop)
