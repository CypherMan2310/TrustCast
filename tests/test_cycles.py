"""Cycle selection and staleness."""

import datetime as dt

from trustcast.archive.cycles import candidate_cycles, floor_cycle

D = dt.datetime


def test_floor_cycle():
    assert floor_cycle(D(2026, 9, 30, 6), [0, 12]) == D(2026, 9, 30, 0)
    assert floor_cycle(D(2026, 9, 30, 12), [0, 12]) == D(2026, 9, 30, 12)
    assert floor_cycle(D(2026, 9, 30, 11, 59), [0, 12]) == D(2026, 9, 30, 0)
    assert floor_cycle(D(2026, 1, 1, 3), [0, 12]) == D(2026, 1, 1, 0)


def test_06z_provider_run_maps_to_00z():
    # ICON reported 06Z as its newest run: we archive 00Z and earlier 00/12Z cycles
    c = candidate_cycles(D(2026, 9, 30, 6), D(2026, 9, 30, 10), [0, 12], 4, 48)
    assert c == [D(2026, 9, 28, 12), D(2026, 9, 29, 0), D(2026, 9, 29, 12), D(2026, 9, 30, 0)]


def test_future_last_init_is_clamped_to_now():
    c = candidate_cycles(D(2026, 10, 5, 0), D(2026, 9, 30, 10), [0, 12], 1, 48)
    assert c == [D(2026, 9, 30, 0)]


def test_age_limit_drops_old_cycles():
    c = candidate_cycles(D(2026, 9, 30, 0), D(2026, 9, 30, 10), [0, 12], 10, 24)
    assert c == [D(2026, 9, 29, 12), D(2026, 9, 30, 0)]


def test_stale_source_gives_no_candidates():
    # GEM on Open-Meteo reported 2026-05-26 00Z on 2026-09-30
    assert candidate_cycles(D(2026, 5, 26, 0), D(2026, 9, 30, 10), [0, 12], 4, 48) == []
