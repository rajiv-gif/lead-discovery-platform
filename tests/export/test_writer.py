"""Tests for src/export/writer.py"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.export.writer import write_csv

FIELDS = ["name", "email", "score"]


def test_writes_header_even_when_rows_empty(tmp_path):
    out = tmp_path / "out.csv"
    count = write_csv([], out, FIELDS)

    assert count == 0
    assert out.exists()

    with out.open() as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == FIELDS
        rows = list(reader)
    assert rows == []


def test_returns_correct_row_count(tmp_path):
    rows = [
        {"name": "Alice", "email": "alice@example.com", "score": "80"},
        {"name": "Bob", "email": "bob@example.com", "score": "60"},
        {"name": "Carol", "email": "carol@example.com", "score": "40"},
    ]
    out = tmp_path / "out.csv"
    count = write_csv(rows, out, FIELDS)

    assert count == 3

    with out.open() as f:
        reader = csv.DictReader(f)
        read_rows = list(reader)
    assert len(read_rows) == 3


def test_creates_parent_directories(tmp_path):
    out = tmp_path / "subdir1" / "subdir2" / "out.csv"
    assert not out.parent.exists()

    write_csv([], out, FIELDS)

    assert out.exists()


def test_handles_special_characters_correctly(tmp_path):
    rows = [
        {"name": 'Alice "The Best" Smith', "email": "alice@example.com", "score": "80"},
        {"name": "Bob,Jones", "email": "bob@example.com", "score": "60"},
        {"name": "Carol\nNewline", "email": "carol@example.com", "score": "40"},
    ]
    out = tmp_path / "out.csv"
    write_csv(rows, out, FIELDS)

    with out.open() as f:
        reader = csv.DictReader(f)
        read_rows = list(reader)

    assert len(read_rows) == 3
    assert read_rows[0]["name"] == 'Alice "The Best" Smith'
    assert read_rows[1]["name"] == "Bob,Jones"
