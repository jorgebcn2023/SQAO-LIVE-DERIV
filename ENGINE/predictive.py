"""Rule-based conditional 60-minute scenario engine.

Scores are MODEL_ESTIMATE, not historical win rates.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Iterable

@dataclass
class Scenario:
    name: str
    direction: str
    score: float
    trigger: str
    invalidation: str
    projection: str
    def to_dict(self):
        return asdict(self)

def normalize_scores(values: Iterable[float]) -> list[float]:
    vals = [max(0.0, float(v)) for v in values]
    total = sum(vals)
    return [round(100.0*v/total, 1) for v in vals] if total else [0.0 for _ in vals]

def build_hour_scenarios(d1_bearish: bool, m15_bearish: bool, m5_bearish: bool,
                         support_holds=False, breakout_confirmed=False,
                         recovery_confirmed=False, extended_impulse=True):
    short = 2.0 + d1_bearish + m15_bearish + 0.8*m5_bearish
    bounce = 1.4 + 0.7*support_holds + 0.5*extended_impulse + 0.5*recovery_confirmed
    range_score = 0.8 + 0.4*(not breakout_confirmed and not recovery_confirmed)
    if breakout_confirmed: short += 2.0
    if recovery_confirmed:
        bounce += 1.6
        short *= 0.75
    scores = normalize_scores([short, bounce, range_score])
    return [
        Scenario("Continuación bajista", "SHORT", scores[0],
                 "Ruptura del soporte crítico + cierre + retest fallido",
                 "Recuperación sostenida de la resistencia de invalidación",
                 "Extensión hacia la siguiente liquidez; sin distancia fija"),
        Scenario("Rebote técnico", "LONG", scores[1],
                 "Defensa del soporte + mínimo superior + recuperación de resistencia",
                 "Nuevo mínimo confirmado bajo el soporte",
                 "Recuperación hacia resistencias sucesivas"),
        Scenario("Lateralización", "WAIT", scores[2],
                 "Precio permanece entre soporte y resistencia sin confirmación",
                 "Ruptura confirmada de cualquiera de los extremos",
                 "Rango; evitar persecución de micro-rupturas"),
    ]
