# Skill: adversarial-tests

Adapted from garden (its list was JavaScript- and SES-specific; this one is
stack-neutral). A brainstorming list of attacks on the claims a module makes. Walk it per
claim; skip categories that genuinely don't apply; when unsure, include. The stack
skills wired to your role add the attacks specific to this stack. For smart contracts,
reach for those first.

Used by the tester (to write attack tests), and by the saboteur, breaker and
corner-prober seats (to review).

## The list

### Boundary
- Empty input, one element where the code assumes zero or many, the maximum size.
- Off-by-one at indexed limits and at range edges.
- The type's minimum and maximum, and their neighbors; values that overflow,
  underflow, truncate or round to zero.
- Sentinel values (zero, the zero address/identity, max-value-as-infinity).

### Type and encoding confusion
- Missing vs explicit-null vs zero vs empty, where they mean different things.
- A value of the right shape but the wrong unit, decimals or scale.
- Mismatched encodings: packed vs padded, signed vs unsigned, big vs little endian,
  malformed or non-canonical encodings that decode to the same value.

### Hostile values and actors
- A callee that reverts, returns garbage, returns nothing, or consumes all gas/time.
- A callee or callback controlled by the attacker (a token, a hook, a receiver).
- The same actor in two roles; an actor acting on itself; an actor without authority.
- Duplicate or replayed messages, signatures or IDs.

### Reentrancy and ordering
- A callback that re-enters the function (or a sibling function) mid-operation.
- Steps the caller skips or reorders; init skipped or done twice.
- Use after close, revoke, pause or cancel; write after finalize.

### Timing and shared state
- Two operations interleaved against shared state (two users, two transactions in the
  same block, async completions out of order).
- An attacker who sees an operation before it lands and acts first or around it.
- State that is valid per call but drifts across many calls (rounding, accumulation).

## Writing an attack test

1. **Name the claim attacked:** "withdraw never pays out more than was deposited",
   not "edge case 4".
2. **State the attack** in a one-line comment.
3. **Assert the exact failure mode** the code claims: the specific error and message,
   or the exact resulting state. Never "any error".
4. **A non-failure is evidence.** If the code handles the attack, ship the test as
   defensive cover (`bus handoff builder --defensive`). If the code breaks, you've found
   a bug: that's a red test for the builder.

## Pitfalls

- **The list is endless.** Stop when the next attack tests a property the code doesn't
  claim.
- **Tests that pass for the wrong reason.** A revert from the wrong place satisfies a
  loose "expect revert". Pin the reason.
