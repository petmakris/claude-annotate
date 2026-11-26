from dataclasses import dataclass, field


@dataclass
class Line:
    sku: str
    qty: int
    unit_cents: int

    def total_cents(self) -> int:
        return self.qty * self.unit_cents


@dataclass
class Cart:
    lines: list[Line] = field(default_factory=list)

    def add(self, sku: str, qty: int, unit_cents: int) -> None:
        for line in self.lines:
            if line.sku == sku:
                line.qty += qty
                return
        self.lines.append(Line(sku, qty, unit_cents))

    def total_cents(self) -> int:
        return sum(line.total_cents() for line in self.lines)
