"""The tasks. Each asks for one function; the cases are hidden (never shown to the model).

Small on purpose: a model that fails these will not write a project. They stay stable between
versions so that results can be compared; changing a task means bumping `VERSION`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VERSION = 1

# An expected result meaning "the call must raise ValueError".
RAISES = {"__raises__": "ValueError"}


@dataclass(frozen=True)
class Task:
    id: str
    function: str
    prompt: str
    # (positional arguments, expected result), both JSON values
    cases: tuple[tuple[list[Any], Any], ...]


TASKS: tuple[Task, ...] = (
    Task(
        "fizzbuzz",
        "fizzbuzz",
        "fizzbuzz(n) returns the list of strings for 1..n: 'Fizz' for multiples of 3, 'Buzz' for "
        "multiples of 5, 'FizzBuzz' for both, otherwise the number as a string.",
        (
            ([0], []),
            ([1], ["1"]),
            ([5], ["1", "2", "Fizz", "4", "Buzz"]),
            (
                [15],
                [
                    "1",
                    "2",
                    "Fizz",
                    "4",
                    "Buzz",
                    "Fizz",
                    "7",
                    "8",
                    "Fizz",
                    "Buzz",
                    "11",
                    "Fizz",
                    "13",
                    "14",
                    "FizzBuzz",
                ],
            ),
        ),
    ),
    Task(
        "palindrome",
        "is_palindrome",
        "is_palindrome(s) is True when the string reads the same forwards and backwards, "
        "ignoring case and every character that is not a letter or a digit. The empty string is "
        "a palindrome.",
        (
            (["A man, a plan, a canal: Panama"], True),
            (["race a car"], False),
            ([""], True),
            ([" "], True),
            (["0P"], False),
            (["Was it a car or a cat I saw?"], True),
        ),
    ),
    Task(
        "word_count",
        "word_count",
        "word_count(text) returns a dict mapping each word to how many times it appears. Words "
        "are maximal runs of ASCII letters, compared in lower case. Other characters separate "
        "words. No words gives an empty dict.",
        (
            (["the cat and the hat"], {"the": 2, "cat": 1, "and": 1, "hat": 1}),
            (["Hello, hello; HELLO!"], {"hello": 3}),
            ([""], {}),
            (["42 is not a word"], {"is": 1, "not": 1, "a": 1, "word": 1}),
            (["it's"], {"it": 1, "s": 1}),
        ),
    ),
    Task(
        "merge_intervals",
        "merge_intervals",
        "merge_intervals(intervals) takes a list of [start, end] pairs (start <= end, any order) "
        "and returns the merged list sorted by start. Intervals that overlap or touch "
        "(next.start <= current.end) are merged. Each result is a [start, end] list.",
        (
            ([[[1, 3], [2, 6], [8, 10], [15, 18]]], [[1, 6], [8, 10], [15, 18]]),
            ([[[1, 4], [4, 5]]], [[1, 5]]),
            ([[]], []),
            ([[[5, 7], [1, 2], [2, 3]]], [[1, 3], [5, 7]]),
            ([[[1, 10], [2, 3], [4, 5]]], [[1, 10]]),
        ),
    ),
    Task(
        "roman",
        "roman_to_int",
        "roman_to_int(s) converts a Roman numeral (I V X L C D M, with subtractive pairs such as "
        "IV and CM) to an integer.",
        (
            (["III"], 3),
            (["IV"], 4),
            (["IX"], 9),
            (["LVIII"], 58),
            (["MCMXCIV"], 1994),
            (["MMMCMXCIX"], 3999),
        ),
    ),
    Task(
        "top_k",
        "top_k_frequent",
        "top_k_frequent(nums, k) returns the k most frequent integers of the list, most frequent "
        "first. Ties are broken by the smaller number first. If k is larger than the number of "
        "distinct values, return all of them.",
        (
            ([[1, 1, 1, 2, 2, 3], 2], [1, 2]),
            ([[1], 1], [1]),
            ([[4, 4, 5, 5, 6], 2], [4, 5]),
            ([[3, 3, 1, 1, 2], 3], [1, 3, 2]),
            ([[1, 2], 5], [1, 2]),
            ([[], 3], []),
        ),
    ),
    Task(
        "duration",
        "parse_duration",
        "parse_duration(text) converts a duration such as '1h30m', '45s', '2d', '1h1m1s' into a "
        "number of seconds. Units are d (86400), h (3600), m (60), s (1), each at most once and "
        "in that order. An empty or malformed string raises ValueError.",
        (
            (["1h30m"], 5400),
            (["45s"], 45),
            (["2d"], 172800),
            (["1h1m1s"], 3661),
            (["1d2h3m4s"], 93784),
            ([""], RAISES),
            (["abc"], RAISES),
            (["1m1h"], RAISES),
        ),
    ),
    Task(
        "flatten",
        "flatten",
        "flatten(items) returns a flat list with all the elements of arbitrarily nested lists, "
        "in order. Strings are not lists: keep them whole.",
        (
            ([[1, [2, [3, [4]]], 5]], [1, 2, 3, 4, 5]),
            ([[]], []),
            ([[[], [[]]]], []),
            ([["ab", ["cd", ["e"]]]], ["ab", "cd", "e"]),
            ([[1, 2, 3]], [1, 2, 3]),
        ),
    ),
)
