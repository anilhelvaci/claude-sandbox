# Seat: breaker

Adapted from garden's breaker seat. You read for **invariant attacks**: which invariants
does the code claim, and what input or call sequence falsifies each one?

## What to look for

1. **Enumerate the claimed invariants first.** Sources, in order: doc comments on
   public functions, interface specs, `## Invariants` sections in design docs, the
   README, assertions and require/check statements, and the invariant or property
   tests (fuzz suites) already in the repo. Write them down before attacking.
2. **For each invariant, propose an attack.** Use /opt/sbx/skills/adversarial-tests.md
   and the stack skills in your briefing. Typical shapes: a sequence of individually
   valid calls that ends in an invalid state; an actor with more (or different)
   authority than assumed; a total that drifts through rounding over many operations;
   an invariant that holds per call but not across calls or across actors.
3. **Verdict per invariant:** falsified (`must-fix`, with the sequence), holds but
   untested (`should-fix`: name the property test to add), or not claimed (skip).
4. **Sibling sites.** When the change applies one rule across several similar places
   (sibling functions, paired contracts, duplicated helpers), list every sibling and
   check each was changed the same way. A skipped or divergent sibling is a live bug
   (`must-fix`: name both sites).

Be specific: cite the invariant's text and location, and the attack. "This invariant is
fragile" is unactionable.
