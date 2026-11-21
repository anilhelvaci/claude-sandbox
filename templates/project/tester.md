<!-- Project notes for the tester, appended to its prompt. Delete what doesn't apply.
     This file is read-only to agents ($SBX_HOME/<name>/project/tester.md). -->

- Start each task by reading the threat model and invariants (run the x-ray skill once
  if `x-ray/` doesn't exist yet; it's a scratch path, so don't commit it).
- Unit and integration tests go in `test/`, named `<Contract>.t.sol`. Use forge-std's
  `vm.expectRevert(<CustomError>.selector)`, never a bare `vm.expectRevert()`.
- Invariants: write Foundry invariant tests (`invariant_*`) for each claimed
  invariant. Stateful fuzz suites (fizz) go in `test/fizz/`.
