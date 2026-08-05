Findings that may affect the simulator spec:

1. The "compensation may not be negative" rule is assessed over a period of at least a month, not per interval. An amendment set it that way explicitly. So individual negative-price intervals don't breach the floor as long as the monthly aggregate holds — which means the spec's per-interval max(0, α × bare + β) clamp is slightly too strict and could understate feed-in revenue during volatile months.
2. Feed-in charges may only be levied on active customers — those who actually feed in — rather than spread across all customers, and charges that are discriminatory or unrelated to feed-in are prohibited. This constrains what preset shapes are legally plausible.
