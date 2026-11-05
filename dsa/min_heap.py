class MinHeap:
    def __init__(self):
        self.heap = []

    def parent(self, index):
        return (index - 1) // 2

    def left_child(self, index):
        return 2 * index + 1

    def right_child(self, index):
        return 2 * index + 2

    def _get_cost(self, item):
        return item["response_cost"]

    def insert(self, item):
        self.heap.append(item)
        self._heapify_up(len(self.heap) - 1)

    def _heapify_up(self, index):
        while index > 0:

            parent_index = self.parent(index)

            if (
                self._get_cost(self.heap[index])
                >= self._get_cost(self.heap[parent_index])
            ):
                break

            self.heap[index], self.heap[parent_index] = (
                self.heap[parent_index],
                self.heap[index]
            )

            index = parent_index

    def peek(self):
        if not self.heap:
            return None

        return self.heap[0]

    def extract_min(self):
        if not self.heap:
            return None

        if len(self.heap) == 1:
            return self.heap.pop()

        minimum = self.heap[0]

        self.heap[0] = self.heap.pop()

        self._heapify_down(0)

        return minimum

    def _heapify_down(self, index):

        while True:

            left = self.left_child(index)
            right = self.right_child(index)

            smallest = index

            if (
                left < len(self.heap)
                and self._get_cost(self.heap[left])
                < self._get_cost(self.heap[smallest])
            ):
                smallest = left

            if (
                right < len(self.heap)
                and self._get_cost(self.heap[right])
                < self._get_cost(self.heap[smallest])
            ):
                smallest = right

            if smallest == index:
                break

            self.heap[index], self.heap[smallest] = (
                self.heap[smallest],
                self.heap[index]
            )

            index = smallest

    def get_size(self):
        return len(self.heap)