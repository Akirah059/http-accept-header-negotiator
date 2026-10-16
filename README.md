# http-accept-header-negotiator

Parses Accept, Accept-Language, and Accept-Encoding headers and selects the best representation by quality factor, using the standard library only.

```python
from http_accept_header_negotiator import AcceptHeaderNegotiator, negotiate

# One-shot
best = negotiate("text/html;q=0.9, application/json", ["application/json", "text/html"])

# Reuse a parsed header across multiple offer sets
neg = AcceptHeaderNegotiator("en-US,en;q=0.9,fr;q=0.8")
print(neg.select(["fr", "en"]))  # "en"
```

## Why this exists

Content negotiation is simple until it isn't. RFC 7231 mixes quality factors, specificity ordering, and parameter matching into one resolution rule that most hand-rolled parsers get subtly wrong. This library implements the parsing and selection faithfully: it respects q-value truncation to three decimal places, clamps out-of-range q-values, excludes q=0 representations, and orders matches by specificity before q-factor.

The trade-off: this library does **not** do full parameter matching for media types. It parses parameters (so `text/html;charset=utf-8` is recognized as more specific than `text/html`), but it does not compare parameter values between the Accept entry and the offered content type. If you need RFC 7231 §5.3.2 parameter matching on the server side, layer that on top.

## The awkward edge

q-values are floats. The RFC defines them as at most three decimal places, but parsing `0.333` and `0.333333` into a float gives values that compare differently than you might expect. This library truncates extra fractional digits (rather than rounding) to match common server behaviour. If you compare q-factors directly in your own code, be aware that two ranges can both have `q == 1.0` and the tie is broken by the order of your offered values, not by the header order.

## Performance

The window keeps a bounded buffer, so `push` is constant time and memory does not
grow with the length of the stream. `peak` and `trough` are linear in the window
size, which is the trade that keeps `push` cheap.

