"""
Hand-written data structures used by the /api/top endpoint (no heapq, Counter, sorted, sort_values ...).

  HashCounter : separate-chaining hash table  key -> count
  MinHeap     : binary min-heap of (count, key) with manual sift_up / sift_down
  top_k       : streams the counter through a size-K min-heap and returns the K largest, descending

Complexity (n = rows streamed, m = distinct keys, K = result size)
  counting      O(n) expected time, O(m) space
  heap pass     O(m log K) time, O(K) space
  final order   O(K log K)  (K pops from the heap, then a manual reversal)
  total         O(n + m log K) time, O(m + K) space
"""


class HashCounter:
    def __init__(self, capacity=1024):
        self._buckets = [None] * capacity
        self._cap = capacity
        self._size = 0

    def _index(self, key):
        return (key * 2654435761) % self._cap            # Knuth multiplicative hash (integer keys)

    def increment(self, key, by=1):
        i = self._index(key)
        node = self._buckets[i]
        while node is not None:                          # walk the chain
            if node[0] == key:
                node[1] += by
                return
            node = node[2]
        self._buckets[i] = [key, by, self._buckets[i]]   # push-front new node [key, count, next]
        self._size += 1
        if self._size > 0.75 * self._cap:
            self._resize()

    def _resize(self):
        old = self._buckets
        self._cap *= 2
        self._buckets = [None] * self._cap
        for head in old:
            node = head
            while node is not None:
                nxt = node[2]
                i = self._index(node[0])
                node[2] = self._buckets[i]
                self._buckets[i] = node
                node = nxt

    def __len__(self):
        return self._size

    def items(self):
        for head in self._buckets:
            node = head
            while node is not None:
                yield node[0], node[1]
                node = node[2]


def _less(a, b):
    """(count, key) ordering: smaller count first; ties broken by larger key being 'smaller' (stable output)."""
    if a[0] != b[0]:
        return a[0] < b[0]
    return a[1] > b[1]


class MinHeap:
    def __init__(self):
        self.data = []

    def __len__(self):
        return len(self.data)

    def peek(self):
        return self.data[0]

    def push(self, item):
        self.data.append(item)
        self._sift_up(len(self.data) - 1)

    def pop(self):
        top = self.data[0]
        last = self.data.pop()
        if self.data:
            self.data[0] = last
            self._sift_down(0)
        return top

    def replace_root(self, item):
        self.data[0] = item
        self._sift_down(0)

    def _sift_up(self, i):
        d = self.data
        while i > 0:
            parent = (i - 1) // 2
            if _less(d[i], d[parent]):
                d[i], d[parent] = d[parent], d[i]
                i = parent
            else:
                break

    def _sift_down(self, i):
        d, n = self.data, len(self.data)
        while True:
            l, r, smallest = 2 * i + 1, 2 * i + 2, i
            if l < n and _less(d[l], d[smallest]):
                smallest = l
            if r < n and _less(d[r], d[smallest]):
                smallest = r
            if smallest == i:
                return
            d[i], d[smallest] = d[smallest], d[i]
            i = smallest


def top_k(pairs, k):
    """pairs: iterable of (key, count). Returns [(key, count), ...] largest first."""
    heap = MinHeap()
    for key, count in pairs:
        item = (count, key)
        if len(heap) < k:
            heap.push(item)
        elif _less(heap.peek(), item):      # beats the current K-th best -> replace it
            heap.replace_root(item)
    ascending = []
    while len(heap):
        ascending.append(heap.pop())
    result = []
    for i in range(len(ascending) - 1, -1, -1):          # manual reverse -> descending
        count, key = ascending[i]
        result.append((key, count))
    return result
