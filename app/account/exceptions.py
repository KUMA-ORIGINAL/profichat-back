"""Оставлено для обратной совместимости: обработчик исключений переехал в common."""

from common.error_handler import api_exception_handler as custom_exception_handler  # noqa: F401
