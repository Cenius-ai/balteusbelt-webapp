"""End-to-end tests for the BalteusBelt command line tool.

Every test drives the shipped CLI exactly the way a user does - through
``python3 balteusbelt.py`` - so the tests double as the contract check for
the documented output.  The suite needs nothing but pytest and CPython.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "balteusbelt.py"

sys.path.insert(0, str(ROOT))
import balteusbelt as bb  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )


def output(*args: str) -> str:
    proc = run(*args)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    return proc.stdout


def failure(*args: str) -> str:
    proc = run(*args)
    assert proc.returncode == 2, "expected exit 2, got %d: %s" % (
        proc.returncode,
        proc.stdout,
    )
    assert proc.stdout == "", "failure must leave stdout empty"
    assert proc.stderr.startswith("error: "), proc.stderr
    assert proc.stderr.endswith("\n")
    assert proc.stderr.count("\n") == 1, "exactly one error line"
    return proc.stderr[len("error: ") : -1]


def write(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def grid_rows(stdout: str):
    """{pick: [glyph, ...]} parsed out of a render."""
    rows = {}
    for line in stdout.splitlines():
        match = re.match(r"^\s*(\d+)  [fb]   (\S.*)$", line)
        if match:
            rows[int(match.group(1))] = match.group(2).split()
    return rows


def turn_letters(stdout: str):
    return [line.split()[1] for line in stdout.splitlines() if re.match(r"^\s*\d+  [fb]  ", line)]


def dye_rows(stdout: str):
    """{(round, colour): (cards, threads)} parsed out of the dye table."""
    rows = {}
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[0].isdigit() and re.match(r"^\d+-\d+$", parts[1]):
            rows[(int(parts[0]), parts[2])] = (int(parts[3]), int(parts[4]))
    return rows


def dye_picks_labels(stdout: str):
    labels = {}
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[0].isdigit() and re.match(r"^\d+-\d+$", parts[1]):
            labels[int(parts[0])] = parts[1]
    return labels


OSEBERG_SWAP_LINE = "pick 3  card 2  hole 1  Green  (round 1)"
TURN_CONVENTION_LINE = (
    "Turn convention: pick 1 shows hole 0 face-up (no turn applied); "
    "row letter = turns[(p-1) % len(turns)]; f = +1 step, b = -1 step"
)


# ---------------------------------------------------------------------------
# T1 - CLI skeleton, help text and exit codes
# ---------------------------------------------------------------------------


def test_help_exits_zero_and_states_the_turn_convention():
    proc = run("--help")
    assert proc.returncode == 0
    assert TURN_CONVENTION_LINE in proc.stdout


def test_help_documents_options_formats_and_exit_codes():
    text = output("--help")
    for expected in ("--pattern", "--file", "--picks", "--show", "--list-patterns"):
        assert expected in text
    assert "JSON" in text and "text" in text
    assert "Exit codes:" in text
    assert "  0  success" in text
    assert "  2  input or usage error" in text


def test_version_exits_zero():
    assert output("--version") == "BalteusBelt 1.0.0\n"


@pytest.mark.parametrize("picks", ["0", "201", "500"])
def test_picks_out_of_range(picks):
    assert failure("--picks", picks) == "--picks must be between 1 and 200"


def test_picks_must_be_a_number():
    assert "--picks must be a whole number" in failure("--picks", "many")


def test_unrecognised_option():
    assert failure("--frobnicate") == "unrecognised option: --frobnicate"


def test_show_rejects_unknown_section():
    assert failure("--show", "bogus") == "--show must be one of grid, swaps, dye, all"


def test_pattern_and_file_are_mutually_exclusive(tmp_path):
    path = write(tmp_path, "p.json", json.dumps({"name": "x", "turns": "fb",
                                                 "threading": [["Red", "White", "Red", "White"]]}))
    assert failure("--pattern", "oseberg", "--file", path) == (
        "use either --pattern or --file, not both"
    )


# ---------------------------------------------------------------------------
# T2 - colour normalisation, glyph allocation and shared validators
# ---------------------------------------------------------------------------


def test_glyph_collision_uses_the_next_letter():
    glyphs = bb.allocate_glyphs(["Red", "Rust", "Blue"])
    assert glyphs == {"Red": "R", "Rust": "U", "Blue": "B"}


def test_glyph_legend_from_a_file(tmp_path):
    path = write(
        tmp_path,
        "rust.json",
        json.dumps(
            {
                "name": "rusty",
                "turns": "fb",
                "threading": [["Red", "Rust", "Blue", "White"]],
            }
        ),
    )
    stdout = output("--file", path, "--show", "grid")
    assert "Legend: R=Red U=Rust B=Blue W=White" in stdout


def test_glyph_falls_back_when_the_name_is_exhausted():
    glyphs = bb.allocate_glyphs(["R", "r"])
    assert glyphs == {"R": "R", "r": "#"}


def test_fallback_sequence_is_used_in_order():
    colours = ["R", "r", "Rr", "rr"]
    glyphs = bb.allocate_glyphs(colours)
    assert list(glyphs.values()) == ["R", "#", "@", "%"]


def test_non_ascii_colour_is_an_error_on_its_line(tmp_path):
    path = write(
        tmp_path,
        "accent.txt",
        "# a comment\nname: nonascii\ncard 1: R\u00f3d Blue Red White\nturns: fb\n",
    )
    assert failure("--file", path) == (
        "line 3: colour must be 1-24 ASCII letters, digits, - or _"
    )


def test_colour_names_are_ascii_only_in_json(tmp_path):
    path = write(
        tmp_path,
        "accent.json",
        json.dumps({"name": "x", "turns": "fb",
                    "threading": [["R\u00e9d", "Blue", "Red", "White"]]}),
    )
    assert "colour must be 1-24 ASCII letters" in failure("--file", path)


# ---------------------------------------------------------------------------
# T3 - pattern model, built-in catalogue and --list-patterns
# ---------------------------------------------------------------------------


def test_list_patterns_lists_all_four_builtins():
    text = output("--list-patterns")
    lines = text.splitlines()
    assert lines[0] == "BalteusBelt built-in patterns (4):"
    names = [line.split()[0] for line in lines[1:]]
    assert names == ["oseberg", "birka", "hedeby", "mammen"]
    assert "cards  8" in lines[1] and "picks   4" in lines[1]
    assert "Four-colour diagonal repeat" in lines[1]
    assert "Three-colour chevron with blue flash" in lines[2]
    assert "Two-colour band, red selvedge" in lines[3]
    assert "Two-colour interlace, six picks" in lines[4]
    assert all(len(line) <= 80 for line in lines)


def test_builtin_lookup_is_case_insensitive():
    stdout = output("--pattern", "BIRKA", "--show", "grid")
    assert stdout.splitlines()[0] == (
        "BalteusBelt - birka - Three-colour chevron with blue flash"
    )


def test_unknown_builtin_names_the_pattern():
    assert failure("--pattern", "nope") == "unknown pattern: nope (try --list-patterns)"


# ---------------------------------------------------------------------------
# T4 - grid renderer
# ---------------------------------------------------------------------------


def test_default_render_first_two_lines():
    lines = output().splitlines()
    assert lines[0] == "BalteusBelt - oseberg - Four-colour diagonal repeat"
    assert lines[1] == "Weft: Linen  Cards: 8  Picks: 4  Turns: fbfb"


def test_first_row_shows_the_unturned_threading():
    rows = grid_rows(output("--show", "grid"))
    assert rows[1] == "R O B W R O B W".split()
    assert turn_letters(output("--show", "grid"))[0] == "f"


def test_second_row_applies_one_forward_turn():
    stdout = output("--show", "grid")
    rows = grid_rows(stdout)
    assert rows[2] == "O B W R O B W R".split()
    assert turn_letters(stdout)[1] == "b"


def test_grid_has_one_row_per_pick():
    rows = grid_rows(output("--show", "grid"))
    assert sorted(rows) == [1, 2, 3, 4]


def test_legend_line_matches_the_documented_order():
    assert "Legend: R=Red O=Ochre B=Blue W=White G=Green" in output("--show", "grid")


def test_birka_glyph_collision_gives_blue_an_l():
    legend = [line for line in output("--pattern", "birka", "--show", "grid").splitlines()
              if line.startswith("Legend: ")]
    assert legend == ["Legend: R=Red W=White B=Black G=Gold L=Blue"]


@pytest.mark.parametrize("name", ["oseberg", "birka", "hedeby", "mammen"])
def test_every_builtin_line_fits_80_columns(name):
    proc = run("--pattern", name)
    assert proc.returncode == 0
    for line in proc.stdout.splitlines():
        assert len(line) <= 80, line


def test_grid_rows_fit_80_columns_at_the_maximum(tmp_path):
    cards = [["Red", "Ochre", "Blue", "White"] for _ in range(35)]
    path = write(tmp_path, "wide.json", json.dumps(
        {"name": "wide", "turns": "fb", "threading": cards}))
    stdout = output("--file", path, "--picks", "200")
    assert len(grid_rows(stdout)) == 200
    for line in stdout.splitlines():
        assert len(line) <= 80, line
    assert max(len(line) for line in stdout.splitlines()) <= 80


def test_long_name_and_description_still_fit_80_columns(tmp_path):
    cards = [["Red", "Ochre", "Blue", "White"] for _ in range(35)]
    path = write(tmp_path, "titled.json", json.dumps(
        {"name": "n" * 40, "description": "d" * 60, "turns": "fb" * 100,
         "threading": cards,
         "swaps": [{"pick": 200, "card": 35, "hole": 4, "colour": "Zed"}]}))
    stdout = output("--file", path, "--picks", "200")
    assert all(len(line) <= 80 for line in stdout.splitlines())
    assert "Zed" in stdout.splitlines()[-1] or "Totals" in stdout.splitlines()[-1]


def test_long_turns_metadata_is_wrapped(tmp_path):
    path = write(tmp_path, "turns.json", json.dumps(
        {"name": "longturns", "turns": "fb" * 100,
         "threading": [["Red", "Ochre", "Blue", "White"]]}))
    stdout = output("--file", path, "--picks", "4", "--show", "grid")
    assert all(len(line) <= 80 for line in stdout.splitlines())


# ---------------------------------------------------------------------------
# T5 - picks handling, cyclic turns and the 35-card limit
# ---------------------------------------------------------------------------


def test_picks_beyond_the_turns_cycle_repeats_the_letters():
    stdout = output("--pattern", "oseberg", "--picks", "8", "--show", "grid")
    assert turn_letters(stdout) == list("fbfbfbfb")
    assert len(grid_rows(stdout)) == 8


def test_too_many_cards_is_rejected(tmp_path):
    path = write(tmp_path, "big.json", json.dumps(
        {"name": "big", "turns": "fb",
         "threading": [["Red", "White", "Red", "White"]] * 36}))
    assert failure("--file", path) == (
        "threading: 36 cards exceeds the 35-card limit for an 80-column grid"
    )


def test_35_cards_is_accepted(tmp_path):
    path = write(tmp_path, "ok.json", json.dumps(
        {"name": "ok", "turns": "fb",
         "threading": [["Red", "White", "Red", "White"]] * 35}))
    proc = run("--file", path)
    assert proc.returncode == 0
    assert "Cards: 35" in proc.stdout


# ---------------------------------------------------------------------------
# T6 - swap application and the Swaps section
# ---------------------------------------------------------------------------


def test_swap_shows_on_its_pick_and_later():
    rows = grid_rows(output("--show", "grid"))
    assert rows[1][1] == "O"
    assert rows[2][1] == "B"
    assert rows[3][1] == "G"
    assert rows[4][1] == "B"


def test_swaps_section_lists_every_swap():
    stdout = output("--show", "swaps")
    assert stdout.splitlines() == ["Swaps:", OSEBERG_SWAP_LINE]


def test_not_reached_swap_is_marked_and_not_applied():
    stdout = output("--pattern", "hedeby")
    lines = stdout.splitlines()
    index = lines.index("pick 5  card 4  hole 1  Red  (round 2)")
    assert lines[index + 1].strip() == "(not reached: beyond --picks)"
    rows = grid_rows(stdout)
    # card 4 hole 0 is still its original Yellow: the pick-5 swap never fired
    assert rows[1][3] == "Y"
    assert rows[3][3] == "Y"
    # ... and it does fire as soon as the pick is rendered
    reached = grid_rows(output("--pattern", "hedeby", "--picks", "5", "--show", "grid"))
    assert reached[5][3] == "R"


def test_swaps_none_for_a_pattern_without_swaps(tmp_path):
    path = write(tmp_path, "noswap.json", json.dumps(
        {"name": "plain", "turns": "fb",
         "threading": [["Red", "White", "Red", "White"], ["White", "Red", "White", "Red"]]}))
    assert output("--file", path, "--show", "swaps") == "Swaps: none\n"


def test_swap_card_out_of_range(tmp_path):
    path = write(tmp_path, "bad.json", json.dumps(
        {"name": "bad", "turns": "fb",
         "threading": [["Red", "White", "Red", "White"]] * 8,
         "swaps": [{"pick": 2, "card": 9, "hole": 1, "colour": "Blue"}]}))
    assert failure("--file", path) == (
        "swap: card 9 is out of range (pattern has 8 cards)"
    )


def test_swap_pick_out_of_range(tmp_path):
    path = write(tmp_path, "badpick.json", json.dumps(
        {"name": "bad", "turns": "fb",
         "threading": [["Red", "White", "Red", "White"]],
         "swaps": [{"pick": 201, "card": 1, "hole": 1, "colour": "Blue"}]}))
    assert failure("--file", path) == "swap: pick 201 is out of range (1-200)"


def test_swap_hole_out_of_range(tmp_path):
    path = write(tmp_path, "badhole.json", json.dumps(
        {"name": "bad", "turns": "fb",
         "threading": [["Red", "White", "Red", "White"]],
         "swaps": [{"pick": 1, "card": 1, "hole": 5, "colour": "Blue"}]}))
    assert failure("--file", path) == "swap: hole 5 is out of range (1-4)"


# ---------------------------------------------------------------------------
# T7 - dye count section
# ---------------------------------------------------------------------------


def test_dye_header_and_cards_per_colour():
    stdout = output("--show", "dye", "--picks", "4")
    assert stdout.splitlines()[0] == "Dye count - 4 picks per round, 1 round, 8 cards"
    rows = dye_rows(stdout)
    assert rows[(1, "Red")][0] == 2
    assert rows[(1, "Ochre")][0] == 2
    assert rows[(1, "Blue")][0] == 2
    assert rows[(1, "White")][0] == 2


def test_dye_threads_count_distinct_positions_once():
    stdout = output("--show", "dye", "--picks", "4")
    rows = dye_rows(stdout)
    assert rows[(1, "Ochre")][1] == 7
    assert rows[(1, "Green")][1] == 1
    assert rows[(1, "Green")][0] == 0
    assert "Totals: cards 8, threads 32 = 8 cards x 4" in stdout


def test_dye_worked_example_at_three_picks():
    stdout = output("--show", "dye", "--picks", "3")
    lines = stdout.splitlines()
    assert lines[0] == "Dye count - 4 picks per round, 1 round, 8 cards"
    assert dye_picks_labels(stdout) == {1: "1-3"}
    rows = dye_rows(stdout)
    cards = {colour: counts[0] for (rnd, colour), counts in rows.items() if rnd == 1}
    assert cards == {"Red": 2, "Green": 1, "Ochre": 1, "Blue": 2, "White": 2}
    threads = {colour: counts[1] for (rnd, colour), counts in rows.items() if rnd == 1}
    assert threads == {"Red": 8, "Ochre": 7, "Blue": 8, "White": 8, "Green": 1}
    assert sum(threads.values()) == 32


def test_dye_final_partial_round_mammen():
    stdout = output("--pattern", "mammen", "--show", "dye", "--picks", "6")
    assert stdout.splitlines()[0] == "Dye count - 4 picks per round, 2 rounds, 5 cards"
    assert dye_picks_labels(stdout) == {1: "1-4", 2: "5-6"}


@pytest.mark.parametrize("name", ["oseberg", "birka", "hedeby", "mammen"])
@pytest.mark.parametrize("picks", ["1", "3", "4", "6", "8", "200"])
def test_thread_tally_always_equals_cards_times_four(name, picks):
    stdout = output("--pattern", name, "--show", "dye", "--picks", picks)
    cards = bb.BUILTINS[name].card_count
    rows = dye_rows(stdout)
    rounds = (int(picks) + 3) // 4
    for round_number in range(1, rounds + 1):
        threads = sum(counts[1] for (rnd, _), counts in rows.items() if rnd == round_number)
        card_total = sum(counts[0] for (rnd, _), counts in rows.items() if rnd == round_number)
        assert threads == cards * 4
        assert card_total == cards
    assert "Totals: cards %d, threads %d = %d cards x 4" % (cards, cards * 4, cards) in stdout


# ---------------------------------------------------------------------------
# T8 - --show filter and section order
# ---------------------------------------------------------------------------


def test_show_grid_prints_only_the_grid():
    stdout = output("--show", "grid")
    assert stdout.startswith("BalteusBelt - oseberg")
    assert "Legend: " in stdout
    assert "Swaps:" not in stdout
    assert "Dye count" not in stdout


def test_show_swaps_prints_only_the_swaps():
    assert output("--show", "swaps") == "Swaps:\n%s\n" % OSEBERG_SWAP_LINE


def test_show_dye_prints_only_the_dye_table():
    stdout = output("--show", "dye")
    assert stdout.startswith("Dye count")
    assert "Legend: " not in stdout
    assert "Swaps:" not in stdout


def test_default_output_orders_grid_then_swaps_then_dye():
    stdout = output()
    grid_at = stdout.index("BalteusBelt - oseberg")
    legend_at = stdout.index("Legend: ")
    swaps_at = stdout.index("Swaps:")
    dye_at = stdout.index("Dye count")
    assert grid_at < legend_at < swaps_at < dye_at


def test_show_all_is_the_default():
    assert output("--show", "all") == output()


# ---------------------------------------------------------------------------
# T9 - JSON pattern file loader
# ---------------------------------------------------------------------------


def test_json_pattern_loads_with_defaults(tmp_path):
    path = write(tmp_path, "test.json", json.dumps(
        {"name": "test", "turns": "fb",
         "threading": [["Red", "White", "Red", "White"], ["White", "Red", "White", "Red"]]}))
    lines = output("--file", path).splitlines()
    assert lines[0] == "BalteusBelt - test"
    assert lines[1] == "Weft: Linen  Cards: 2  Picks: 2  Turns: fb"
    assert "Swaps: none" in lines
    assert len(grid_rows("\n".join(lines))) == 2


def test_json_turns_charset_is_validated(tmp_path):
    path = write(tmp_path, "turns.json", json.dumps(
        {"name": "t", "turns": "fbfx",
         "threading": [["Red", "White", "Red", "White"]]}))
    assert failure("--file", path) == "turns: only f and b are allowed"


def test_json_card_needs_exactly_four_colours(tmp_path):
    path = write(tmp_path, "card.json", json.dumps(
        {"name": "t", "turns": "fb", "threading": [["Red", "White", "Red"]]}))
    assert failure("--file", path) == "threading: card 1 must have exactly 4 colours"


def test_json_unknown_key_is_rejected(tmp_path):
    path = write(tmp_path, "extra.json", json.dumps(
        {"name": "t", "turns": "fb",
         "threading": [["Red", "White", "Red", "White"]], "colours": 1}))
    assert failure("--file", path) == "unknown key: colours"


def test_json_missing_required_key(tmp_path):
    path = write(tmp_path, "missing.json", json.dumps(
        {"turns": "fb", "threading": [["Red", "White", "Red", "White"]]}))
    assert failure("--file", path) == "name: required"


def test_json_broken_syntax_reports_json_context(tmp_path):
    path = write(tmp_path, "broken.json", '{"name": "t", ')
    message = failure("--file", path)
    assert message.startswith("json: ")


# ---------------------------------------------------------------------------
# T10 - plain-text loader, auto-detection and comments
# ---------------------------------------------------------------------------


TEXT_PATTERN = """# a comment
name: demo
weft: Wool
turns: fbfb
card 1: Red White Red White
card 2: White Red White Red
swap 3 2 1 Blue
"""


def test_text_pattern_is_detected_and_loaded(tmp_path):
    path = write(tmp_path, "demo.txt", TEXT_PATTERN)
    stdout = output("--file", path)
    lines = stdout.splitlines()
    assert lines[0] == "BalteusBelt - demo"
    assert lines[1] == "Weft: Wool  Cards: 2  Picks: 4  Turns: fbfb"
    assert len(grid_rows(stdout)) == 4
    assert "pick 3  card 2  hole 1  Blue  (round 1)" in lines


def test_text_comments_and_blank_lines_are_ignored(tmp_path):
    path = write(tmp_path, "blank.txt", "\n# leading comment\n" + TEXT_PATTERN)
    proc = run("--file", path)
    assert proc.returncode == 0


def test_text_card_colour_count_names_the_line(tmp_path):
    path = write(tmp_path, "short.txt",
                 "# a comment\nname: demo\nturns: fb\ncard 1: Red White Red\n")
    assert failure("--file", path) == "line 4: card 1 must have exactly 4 colours"


def test_text_unrecognised_line_names_the_line(tmp_path):
    path = write(tmp_path, "odd.txt",
                 "name: demo\nturns: fb\ncard 1: Red White Red White\nfrobnicate: yes\n")
    assert failure("--file", path) == "line 4: unrecognised line: frobnicate: yes"


def test_detection_uses_the_first_non_blank_non_comment_character(tmp_path):
    path = write(tmp_path, "jsonish.txt", "# comment\n\n{\"name\": \"t\"\n")
    message = failure("--file", path)
    assert message.startswith("json: "), message


def test_missing_file_is_reported():
    message = failure("--file", "no-such-band.txt")
    assert message.startswith("--file: cannot read no-such-band.txt")


def test_empty_file_is_reported(tmp_path):
    path = write(tmp_path, "empty.txt", "# nothing here\n\n")
    assert failure("--file", path) == "--file: no pattern content found"


# ---------------------------------------------------------------------------
# Non-functional contract: deterministic ASCII, 80 columns, speed
# ---------------------------------------------------------------------------


def test_output_is_byte_identical_across_runs():
    assert output() == output()


def test_output_is_pure_ascii():
    for args in ([], ["--pattern", "birka"], ["--show", "dye"], ["--list-patterns"]):
        output(*args).encode("ascii")


def test_full_render_at_maximums_is_fast(tmp_path):
    import time

    cards = [["Red", "Ochre", "Blue", "White"] for _ in range(35)]
    path = write(tmp_path, "max.json", json.dumps(
        {"name": "max", "turns": "fb" * 100, "threading": cards}))
    started = time.perf_counter()
    proc = run("--file", path, "--picks", "200")
    elapsed = time.perf_counter() - started
    assert proc.returncode == 0
    assert elapsed < 2.0  # generous: the render itself is well under 100 ms


# ---------------------------------------------------------------------------
# T11 - README, --help parity and the manual smoke run
# ---------------------------------------------------------------------------


def readme_text() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_repeats_the_help_turn_convention_line():
    assert TURN_CONVENTION_LINE in readme_text()


def test_readme_documents_the_required_material():
    text = readme_text()
    for expected in ("oseberg", "birka", "hedeby", "mammen", "--pattern", "--file",
                     "--picks", "--show", "--list-patterns", "JSON", "Exit codes"):
        assert expected in text, expected


def smoke_steps():
    text = readme_text()
    block = text.split("<!-- smoke:start -->")[1].split("<!-- smoke:end -->")[0]
    steps = []
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 3 or not cells[0].isdigit():
            continue
        steps.append((int(cells[0]), cells[1].strip("`"), cells[2].strip("`")))
    return steps


def test_smoke_run_table_is_documented():
    steps = smoke_steps()
    assert [step for step, _, _ in steps] == list(range(1, len(steps) + 1))
    assert len(steps) >= 8


def test_documented_smoke_run_reproduces_every_first_line():
    for number, command, expected in smoke_steps():
        argv = shlex.split(command)
        assert argv[0] == "python3", "smoke commands start with python3"
        proc = subprocess.run(
            [sys.executable, *argv[1:]], cwd=str(ROOT), capture_output=True, text=True
        )
        if expected.startswith("error: "):
            assert proc.returncode == 2, (number, command, proc.stdout)
            assert proc.stderr.splitlines()[0] == expected, (number, command)
        else:
            assert proc.returncode == 0, (number, command, proc.stderr)
            assert proc.stdout.splitlines()[0] == expected, (number, command)
