"""Static-analysis corpus; never execute this file as a test suite."""

import time

import requests


def test_network():
    requests.get("https://example.test")


def test_clock():
    time.sleep(0.01)


def test_clean():
    assert 1 == 1
