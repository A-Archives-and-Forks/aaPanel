# coding: utf-8

import json

from .exceptions import ProjectImportError


def parse_json_field(value, field_name, default=None):
    if value in (None, ""):
        return {} if default is None else default
    if isinstance(value, (dict, list)):
        return value
    try:
        result = json.loads(str(value))
    except (TypeError, ValueError) as exc:
        raise ProjectImportError(
            "{} must be valid JSON: {}".format(field_name, exc),
            "INVALID_JSON_FIELD",
        )
    return result


def bool_value(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def error_response(exc):
    import public
    if isinstance(exc, ProjectImportError):
        return public.return_message(-1, 0, {"result": str(exc), "error_code": exc.code})
    return public.return_message(-1, 0, str(exc))

