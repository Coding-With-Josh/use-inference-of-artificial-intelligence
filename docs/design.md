# design

the value of ai is inferential. it generates candidates, not facts. the pilot model treats the user as the pilot and the ai as an instrument, with safety as a property of the whole system.

three levers:
- context lowers e (chance output is wrong in a way that matters).
- checking raises d (chance error is caught before taking effect).
- limits bound i (impact if error lands).

hypotheses:
- h1: condition c (pilot practice) produces fewer defects and fewer security findings than condition b (naive use).
- h2: condition c finishes faster than condition a (no ai) at comparable quality.
- h3: condition b shows worse confidence calibration than condition c.

conditions: a no ai, b naive ai, c pilot practice with enriched context, decomposition, guardrails, scoped authority.

four failure modes: context starvation, oracle fallacy, unverified autonomy, upstream misalignment. these map to the three levers. danger is not intrinsic to inference; it comes from authority without verification or harmful deployment.
