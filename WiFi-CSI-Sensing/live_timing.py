"""Wait for paced device timestamps before exposing serial data as live."""


class LiveClock:
    def __init__(self, warmup=2.0, stable_seconds=1.0):
        self.warmup, self.stable_seconds = warmup, stable_seconds
        self.previous = self.anchor = None
        self.offset = None
        self.ready = False
        self.epoch = 0
        self.message = "USB 버퍼 정리 · 새 신호 시간 확인 중"

    def map_time(self, device, arrival):
        if self.previous is not None:
            previous_device, previous_arrival = self.previous
            dt, da = device - previous_device, arrival - previous_arrival
            if dt <= 0 or dt > 0.5 or abs(dt - da) > 0.25:
                self.anchor = None
                self.ready = False
                self.epoch += 1
        self.previous = (device, arrival)
        if self.anchor is None:
            self.anchor = (device, arrival)
        if self.ready and abs(arrival - (device + self.offset)) > 0.25:
            self.anchor = (device, arrival)
            self.ready = False
            self.epoch += 1
        if not self.ready:
            device_span, arrival_span = (
                device - self.anchor[0],
                arrival - self.anchor[1],
            )
            if abs(device_span - arrival_span) > 0.15:
                self.anchor = (device, arrival)
                arrival_span = 0
            if arrival < self.warmup or arrival_span < self.stable_seconds:
                return None
            self.offset = arrival - device
            self.ready = True
            self.message = "장치 시간 동기화 완료"
        return device + self.offset
