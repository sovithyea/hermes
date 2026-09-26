"""Speaker-accuracy check for Pride & Prejudice Chapter I (hermes chapter 2).

Usage: uv run python tests/eval_pp_ch1.py
Gold = sequence of speakers for every real dialogue line, in order.
"""
from hermes.store import BookProject

M, F = "Mr. Bennet", "Mrs. Bennet"
GOLD = [F, F, F, F, F, M, F, M, F, M, F, M, F, F, M, F, M, F, M, F, M, F, M, F, M, M, F, M, F, M, F, M]

lines = [l for l in BookProject("pride-and-prejudice").load_script(2)
         if l.type == "dialogue" and "came down to see the place" not in l.text]  # illustration caption
got = [l.speaker for l in lines]
wrong = [(l.id, l.speaker, g, l.text[:50]) for l, g in zip(lines, GOLD) if l.speaker != g]
print(f"{len(GOLD) - len(wrong)}/{len(GOLD)} correct (lines found: {len(got)})")
for w in wrong:
    print("  WRONG", *w)
