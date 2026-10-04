"""Validation helpers for LiveCodeBench's Python functional test format."""

from __future__ import annotations

import ast
import json
import math
from dataclasses import dataclass


class FunctionalFormatError(ValueError):
    """Raised when a functional case is outside the supported call format."""


@dataclass(frozen=True)
class SolutionMethod:
    name: str
    minimum_arguments: int
    maximum_arguments: int


def solution_method(starter_code: str | None) -> SolutionMethod:
    """Return the sole public instance method declared by a Solution stub."""
    if not starter_code:
        raise FunctionalFormatError("starter code is missing")
    try:
        module = ast.parse(starter_code)
    except SyntaxError as exc:
        lines = starter_code.splitlines()
        last_code_line = next((line for line in reversed(lines) if line.strip()), "")
        if not last_code_line.rstrip().endswith(":"):
            raise FunctionalFormatError("starter code is not valid Python") from exc
        indentation = len(last_code_line) - len(last_code_line.lstrip()) + 4
        try:
            module = ast.parse("\n".join([*lines, " " * indentation + "pass"]))
        except SyntaxError as retry_exc:
            raise FunctionalFormatError("starter code is not valid Python") from retry_exc

    classes = [
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "Solution"
    ]
    if len(classes) != 1:
        raise FunctionalFormatError("starter code must declare one Solution class")

    methods = [
        node
        for node in classes[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    ]
    if len(methods) != 1:
        raise FunctionalFormatError("Solution must declare one public method")
    method = methods[0]
    if isinstance(method, ast.AsyncFunctionDef):
        raise FunctionalFormatError("async Solution methods are unsupported")
    if any(
        isinstance(decorator, ast.Name)
        and decorator.id in {"staticmethod", "classmethod"}
        for decorator in method.decorator_list
    ):
        raise FunctionalFormatError("only instance methods are supported")

    arguments = method.args
    if (
        arguments.vararg is not None
        or arguments.kwarg is not None
        or arguments.kwonlyargs
        or not arguments.args
        or arguments.args[0].arg != "self"
    ):
        raise FunctionalFormatError("method must accept positional arguments")
    positional = arguments.posonlyargs + arguments.args[1:]
    default_count = len(arguments.defaults)
    return SolutionMethod(
        name=method.name,
        minimum_arguments=len(positional) - default_count,
        maximum_arguments=len(positional),
    )


def parse_functional_arguments(value: str) -> list[object]:
    """Parse one LiveCodeBench argument per line without evaluating code."""
    lines = value.splitlines()
    if value == "":
        lines = []
    try:
        return [_parse_literal(line) for line in lines]
    except (ValueError, SyntaxError) as exc:
        raise FunctionalFormatError("input must contain one literal per line") from exc


def parse_expected_result(value: str) -> object:
    """Parse the official JSON-encoded expected return value."""
    try:
        result = json.loads(
            value,
            parse_constant=lambda _constant: (_ for _ in ()).throw(
                ValueError("non-finite JSON number")
            ),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise FunctionalFormatError("expected result must be valid JSON") from exc
    if not _is_json_value(result):
        raise FunctionalFormatError("expected result is not JSON-compatible")
    return result


def validate_functional_case(
    method: SolutionMethod, input_value: str, expected_value: str
) -> None:
    """Check an official test case against the supported call/result format."""
    arguments = parse_functional_arguments(input_value)
    if not method.minimum_arguments <= len(arguments) <= method.maximum_arguments:
        raise FunctionalFormatError("input argument count does not match the method")
    parse_expected_result(expected_value)


def functional_results_equal(actual: object, expected: object) -> bool:
    """Compare JSON-like values while preserving JSON type distinctions."""
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(
            functional_results_equal(left, right)
            for left, right in zip(actual, expected)
        )
    if isinstance(actual, dict):
        return (
            actual.keys() == expected.keys()
            and all(
                functional_results_equal(actual[key], expected[key])
                for key in actual
            )
        )
    return actual == expected


def _parse_literal(value: str) -> object:
    try:
        return json.loads(
            value,
            parse_constant=lambda _constant: (_ for _ in ()).throw(
                ValueError("non-finite JSON number")
            ),
        )
    except json.JSONDecodeError:
        return ast.literal_eval(value)


def _is_json_value(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(item)
            for key, item in value.items()
        )
    return False
