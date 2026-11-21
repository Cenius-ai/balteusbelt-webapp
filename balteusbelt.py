#!/usr/bin/env python3
"""BalteusBelt - Viking tablet-weave grid, warp colour swaps and dye count.

    python3 balteusbelt.py                  # render the oseberg built-in
    python3 balteusbelt.py --help

Single file, standard library only, deterministic ASCII output, every line of a
render at most 80 columns. Exit 0 = success; exit 2 = one 'error: ...' line on
stderr and nothing on stdout.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

VERSION = "1.0.0"

WIDTH = 80
MAX_CARDS = 35  # 10-character pick/turn prefix + 2 characters per card = 80
MAX_PICKS = 200
MAX_TURNS = 200
PICKS_PER_ROUND = 4
NOT_REACHED = "        (not reached: beyond --picks)"

FALLBACK_GLYPHS = "#@%&*+=?$^~<>"
COLOUR_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
CARD_LINE_RE = re.compile(r"^card\s+([0-9]+)\s*:\s*(.*)$", re.IGNORECASE)

TURN_CONVENTION = (
    "Turn convention: pick 1 shows hole 0 face-up (no turn applied); "
    "row letter = turns[(p-1) % len(turns)]; f = +1 step, b = -1 step"
)
JSON_KEYS = ("name", "description", "weft", "turns", "threading", "swaps")
REQUIRED_JSON_KEYS = ("name", "turns", "threading")
SWAP_KEYS = ("pick", "card", "hole", "colour")


class PatternError(Exception):
    """A single user/input failure; rendered as one 'error: ...' line."""


# --- model -----------------------------------------------------------------

def round_of(pick: int) -> int:
    """Rounds are 1-based groups of four picks."""
    return (pick - 1) // PICKS_PER_ROUND + 1


def ceil_div(value: int, divisor: int) -> int:
    return -(-value // divisor)


def plural(count: int, singular: str, plural_form: str) -> str:
    return singular if count == 1 else plural_form


@dataclass(frozen=True)
class Swap:
    """One warp thread changing colour at a named pick."""

    pick: int
    card: int  # 1-based card number, as written in pattern files
    hole: int  # 0-based internal index; file hole 1 is internal hole 0
    colour: str

    @property
    def file_hole(self) -> int:
        return self.hole + 1

    @property
    def round(self) -> int:
        return round_of(self.pick)


@dataclass(frozen=True)
class Pattern:
    """A normalised pattern, whatever its source was."""

    name: str
    description: str
    weft: str
    turns: str
    threading: Tuple[Tuple[str, ...], ...]
    swaps: Tuple[Swap, ...]

    @property
    def card_count(self) -> int:
        return len(self.threading)

    @property
    def default_picks(self) -> int:
        return len(self.turns)

    def turn_letter(self, pick: int) -> str:
        return self.turns[(pick - 1) % len(self.turns)]

    def step(self, pick: int) -> int:
        return 1 if self.turn_letter(pick) == "f" else -1


@dataclass(frozen=True)
class PickState:
    """Everything derived for one rendered pick."""

    pick: int
    turn_letter: str
    visible_hole: int


# --- validators ------------------------------------------------------------

def check_colour(colour: object) -> str:
    if not isinstance(colour, str) or not COLOUR_RE.match(colour):
        raise PatternError("colour must be 1-24 ASCII letters, digits, - or _")
    return colour


def check_name(name: object) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise PatternError("name: must be 1-40 characters of A-Z a-z 0-9 - or _")
    return name


def check_description(description: object) -> str:
    if description is None:
        return ""
    if not isinstance(description, str):
        raise PatternError("description: must be text")
    if len(description) > 60:
        raise PatternError("description: must be at most 60 characters")
    if not description.isascii():
        raise PatternError("description: must be ASCII")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in description):
        raise PatternError("description: must be a single line of printable ASCII")
    return description


def check_weft(weft: object) -> str:
    if weft is None:
        return "Linen"
    if not isinstance(weft, str) or not COLOUR_RE.match(weft):
        raise PatternError("weft: must be 1-24 characters of A-Z a-z 0-9 - or _")
    return weft


def check_turns(turns: object) -> str:
    if not isinstance(turns, str):
        raise PatternError("turns: must be a string of f and b")
    if not turns:
        raise PatternError("turns: at least 1 turn is required")
    if len(turns) > MAX_TURNS:
        raise PatternError("turns: %d turns exceeds the %d-turn limit" % (len(turns), MAX_TURNS))
    if any(ch not in "fb" for ch in turns):
        raise PatternError("turns: only f and b are allowed")
    return turns


def check_threading(threading: object) -> Tuple[Tuple[str, ...], ...]:
    if not isinstance(threading, list):
        raise PatternError("threading: must be a list of cards")
    if not threading:
        raise PatternError("threading: at least 1 card is required")
    if len(threading) > MAX_CARDS:
        raise PatternError("threading: %d cards exceeds the %d-card limit for an "
                           "80-column grid" % (len(threading), MAX_CARDS))
    cards: List[Tuple[str, ...]] = []
    for card_index, card in enumerate(threading, start=1):
        if not isinstance(card, list):
            raise PatternError("threading: card %d must be a list of 4 colours" % card_index)
        if len(card) != 4:
            raise PatternError("threading: card %d must have exactly 4 colours" % card_index)
        holes: List[str] = []
        for hole_index, colour in enumerate(card, start=1):
            try:
                holes.append(check_colour(colour))
            except PatternError as exc:
                raise PatternError("threading: card %d hole %d: %s"
                                   % (card_index, hole_index, exc)) from None
        cards.append(tuple(holes))
    return tuple(cards)


def check_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PatternError("%s must be a whole number" % context)
    return value


def check_swaps(swaps: object, card_count: int) -> Tuple[Swap, ...]:
    if swaps is None:
        return ()
    if not isinstance(swaps, list):
        raise PatternError("swaps: must be a list of swaps")
    result: List[Swap] = []
    for index, raw in enumerate(swaps, start=1):
        if not isinstance(raw, dict):
            raise PatternError("swap %d: must be an object with pick, card, hole "
                               "and colour" % index)
        for key in sorted(raw):
            if key not in SWAP_KEYS:
                raise PatternError("swap %d: unknown key: %s" % (index, key))
        for key in SWAP_KEYS:
            if key not in raw:
                raise PatternError("swap %d: %s is required" % (index, key))
        pick = check_int(raw["pick"], "swap %d: pick" % index)
        card = check_int(raw["card"], "swap %d: card" % index)
        hole = check_int(raw["hole"], "swap %d: hole" % index)
        if not 1 <= pick <= MAX_PICKS:
            raise PatternError("swap: pick %d is out of range (1-%d)" % (pick, MAX_PICKS))
        if not 1 <= card <= card_count:
            raise PatternError("swap: card %d is out of range (pattern has %d cards)"
                               % (card, card_count))
        if not 1 <= hole <= 4:
            raise PatternError("swap: hole %d is out of range (1-4)" % hole)
        try:
            colour = check_colour(raw["colour"])
        except PatternError as exc:
            raise PatternError("swap %d: %s" % (index, exc)) from None
        result.append(Swap(pick=pick, card=card, hole=hole - 1, colour=colour))
    return tuple(result)


# --- built-in catalogue ----------------------------------------------------

def make_builtin(name: str, description: str, weft: str, turns: str,
                 cards: Sequence[str],
                 swaps: Sequence[Tuple[int, int, int, str]] = ()) -> Pattern:
    """Assemble a built-in through the same validators a pattern file meets."""
    threading = check_threading([card.split() for card in cards])
    raw_swaps = [{"pick": p, "card": c, "hole": h, "colour": k} for p, c, h, k in swaps]
    return Pattern(
        name=check_name(name), description=check_description(description),
        weft=check_weft(weft), turns=check_turns(turns), threading=threading,
        swaps=check_swaps(raw_swaps, len(threading)),
    )


OSEBERG_CARDS = (
    "Red Ochre Blue White", "Ochre Blue White Red", "Blue White Red Ochre",
    "White Red Ochre Blue", "Red Ochre Blue White", "Ochre Blue White Red",
    "Blue White Red Ochre", "White Red Ochre Blue",
)


def _build_catalogue() -> Dict[str, Pattern]:
    catalogue = (
        make_builtin("oseberg", "Four-colour diagonal repeat", "Linen", "fbfb",
                     OSEBERG_CARDS, ((3, 2, 1, "Green"),)),
        make_builtin("birka", "Three-colour chevron with blue flash", "Wool", "ffbbffbb",
                     ("Red White Red White", "White Black White Black",
                      "Gold Red Gold Red", "Red White Red White",
                      "White Black White Black", "Gold Red Gold Red"),
                     ((4, 3, 2, "Blue"), (6, 1, 4, "Gold"))),
        make_builtin("hedeby", "Two-colour band, red selvedge", "Linen", "ffbb",
                     ("Blue Yellow Blue Red", "Yellow Red Yellow Blue",
                      "Blue Yellow Blue Red", "Yellow Red Yellow Blue"),
                     ((5, 4, 1, "Red"),)),
        make_builtin("mammen", "Two-colour interlace, six picks", "Wool", "fffbbb",
                     ("Red Gold Red Gold", "Gold Red Gold Red", "Red Gold Red Gold",
                      "Gold Red Gold Red", "Red Gold Red Gold"),
                     ((3, 1, 4, "Black"),)),
    )
    return {pattern.name: pattern for pattern in catalogue}


BUILTINS: Dict[str, Pattern] = _build_catalogue()


def find_builtin(name: str) -> Pattern:
    key = name.lower()
    if key not in BUILTINS:
        raise PatternError("unknown pattern: %s (try --list-patterns)" % name)
    return BUILTINS[key]


# --- pattern file loaders --------------------------------------------------

def load_json_pattern(text: str) -> Pattern:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PatternError("json: %s at line %d column %d"
                           % (exc.msg, exc.lineno, exc.colno)) from None
    if not isinstance(data, dict):
        raise PatternError("pattern: JSON file must contain an object")
    for key in sorted(data):
        if key not in JSON_KEYS:
            raise PatternError("unknown key: %s" % key)
    for key in REQUIRED_JSON_KEYS:
        if key not in data:
            raise PatternError("%s: required" % key)
    threading = check_threading(data["threading"])
    return Pattern(
        name=check_name(data["name"]), description=check_description(data.get("description")),
        weft=check_weft(data.get("weft")), turns=check_turns(data["turns"]),
        threading=threading, swaps=check_swaps(data.get("swaps"), len(threading)),
    )


def _text_card(lineno: int, line: str, cards: List[List[str]]) -> None:
    match = CARD_LINE_RE.match(line)
    if not match:
        raise PatternError("line %d: unrecognised line: %s" % (lineno, line))
    number = int(match.group(1))
    if number != len(cards) + 1:
        raise PatternError("line %d: card %d is out of order (expected card %d)"
                           % (lineno, number, len(cards) + 1))
    colours = match.group(2).split()
    if len(colours) != 4:
        raise PatternError("line %d: card %d must have exactly 4 colours" % (lineno, number))
    checked: List[str] = []
    for colour in colours:
        try:
            checked.append(check_colour(colour))
        except PatternError as exc:
            raise PatternError("line %d: %s" % (lineno, exc)) from None
    cards.append(checked)


def _text_swap(lineno: int, line: str, raw_swaps: List[Dict[str, object]]) -> None:
    parts = line.split()
    if len(parts) != 5 or parts[0].lower() != "swap":
        raise PatternError("line %d: unrecognised line: %s" % (lineno, line))
    numbers: List[int] = []
    for label, token in zip(("pick", "card", "hole"), parts[1:4]):
        if not token.isdigit():
            raise PatternError("line %d: swap %s must be a whole number" % (lineno, label))
        numbers.append(int(token))
    raw_swaps.append({"pick": numbers[0], "card": numbers[1],
                      "hole": numbers[2], "colour": parts[4]})


def load_text_pattern(text: str) -> Pattern:
    name: Optional[str] = None
    description = ""
    weft: Optional[str] = None
    turns: Optional[str] = None
    cards: List[List[str]] = []
    raw_swaps: List[Dict[str, object]] = []
    seen: Dict[str, int] = {}

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lowered = line.lower()
        if lowered.startswith("card"):
            _text_card(lineno, line, cards)
            continue
        if lowered.startswith("swap"):
            _text_swap(lineno, line, raw_swaps)
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key not in ("name", "description", "weft", "turns"):
            raise PatternError("line %d: unrecognised line: %s" % (lineno, line))
        if key in seen:
            raise PatternError("line %d: duplicate %s (already set on line %d)"
                               % (lineno, key, seen[key]))
        seen[key] = lineno
        try:
            if key == "name":
                name = check_name(value)
            elif key == "description":
                description = check_description(value)
            elif key == "weft":
                weft = check_weft(value)
            else:
                turns = check_turns(value)
        except PatternError as exc:
            raise PatternError("line %d: %s" % (lineno, exc)) from None

    if name is None:
        raise PatternError("name: required")
    if turns is None:
        raise PatternError("turns: required")
    threading = check_threading(cards)
    return Pattern(name=name, description=description, weft=check_weft(weft),
                   turns=turns, threading=threading,
                   swaps=check_swaps(raw_swaps, len(threading)))


def detect_format(text: str) -> str:
    """'{' starts a JSON pattern; anything else is plain text."""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        return "json" if line.startswith("{") else "text"
    raise PatternError("--file: no pattern content found")


def load_pattern_file(path: str) -> Pattern:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise PatternError("--file: cannot read %s: %s" % (path, exc.strerror or exc)) from None
    except UnicodeDecodeError:
        raise PatternError("--file: %s is not valid UTF-8" % path) from None
    return load_json_pattern(text) if detect_format(text) == "json" else load_text_pattern(text)


def load_pattern(pattern_name: Optional[str], file_path: Optional[str]) -> Pattern:
    if pattern_name is not None and file_path is not None:
        raise PatternError("use either --pattern or --file, not both")
    if file_path is not None:
        return load_pattern_file(file_path)
    if pattern_name is not None:
        return find_builtin(pattern_name)
    return BUILTINS["oseberg"]


# --- glyphs ----------------------------------------------------------------

def ordered_colours(pattern: Pattern) -> List[str]:
    """Canonical colour order: cards in order, holes 0-3, then swap colours."""
    seen: List[str] = []
    for card in pattern.threading:
        for colour in card:
            if colour not in seen:
                seen.append(colour)
    for swap in pattern.swaps:
        if swap.colour not in seen:
            seen.append(swap.colour)
    return seen


def allocate_glyphs(colours: Sequence[str]) -> Dict[str, str]:
    """One deterministic ASCII glyph per colour."""
    used = set()
    glyphs: Dict[str, str] = {}
    for colour in colours:
        glyph = None
        for character in colour.upper():
            if character.isascii() and character.isalnum() and character not in used:
                glyph = character
                break
        if glyph is None:
            for candidate in FALLBACK_GLYPHS:
                if candidate not in used:
                    glyph = candidate
                    break
        if glyph is None:
            raise PatternError("colours: cannot allocate a unique glyph for %s "
                               "(too many distinct colours)" % colour)
        glyphs[colour] = glyph
        used.add(glyph)
    return glyphs


# --- simulation ------------------------------------------------------------

def simulate(pattern: Pattern, picks: int
             ) -> Tuple[List[Tuple[PickState, List[str]]], Dict[int, List[List[str]]]]:
    """Apply each swap before its pick renders, then record the visible colour.

    Returns the rows to render plus a snapshot of the full colour state at the
    last rendered pick of every round (used by the dye count).
    """
    cards = [list(card) for card in pattern.threading]
    swaps_at: Dict[int, List[Swap]] = {}
    for swap in pattern.swaps:
        if swap.pick <= picks:
            swaps_at.setdefault(swap.pick, []).append(swap)
    rows: List[Tuple[PickState, List[str]]] = []
    snapshots: Dict[int, List[List[str]]] = {}
    offset = 0
    for pick in range(1, picks + 1):
        for swap in swaps_at.get(pick, ()):
            cards[swap.card - 1][swap.hole] = swap.colour
        state = PickState(pick=pick, turn_letter=pattern.turn_letter(pick),
                          visible_hole=offset)
        rows.append((state, [card[offset] for card in cards]))
        if pick % PICKS_PER_ROUND == 0 or pick == picks:
            snapshots[round_of(pick)] = [list(card) for card in cards]
        offset = (offset + pattern.step(pick)) % 4
    return rows, snapshots


# --- line wrapping ---------------------------------------------------------

def wrap_words(text: str, width: int = WIDTH, indent: str = "  ") -> List[str]:
    """Greedy word wrap so even long titles and descriptions stay inside 80."""
    words = text.split()
    if not words:
        return [text]
    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = indent + word
    lines.append(current)
    return lines


def wrap_items(prefix: str, items: Sequence[str], width: int = WIDTH) -> List[str]:
    """Join items with spaces, wrapping onto lines indented under the prefix."""
    indent = " " * len(prefix)
    lines: List[str] = []
    current = prefix
    started = False
    for item in items:
        if not started:
            current = prefix + item
            started = True
            continue
        candidate = current + " " + item
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = indent + item
    lines.append(current)
    return lines


def wrap_value(prefix: str, value: str, width: int = WIDTH) -> List[str]:
    """Wrap one unbreakable value (such as a turns string) under the prefix."""
    if len(prefix) >= width:
        return [prefix + value]
    lines = [prefix + value[: width - len(prefix)]]
    rest = value[len(lines[0]) - len(prefix):]
    indent = " " * len(prefix)
    while rest:
        chunk = rest[: width - len(indent)]
        lines.append(indent + chunk)
        rest = rest[len(chunk):]
    return lines


# --- sections --------------------------------------------------------------

def grid_lines(pattern: Pattern, picks: int,
               rows: Sequence[Tuple[PickState, List[str]]],
               glyphs: Dict[str, str], colours: Sequence[str]) -> List[str]:
    title = "BalteusBelt - %s" % pattern.name
    if pattern.description:
        title += " - %s" % pattern.description
    lines = wrap_words(title)
    meta = "Weft: %s  Cards: %d  Picks: %d  Turns: " % (
        pattern.weft, pattern.card_count, picks)
    lines.extend(wrap_value(meta, pattern.turns))
    lines.append("Pick Trn  Warp (card 1 on the left)")
    for state, row_colours in rows:
        lines.append("%4d  %s   %s" % (state.pick, state.turn_letter,
                                       " ".join(glyphs[colour] for colour in row_colours)))
    lines.extend(wrap_items("Legend: ", ["%s=%s" % (glyphs[colour], colour)
                                         for colour in colours]))
    return lines


def swap_lines(pattern: Pattern, picks: int) -> List[str]:
    if not pattern.swaps:
        return ["Swaps: none"]
    lines = ["Swaps:"]
    for swap in pattern.swaps:
        lines.append("pick %d  card %d  hole %d  %s  (round %d)" % (
            swap.pick, swap.card, swap.file_hole, swap.colour, swap.round))
        if swap.pick > picks:
            lines.append(NOT_REACHED)
    return lines


def dye_lines(pattern: Pattern, picks: int,
              rows: Sequence[Tuple[PickState, List[str]]],
              snapshots: Dict[int, List[List[str]]],
              colours: Sequence[str]) -> List[str]:
    rounds = ceil_div(picks, PICKS_PER_ROUND)
    card_word = plural(pattern.card_count, "card", "cards")
    lines = ["Dye count - %d picks per round, %d %s, %d %s" % (
        PICKS_PER_ROUND, rounds, plural(rounds, "round", "rounds"),
        pattern.card_count, card_word)]
    colour_width = max([len("Colour")] + [len(colour) for colour in colours])
    lines.append("%5s  %5s  %-*s  %5s  %7s"
                 % ("Round", "Picks", colour_width, "Colour", "Cards", "Threads"))
    last_threads: Dict[str, int] = {colour: 0 for colour in colours}

    for round_number in range(1, rounds + 1):
        first_pick = (round_number - 1) * PICKS_PER_ROUND + 1
        last_pick = min(round_number * PICKS_PER_ROUND, picks)
        state = snapshots[round_number]
        face_up = rows[last_pick - 1][0].visible_hole
        cards_by_colour = {colour: 0 for colour in colours}
        threads_by_colour = {colour: 0 for colour in colours}
        for card in state:
            cards_by_colour[card[face_up]] += 1
            for colour in card:
                threads_by_colour[colour] += 1
        last_threads = threads_by_colour
        picks_label = "%d-%d" % (first_pick, last_pick)
        for colour in colours:
            if cards_by_colour[colour] == 0 and threads_by_colour[colour] == 0:
                continue
            lines.append("%5d  %5s  %-*s  %5d  %7d" % (
                round_number, picks_label, colour_width, colour,
                cards_by_colour[colour], threads_by_colour[colour]))

    initial = {colour: 0 for colour in colours}
    for card in pattern.threading:
        for colour in card:
            initial[colour] += 1
    lines.extend(wrap_items("Initial threading: ", ["%s=%d" % (colour, initial[colour])
                                                   for colour in colours if initial[colour]]))
    lines.append("Totals: cards %d, threads %d = %d %s x 4" % (
        pattern.card_count, sum(last_threads.values()), pattern.card_count, card_word))
    return lines


def render(pattern: Pattern, picks: int, show: str) -> List[str]:
    colours = ordered_colours(pattern)
    glyphs = allocate_glyphs(colours)
    rows, snapshots = simulate(pattern, picks)
    sections: List[List[str]] = []
    if show in ("grid", "all"):
        sections.append(grid_lines(pattern, picks, rows, glyphs, colours))
    if show in ("swaps", "all"):
        sections.append(swap_lines(pattern, picks))
    if show in ("dye", "all"):
        sections.append(dye_lines(pattern, picks, rows, snapshots, colours))
    lines: List[str] = []
    for index, section in enumerate(sections):
        if index:
            lines.append("")
        lines.extend(section)
    return lines


def catalogue_lines() -> List[str]:
    lines = ["BalteusBelt built-in patterns (%d):" % len(BUILTINS)]
    name_width = max(len(name) for name in BUILTINS)
    for pattern in BUILTINS.values():
        lines.append("%-*s  cards %2d  picks %3d  %s" % (
            name_width, pattern.name, pattern.card_count, pattern.default_picks,
            pattern.description))
    return lines


# --- command line surface --------------------------------------------------

HELP_EPILOG = "\n".join([
    TURN_CONVENTION,
    "",
    "Pattern files:",
    "  JSON  - an object with name, description, weft, turns, threading",
    "          (a list of cards, each a list of exactly 4 colours) and",
    "          swaps (a list of {pick, card, hole, colour}). No comments.",
    "  text  - one directive per line: name:, description:, weft:, turns:,",
    "          'card N: <four colours>' and 'swap <pick> <card> <hole>",
    "          <colour>'. Lines starting with # are comments.",
    "  The format is detected from the first non-blank non-comment",
    "  character: '{' means JSON, anything else means plain text.",
    "",
    "Exit codes:",
    "  0  success",
    "  2  input or usage error (one 'error: ...' line on stderr)",
    "",
    "Examples:",
    "  python3 balteusbelt.py",
    "  python3 balteusbelt.py --pattern birka --picks 8",
    "  python3 balteusbelt.py --file band.txt --show dye",
    "  python3 balteusbelt.py --list-patterns",
])


class BeltParser(argparse.ArgumentParser):
    """argparse with BalteusBelt's single-line error contract."""

    def error(self, message: str) -> None:  # pragma: no cover - exercised via CLI
        if message.startswith("unrecognized arguments:"):
            offending = message.split(":", 1)[1].strip().split()
            raise PatternError("unrecognised option: %s" % (offending[0] if offending else message))
        raise PatternError(message.replace("unrecognized", "unrecognised"))

    def exit(self, status: int = 0, message: Optional[str] = None) -> None:
        if message:
            sys.stderr.write(message)
        raise SystemExit(status)


