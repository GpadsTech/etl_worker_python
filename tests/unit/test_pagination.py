"""Contrato de consultas Firebase: fronteiras, limites e falhas fechadas."""

import unittest
from unittest.mock import Mock, patch

from app.firebase.pagination import iter_pages, last_key, window_start, validate_key
from app.operations.rehearse import Query
from app.config.config import Config


def key(number):
    return "-" + f"{number:019d}"


class TestPagination(unittest.TestCase):
    def rows(self, count):
        return {key(n): {"n": n} for n in range(1, count + 1)}

    def test_bootstrap_sorts_and_emits_every_key_once_for_different_page_sizes(self):
        rows = dict(reversed(list(self.rows(13).items())))
        for size in (1, 2, 5, 13, 20):
            pages = list(iter_pages(Query(rows), size, end=key(13)))
            self.assertEqual([k for page in pages for k in page], sorted(rows))
            self.assertTrue(all(len(page) <= size for page in pages))

    def test_inclusive_start_and_exclusive_cursor(self):
        query = Query(self.rows(8))
        self.assertEqual(list(iter_pages(query, 2, start=key(3), end=key(6))), [
            {key(3): {"n": 3}, key(4): {"n": 4}},
            {key(5): {"n": 5}, key(6): {"n": 6}},
        ])
        self.assertEqual(list(iter_pages(query, 2, after=key(6), end=key(8))), [
            {key(7): {"n": 7}, key(8): {"n": 8}},
        ])

    def test_deleted_boundary_does_not_skip_extra_record(self):
        rows = self.rows(7)
        pages = iter_pages(Query(rows), 2, end=key(7))
        self.assertEqual(list(next(pages)), [key(1), key(2)])
        del rows[key(2)]
        self.assertEqual([k for page in pages for k in page],
                         [key(n) for n in range(3, 8)])

    def test_fixed_horizon_excludes_new_tail(self):
        rows = self.rows(3)
        horizon = last_key(Query(rows))
        pages = iter_pages(Query(rows), 2, end=horizon)
        next(pages)
        rows[key(4)] = {}
        self.assertEqual([k for page in pages for k in page], [key(3)])

    def test_repeated_page_fails_instead_of_looping_or_advancing(self):
        query = Mock()
        for method in ("order_by_key", "start_at", "end_at", "limit_to_first"):
            getattr(query, method).return_value = query
        query.get.return_value = {key(1): {}, key(2): {}}
        pages = iter_pages(query, 2, end=key(9))
        next(pages)
        with self.assertRaisesRegex(RuntimeError, "repetição"):
            next(pages)

    def test_lookback_is_last_n_keys_including_boundary(self):
        query = Query(self.rows(8))
        self.assertEqual(window_start(query, key(6), 3), key(4))
        self.assertIsNone(window_start(query, key(6), 0))
        self.assertEqual(window_start(query, key(99), 3), key(6))

    def test_window_discovery_itself_is_paginated(self):
        from app.firebase.pagination import read_result
        limits = []

        def observe(query, limit):
            limits.append(limit)
            return read_result(query, limit)

        with patch("app.firebase.pagination.read_result", side_effect=observe):
            self.assertEqual(window_start(Query(self.rows(9)), key(9), 7, 2), key(3))
        self.assertGreater(len(limits), 1)
        self.assertLessEqual(max(limits), 3)

    def test_no_records_and_cursor_at_horizon_make_no_page(self):
        self.assertIsNone(last_key(Query({})))
        self.assertEqual(list(iter_pages(Query({}), 2)), [])
        self.assertEqual(list(iter_pages(Query(self.rows(2)), 2,
                                         after=key(2), end=key(2))), [])

    def test_rejects_unsupported_key_and_invalid_response(self):
        for bad in ("123", "-001", "", 12, "x" * 21, "!" * 20):
            with self.assertRaises(ValueError):
                validate_key(bad)
        for rows in ([], True, {key(1): {}, key(2): {}, key(3): {}}):
            query = Mock()
            query.order_by_key.return_value.limit_to_first.return_value.get.return_value = rows
            with self.assertRaises(ValueError):
                list(iter_pages(query, 2))

    def test_source_cannot_ignore_upper_bound(self):
        query = Mock()
        query.order_by_key.return_value.end_at.return_value.limit_to_first.return_value.get.return_value = {
            key(9): {},
        }
        with self.assertRaises(RuntimeError):
            list(iter_pages(query, 2, end=key(8)))

    def test_config_limits(self):
        with patch.dict("os.environ", {"ETL_PAGE_SIZE": "17", "ETL_LOOKBACK_RECORDS": "0"}):
            config = Config()
            self.assertEqual(config.ETL_PAGE_SIZE, 17)
            self.assertEqual(config.ETL_LOOKBACK_RECORDS, 0)
        for name, value in (("ETL_PAGE_SIZE", "0"), ("ETL_PAGE_SIZE", "10001"),
                            ("ETL_LOOKBACK_RECORDS", "-1"), ("ETL_PAGE_SIZE", "no")):
            with patch.dict("os.environ", {name: value}):
                with self.assertRaises(ValueError):
                    Config()
