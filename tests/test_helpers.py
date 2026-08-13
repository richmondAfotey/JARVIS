"""Tests for JARVIS AI. Run with:  pytest"""

from utils.helpers import clamp, now_str, sanitize_filename, now_timestamp
from datetime import datetime


def test_clamp_within_bounds():
    assert clamp(5, 0, 10) == 5


def test_clamp_below():
    assert clamp(-3, 0, 10) == 0


def test_clamp_above():
    assert clamp(99, 0, 10) == 10


def test_sanitize_filename_removes_illegal_chars():
    assert sanitize_filename('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"


def test_sanitize_filename_empty():
    assert sanitize_filename("   ") == "untitled"


def test_now_str_format():
    value = now_str()
    datetime.strptime(value, "%Y-%m-%d %H:%M:%S")  # raises if malformed


def test_now_timestamp_is_int_and_positive():
    assert isinstance(now_timestamp(), int)
    assert now_timestamp() > 1_600_000_000