def build_parser() -> argparse.ArgumentParser:
    parser = BeltParser(
        prog="balteusbelt.py",
        description=("BalteusBelt - turn a Viking tablet-weave pattern into an ASCII warp "
                     "grid, a warp colour swap schedule and a cards-per-round dye count."),
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--pattern", metavar="NAME",
                        help="render a built-in pattern (oseberg, birka, hedeby, mammen); "
                             "case-insensitive; default oseberg")
    parser.add_argument("--file", metavar="PATH",
                        help="load a pattern file (JSON or plain text, auto-detected)")
    parser.add_argument("--picks", metavar="N",
                        help="render N picks, 1-200; default is len(turns) of the pattern")
    parser.add_argument("--show", metavar="SECTION",
                        help="print one section only: grid, swaps, dye or all (default all)")
    parser.add_argument("--list-patterns", action="store_true",
                        help="list the built-in patterns with card count, default picks "
                             "and description, then exit")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    return parser


def parse_picks(raw: Optional[str], default: int) -> int:
    if raw is None:
        return default
    try:
        picks = int(raw, 10)
    except ValueError:
        raise PatternError("--picks must be a whole number between 1 and %d" % MAX_PICKS) from None
    if not 1 <= picks <= MAX_PICKS:
        raise PatternError("--picks must be between 1 and %d" % MAX_PICKS)
    return picks


def parse_show(raw: Optional[str]) -> str:
    if raw is None:
        return "all"
    value = raw.lower()
    if value not in ("grid", "swaps", "dye", "all"):
        raise PatternError("--show must be one of grid, swaps, dye, all")
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.version:
            sys.stdout.write("BalteusBelt %s\n" % VERSION)
            return 0
        if args.list_patterns:
            sys.stdout.write("\n".join(catalogue_lines()) + "\n")
            return 0
        show = parse_show(args.show)
        pattern = load_pattern(args.pattern, args.file)
        picks = parse_picks(args.picks, pattern.default_picks)
        lines = render(pattern, picks, show)
    except PatternError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 2
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
