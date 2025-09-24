import time


# ==============================================================
class HeartMemory:
    def __init__(self, time_length):
        self.memory = {"hr": [], "time": []}
        self.time_length = time_length
        self.min_hr, self.max_hr, self.mean_hr = None, None, None

    @property
    def is_empty(self):
        return self.min_hr is None

    def drop_first(self):
        assert len(self.memory['hr']) > 0, "HeartMemory is empty."
        self.memory['hr'].pop(0)
        self.memory['time'].pop(0)

    def append(self, heart_rate):
        current_time = time.time()
        self.memory['hr'].append(heart_rate)
        self.memory['time'].append(current_time)
        if current_time - min(self.memory['time']) > self.time_length:
            self.drop_first()
        self.mean_hr = sum(self.memory['hr'])/len(self.memory['hr'])
        self.min_hr = min(self.memory['hr'])
        self.max_hr = max(self.memory['hr'])
