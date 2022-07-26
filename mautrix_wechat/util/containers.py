class SizedDict(dict):
    def __init__(self, *args, **kwds):
        self.maxlen = kwds.pop("maxlen", None)
        super().__init__(*args, **kwds)
        self._check_size_limit()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._check_size_limit()

    def _check_size_limit(self):
        if self.maxlen is not None:
            while len(self) > self.maxlen:
                self.popitem()