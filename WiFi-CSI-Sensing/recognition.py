"""Prediction state that expires on stale input, stop, model change or reconnect."""


class Recognition:
    def __init__(self):
        self.generation = 0
        self.running = False
        self.result = None
        self.updated_at = None
        self.input_end = None
        self.reason = "모델을 학습한 뒤 인식을 시작하세요."
        self.sid = self.epoch = self.model_id = None
        self.start = 0.0

    def stop(self, reason="인식을 시작하면 현재 행동이 여기에 표시됩니다."):
        self.generation += 1
        self.running = False
        self.clear(reason)

    def clear(self, reason):
        self.result = None
        self.updated_at = self.input_end = None
        self.reason = reason

    def begin(self, sid, epoch, model_id, now):
        self.stop()
        self.running = True
        self.sid, self.epoch, self.model_id, self.start = (
            sid,
            epoch,
            model_id,
            now,
        )
        self.clear("새 신호를 모으고 있습니다.")

    def observe(self, connected, sid, epoch, last_t, now):
        if not self.running:
            return False
        if not connected or sid != self.sid:
            self.stop("보드 연결이 종료되었습니다.")
            return False
        if epoch != self.epoch or last_t is None or now - last_t > 0.75:
            self.generation += 1
            self.epoch, self.start = epoch, now
            self.clear("새 신호 대기 · 수신이 끊겨 이전 결과를 지웠습니다.")
            return False
        if self.input_end is not None and now - self.input_end > 1.5:
            self.clear("최신 결과를 계산하고 있습니다.")
        return True

    def accept(self, generation, model_id, result, input_end, now):
        if (
            not self.running
            or generation != self.generation
            or model_id != self.model_id
            or now - input_end > 0.75
        ):
            return False
        self.result, self.updated_at, self.input_end = result, now, input_end
        self.reason = "실시간 인식 중"
        return True
