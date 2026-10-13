"""python backend/test_algorithms.py  - checks the hand-written code against Python built-ins."""
import random
from collections import Counter
from algorithms import HashCounter, top_k

random.seed(1)
data = [random.randint(1, 3000) for _ in range(200_000)]
hc = HashCounter(8)
for x in data:
    hc.increment(x)
ref = Counter(data)
assert dict(hc.items()) == dict(ref) and len(hc) == len(ref)
for k in (1, 5, 20, 5000):
    mine = top_k(hc.items(), k)
    expected = sorted(ref.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
    assert mine == expected, k
assert top_k([], 5) == []
print("all algorithm tests passed")
