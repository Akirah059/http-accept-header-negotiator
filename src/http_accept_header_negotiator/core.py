from __future__ import annotations

from typing import List, Tuple, Sequence, Optional


# Sentinel value for the default q-parameter. RFC 7231 §5.3.1 specifies that
# "If no Accept header field is present, then it is assumed that the client
# accepts all media types." and "If all media types are acceptable ... a
# value of 1 is assumed."
_DEFAULT_Q = 1.0

# When a q-value rounds to zero the representation is "not acceptable". We
# treat it as excluded from consideration entirely.
_Q_ZERO_THRESHOLD = 0.001


def _split_header(header_value: str) -> List[str]:
    """Split a header on commas, respecting quoted strings.

    RFC 7231 allows parameters whose values are quoted strings, and those
    strings may legally contain commas (e.g. accept-params in RFC 7231,
    though rare). Splitting naively on ',' would break such values.
    """
    parts: List[str] = []
    current = []
    in_quotes = False
    escape = False
    for ch in header_value:
        if escape:
            current.append(ch)
            escape = False
            continue
        if ch == "\\":
            current.append(ch)
            escape = True
            continue
        if ch == '"':
            current.append(ch)
            in_quotes = not in_quotes
            continue
        if ch == "," and not in_quotes:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return parts


def _strip_whitespace(parts: List[str]) -> str:
    return " ".join(parts)


class _MediaRange:
    """A single parsed media-range / language-tag / encoding token with q-factor."""

    __slots__ = ("type", "subtype", "q", "params")

    def __init__(
        self,
        type_: str,
        subtype: str,
        q: float,
        params: List[Tuple[str, str]],
    ) -> None:
        self.type = type_
        self.subtype = subtype
        self.q = q
        self.params = params


def _parse_q(value: Optional[str]) -> float:
    """Parse the q parameter into a float in [0, 1].

    RFC 7231: qvalue = ( "0" [ "." 0*3DIGIT ] ) | ( "1" [ "." 0*3("0") ] ).
    We accept up to three decimal places; extra digits are truncated, not
    rounded, to match common server behaviour and avoid float surprises.
    """
    if value is None:
        return _DEFAULT_Q
    raw = value.strip().strip('"')
    if not raw:
        return _DEFAULT_Q
    try:
        if "." in raw:
            int_part, _, frac = raw.partition(".")
            frac = frac[:3].ljust(3, "0")
            q = float(f"{int_part}.{frac}")
        else:
            q = float(raw)
    except (ValueError, TypeError):
        return _DEFAULT_Q
    if q < 0.0:
        q = 0.0
    elif q > 1.0:
        q = 1.0
    return q


def _parse_one(entry: str) -> Optional[_MediaRange]:
    """Parse a single Accept entry like 'text/html;q=0.9;charset=utf-8'."""
    entry = entry.strip()
    if not entry:
        return None
    # Split on semicolons, but keep quotes intact.
    segments: List[str] = []
    seg: List[str] = []
    in_q = False
    escape = False
    for ch in entry:
        if escape:
            seg.append(ch)
            escape = False
            continue
        if ch == "\\":
            seg.append(ch)
            escape = True
            continue
        if ch == '"':
            seg.append(ch)
            in_q = not in_q
            continue
        if ch == ";" and not in_q:
            segments.append("".join(seg))
            seg = []
            continue
        seg.append(ch)
    segments.append("".join(seg))

    media = segments[0].strip()
    if not media:
        return None
    if "/" in media:
        t, _, s = media.partition("/")
        type_ = t.strip().lower()
        subtype = s.strip().lower()
    else:
        # Accept-Language and Accept-Encoding use a bare token.
        type_ = media.lower()
        subtype = "*"
    params: List[Tuple[str, str]] = []
    q = _DEFAULT_Q
    for p in segments[1:]:
        p = p.strip()
        if not p:
            continue
        if "=" in p:
            k, _, v = p.partition("=")
            k = k.strip().lower()
            v = v.strip()
            if k == "q":
                q = _parse_q(v)
            else:
                params.append((k, v.strip('"')))
        else:
            params.append((p.lower(), ""))
    return _MediaRange(type_, subtype, q, params)


