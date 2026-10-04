"""Keep optional integrations from configuring the embedding application's logging."""

import logging


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
