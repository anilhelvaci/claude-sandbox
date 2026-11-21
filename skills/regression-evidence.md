# Skill: regression-evidence

Adapted from garden. Every new test must be proven **load-bearing**: it fails when the
code path it exercises is broken. A test that passes whether or not the implementation
is correct is not a regression test.

In an sbx team, the gate proves part of this mechanically: `gate red` shows the tests
fail before the builder's change, and `gate prover` shows they fail again with the
builder's production changes reverted. What the gate can't see is whether **each test**
pins **its claim**. That's this discipline, applied by the tester while writing and by
the prover seat while reviewing.

## Procedure (by hand, for one test)

1. Temporarily break the smallest unit of the code path the test covers: flip a
   comparison, drop a check, return early, change a rounding direction.
2. Run the test. It must fail with a recognizable message that names the claim.
3. Revert the break (`git stash` before breaking makes this mechanical).
4. Run it again. It must pass.

## What it catches

- A test asserting something already trivially true, never exercising the new path.
- A test that depends on another test's side effects.
- A test whose fixture doesn't exercise the pattern the new code handles.
- A test that "failed" in red only because it didn't compile, and that would pass
  against a wrong implementation once it does.

## Pitfalls

- **Keep breaks small and reversible.**
- **Property and fuzz tests** need a different demonstration: shrink the property to
  hit the boundary deterministically, or fix the seed, and show the property fails on
  the broken code.
- **"An existing test already covers this" isn't evidence** unless that test exercises
  the same failure shape. Name which shape it covers.

## Equivalence claims need a backing test

When a comment, doc or commit message says one form is "equivalent to" or "the same as"
another, that's a contract. State it as a test: compute both sides on a small input (or a
fixed seed) and assert they match with the strictest comparison available. Then break one
side and confirm the test fails.