def parse_accept(header_value: str) -> List[_MediaRange]:
    """Parse an Accept / Accept-Language / Accept-Encoding header.

    Returns a list of _MediaRange objects sorted by specificity (most specific
    first), then by q-factor (highest first). This ordering mirrors RFC 7231
    §5.3.1's resolution rules: more specific ranges win over wildcards, and
    higher q-factors win within the same specificity.
    """
    ranges: List[_MediaRange] = []
    for entry in _split_header(header_value):
        parsed = _parse_one(entry)
        if parsed is not None:
            ranges.append(parsed)

    def specificity(mr: _MediaRange) -> int:
        score = 0
        if mr.type != "*":
            score += 2
        if mr.subtype != "*":
            score += 1
        # A media range with explicit parameters is more specific than one
        # without (RFC 7231 §5.3.2). We count parameter presence, not value.
        score += len(mr.params)
        return score

    ranges.sort(key=lambda mr: (-specificity(mr), -mr.q))
    return ranges


def _match_offered(offered: str, mr: _MediaRange) -> bool:
    """Check whether an offered token matches a parsed media range.

    For Accept: offered is 'type/subtype'.
    For Accept-Language / Accept-Encoding: offered is a bare token, stored as
    type with subtype '*'.
    """
    offered = offered.strip().lower()
    if "/" in offered:
        t, _, s = offered.partition("/")
        t = t.strip()
        s = s.strip()
        if mr.type != "*" and mr.type != t:
            return False
        if mr.subtype != "*" and mr.subtype != s:
            return False
        return True
    else:
        return mr.type == "*" or mr.type == offered


def negotiate(header_value: str, offered: Sequence[str]) -> Optional[str]:
    """Select the best offered representation for the given Accept header.

    If the header is empty (i.e., the client sent no Accept header), RFC 7231
    says the client accepts everything, so the first offered value is returned.

    Offers are evaluated in the order given: when two offers have the same
    q-factor and specificity, the one appearing earlier in `offered` wins.
    Returns None if no offered value is acceptable.
    """
    if not header_value.strip():
        if offered:
            return offered[0]
        return None
    ranges = parse_accept(header_value)
    acceptable = [mr for mr in ranges if mr.q >= _Q_ZERO_THRESHOLD]
    best: Optional[str] = None
    best_q = -1.0
    best_specificity = -1
    for off in offered:
        for mr in acceptable:
            if _match_offered(off, mr):
                spec = (
                    (2 if mr.type != "*" else 0)
                    + (1 if mr.subtype != "*" else 0)
                    + len(mr.params)
                )
                # Prefer higher q, then higher specificity. Ties broken by
                # order of `offered`.
                if mr.q > best_q or (
                    mr.q == best_q and spec > best_specificity
                ):
                    best_q = mr.q
                    best_specificity = spec
                    best = off
                break  # first matching range for this offer is enough
    return best


class AcceptHeaderNegotiator:
    """Parse an Accept header once, then negotiate against multiple offer sets.

    Useful when a server needs to negotiate the same header against different
    resource representations (e.g. per-route available content types).
    """

    __slots__ = ("_ranges", "_header")

    def __init__(self, header_value: str) -> None:
        self._header = header_value
        self._ranges = parse_accept(header_value)

    @property
    def ranges(self) -> List[_MediaRange]:
        return list(self._ranges)

    def select(self, offered: Sequence[str]) -> Optional[str]:
        """Return the best offered value, or None if none are acceptable."""
        if not self._header.strip():
            if offered:
                return offered[0]
            return None
        acceptable = [mr for mr in self._ranges if mr.q >= _Q_ZERO_THRESHOLD]
        best: Optional[str] = None
        best_q = -1.0
        best_specificity = -1
        for off in offered:
            for mr in acceptable:
                if _match_offered(off, mr):
                    spec = (
                        (2 if mr.type != "*" else 0)
                        + (1 if mr.subtype != "*" else 0)
                        + len(mr.params)
                    )
                    if mr.q > best_q or (
                        mr.q == best_q and spec > best_specificity
                    ):
                        best_q = mr.q
                        best_specificity = spec
                        best = off
                    break
        return best
