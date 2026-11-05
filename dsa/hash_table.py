class HashNode:
    def __init__(self, key, value):
        self.key = key
        self.value = value
        self.next = None


class HashTable:
    def __init__(self, capacity=211):
        self.capacity = capacity
        self.size = 0
        self.table = [None] * capacity

    def _hash(self, key):
        key_string = str(key)

        hash_value = 0

        for character in key_string:
            hash_value = (hash_value * 31 + ord(character)) % self.capacity

        return hash_value

    def insert(self, key, value):
        index = self._hash(key)

        current = self.table[index]

        while current is not None:
            if current.key == key:
                current.value = value
                return

            current = current.next

        new_node = HashNode(key, value)

        new_node.next = self.table[index]
        self.table[index] = new_node

        self.size += 1

    def search(self, key):
        index = self._hash(key)

        current = self.table[index]

        while current is not None:
            if current.key == key:
                return current.value

            current = current.next

        return None

    def update(self, key, value):
        index = self._hash(key)

        current = self.table[index]

        while current is not None:
            if current.key == key:
                current.value = value
                return True

            current = current.next

        return False

    def delete(self, key):
        index = self._hash(key)

        current = self.table[index]
        previous = None

        while current is not None:

            if current.key == key:

                if previous is None:
                    self.table[index] = current.next
                else:
                    previous.next = current.next

                self.size -= 1
                return True

            previous = current
            current = current.next

        return False

    def get_size(self):
        return self.size