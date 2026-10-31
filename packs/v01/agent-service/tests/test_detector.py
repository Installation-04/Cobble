from cobble_agent_service.detector import LoopDetector, normalize


def test_repeated_line_triggers_after_threshold() -> None:
    d = LoopDetector(threshold=4)
    for _ in range(3):
        assert d.feed(b"Retrying the same thing\n").loop is None
    assert d.feed(b"Retrying the same thing\n").loop == "repeated_line"


def test_timestamps_and_colours_are_normalised() -> None:
    d = LoopDetector(threshold=3)
    d.feed(b"\x1b[31m12:00:01 error: boom\x1b[0m\n")
    d.feed(b"12:00:02 error: boom\n")
    assert d.feed(b"2026-01-01T12:00:03Z error: boom\n").loop == "repeated_line"
    assert normalize("12:00:01 x 0xdeadbeef") == "T x H"


def test_counters_and_progress_are_not_a_loop() -> None:
    d = LoopDetector(threshold=3)
    for i in range(20):
        assert d.feed(f"step {i}\n".encode()).loop is None
    for _ in range(20):  # blank lines and separators never count
        assert d.feed(b"\n-----\n").loop is None


def test_other_line_resets_the_streak() -> None:
    d = LoopDetector(threshold=3)
    for _ in range(2):
        d.feed(b"a line\n")
    d.feed(b"something else\n")
    for _ in range(2):
        assert d.feed(b"a line\n").loop is None


def test_partial_lines_and_carriage_returns() -> None:
    d = LoopDetector(threshold=3)
    d.feed(b"same")
    d.feed(b" line\r\nsame line\r\nsame")
    assert d.feed(b" line\r\n").loop == "repeated_line"


def test_iterations_follow_test_runs() -> None:
    d = LoopDetector()
    assert d.feed(b"[cobble:test-run 1]\n[cobble:test-fail aaaa1111]\n").iterations == 1
    assert d.feed(b"[cobble:test-run 2]\n").iterations == 2


def test_same_failure_fingerprint_twice_in_a_row_is_a_loop() -> None:
    d = LoopDetector()
    d.feed(b"[cobble:test-run 1]\n[cobble:test-fail aaaa1111]\n")
    assert d.feed(b"[cobble:test-run 2]\n[cobble:test-fail aaaa1111]\n").loop == "same_failure"


def test_different_or_interrupted_failures_are_not_a_loop() -> None:
    d = LoopDetector()
    d.feed(b"[cobble:test-fail aaaa1111]\n")
    assert d.feed(b"[cobble:test-fail bbbb2222]\n").loop is None
    d.feed(b"[cobble:test-pass]\n")
    assert d.feed(b"[cobble:test-fail bbbb2222]\n").loop is None
