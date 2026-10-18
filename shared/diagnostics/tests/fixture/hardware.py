class Element:
    def __init__(self) -> None:
        self.setpoint = 0
        self.sent: list[str] = []

    def set_point(self, celsius: int) -> None:
        self.sent.append(f"set {celsius}")
        self.setpoint = celsius

    def reading(self) -> int:
        return self.setpoint
