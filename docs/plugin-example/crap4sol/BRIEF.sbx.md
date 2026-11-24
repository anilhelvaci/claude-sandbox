crap4sol scores each changed function: CRAP = CC² × (1 − coverage)³ + CC, from Slither's
cyclomatic complexity and `forge coverage` line coverage. The gate fails (finding) when any
function scores above 8.0. Fix it by covering the function's branches with tests (the
tester's job: message them or escalate) or by splitting the function into simpler ones.
The table in the gate log lists each function's CC, coverage and score, worst first.
