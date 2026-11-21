<!-- Project notes for the builder, appended to its prompt. Delete what doesn't apply.
     This file is read-only to agents ($SBX_HOME/<name>/project/builder.md). -->

- Prefer the OpenZeppelin primitives already used in this repo over hand-rolled code
  (access control, reentrancy guards, SafeERC20, Math.mulDiv with explicit rounding).
- Checks-effects-interactions in every external function that calls out.
- Custom errors, not revert strings.
