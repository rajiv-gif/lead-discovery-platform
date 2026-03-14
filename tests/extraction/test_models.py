"""Tests for src/extraction/models.py — normalize_name_key and split_name."""
from __future__ import annotations

import pytest

from src.extraction.models import normalize_name_key, split_name


# ---------------------------------------------------------------------------
# normalize_name_key
# ---------------------------------------------------------------------------


def test_normalize_name_key_strips_honorific_dr():
    assert normalize_name_key("Dr. John Smith") == "john smith"


def test_normalize_name_key_strips_apostrophe():
    assert normalize_name_key("Mrs. Jane O'Brien") == "jane obrien"


def test_normalize_name_key_strips_extra_whitespace():
    assert normalize_name_key("  Dr  James   Bond  ") == "james bond"


def test_normalize_name_key_plain_name():
    assert normalize_name_key("Alice Wonderland") == "alice wonderland"


def test_normalize_name_key_lowercase():
    assert normalize_name_key("JOHN SMITH") == "john smith"


def test_normalize_name_key_mr():
    assert normalize_name_key("Mr. James Dean") == "james dean"


def test_normalize_name_key_prof():
    assert normalize_name_key("Prof. Alice Brown") == "alice brown"


# ---------------------------------------------------------------------------
# split_name
# ---------------------------------------------------------------------------


def test_split_name_two_tokens():
    assert split_name("John Smith") == ("John", "Smith")


def test_split_name_three_tokens():
    assert split_name("Mary Jane Watson") == ("Mary", "Jane Watson")


def test_split_name_four_tokens():
    assert split_name("John Michael David Smith") == ("John", "Michael David Smith")


def test_split_name_one_token_returns_none():
    assert split_name("Madonna") == (None, None)


def test_split_name_five_tokens_returns_none():
    assert split_name("A B C D E") == (None, None)
