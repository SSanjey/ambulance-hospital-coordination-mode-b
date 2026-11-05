class MaxHeap:
    def __init__(self):
        self.heap = []

    def parent(self, index):
        return (index - 1) // 2

    def left_child(self, index):
        return 2 * index + 1

    def right_child(self, index):
        return 2 * index + 2

    def _get_priority(self, item):
        return item["priority"]

    def insert(self, item):
        self.heap.append(item)
        self._heapify_up(len(self.heap) - 1)

    def _heapify_up(self, index):
        while index > 0:
            parent_index = self.parent(index)

            if self._get_priority(self.heap[index]) <= self._get_priority(self.heap[parent_index]):
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

    def extract_max(self):
        if not self.heap:
            return None

        if len(self.heap) == 1:
            return self.heap.pop()

        maximum = self.heap[0]

        self.heap[0] = self.heap.pop()
        self._heapify_down(0)

        return maximum

    def _heapify_down(self, index):
        while True:
            left = self.left_child(index)
            right = self.right_child(index)
            largest = index

            if (
                left < len(self.heap)
                and self._get_priority(self.heap[left])
                > self._get_priority(self.heap[largest])
            ):
                largest = left

            if (
                right < len(self.heap)
                and self._get_priority(self.heap[right])
                > self._get_priority(self.heap[largest])
            ):
                largest = right

            if largest == index:
                break

            self.heap[index], self.heap[largest] = (
                self.heap[largest],
                self.heap[index]
            )

            index = largest