"""stats.py — the small amount of distribution math we need, stdlib only.

No scipy / numpy: everything here is exact-enough arithmetic built on
``math.lgamma`` and ``math.erf`` so the project stays dependency-free
(and PyInstaller-able) exactly like v1.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Sequence, Tuple

SQRT2 = math.sqrt(2.0)
LOG_2 = math.log(2.0)


# ------------------------------------------------------------------ normal
def norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / SQRT2))


def norm_sf(z: float) -> float:
    """P(Z > z)."""
    return 1.0 - norm_cdf(z)


# ---------------------------------------------------------------- binomial
def binom_log_pmf(k: int, n: int, p: float) -> float:
    if k < 0 or k > n:
        return -math.inf
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    lnc = (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1))
    return lnc + k * math.log(p) + (n - k) * math.log1p(-p)


def binom_pmf(k: int, n: int, p: float) -> float:
    return math.exp(binom_log_pmf(k, n, p))


def binom_sf_ge(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p).

    Exact summation for tractable n; normal approximation with a continuity
    correction beyond that (n > 5000), which is plenty accurate for our use.
    """
    if n <= 0:
        return 0.0
    k = max(0, min(int(k), n + 1))
    if k > n:
        return 0.0
    if k == 0:
        return 1.0
    if n > 5000:
        mu, sd = n * p, math.sqrt(n * p * (1 - p))
        if sd <= 0:
            return 0.0 if mu < k else 1.0
        return norm_sf((k - 0.5 - mu) / sd)
    # Sum from the smaller tail for speed & stability.
    total = 0.0
    for i in range(k, n + 1):
        total += math.exp(binom_log_pmf(i, n, p))
        if total >= 1.0:
            return 1.0
    return min(1.0, total)


def binom_test_greater(hits: int, n: int, p0: float) -> float:
    """One-sided exact binomial p-value for H1: p > p0."""
    if n <= 0:
        return 1.0
    return binom_sf_ge(hits, n, p0)


# ------------------------------------------------------------------- beta
def beta_mean(a: float, b: float) -> float:
    return a / (a + b)


def beta_var(a: float, b: float) -> float:
    s = a + b
    return (a * b) / (s * s * (s + 1.0))


def prob_greater_normal(a1: float, b1: float, a2: float, b2: float) -> float:
    """P(theta1 > theta2) for two independent Beta posteriors.

    Normal approximation to the Beta difference — accurate once each arm has
    a handful of observations, and it keeps us dependency-free.
    """
    m1, v1 = beta_mean(a1, b1), beta_var(a1, b1)
    m2, v2 = beta_mean(a2, b2), beta_var(a2, b2)
    sd = math.sqrt(max(v1 + v2, 1e-12))
    return norm_cdf((m1 - m2) / sd)


def wilson_interval(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval for a proportion (better than Wald near 0/1)."""
    if n <= 0:
        return (0.0, 1.0)
    ph = k / n
    d = 1 + z * z / n
    c = ph + z * z / (2 * n)
    h = z * math.sqrt(max(ph * (1 - ph) / n + z * z / (4 * n * n), 0.0))
    return ((c - h) / d, (c + h) / d)


# --------------------------------------------------------------- sequences
def mean(xs: Iterable[float]) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def stdev(xs: Iterable[float]) -> float:
    xs = list(xs)
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def max_drawdown(curve: Sequence[float]) -> Tuple[float, float]:
    """Return (max_drawdown_absolute, max_drawdown_fraction) of a bankroll curve."""
    peak = -math.inf
    worst_abs = 0.0
    worst_frac = 0.0
    for v in curve:
        peak = max(peak, v)
        dd = peak - v
        if dd > worst_abs:
            worst_abs = dd
            if peak > 0:
                worst_frac = dd / peak
    return worst_abs, worst_frac


def entropy_bits(probs: Iterable[float]) -> float:
    h = 0.0
    for p in probs:
        if p > 0:
            h -= p * math.log(p) / LOG_2
    return h


def cross_entropy_bits(predicted: Dict[str, float], actual_counts: Dict[str, float]) -> float:
    tot = sum(actual_counts.values())
    if tot <= 0:
        return 0.0
    ce = 0.0
    for sym, c in actual_counts.items():
        p = max(predicted.get(sym, 1e-12), 1e-12)
        ce -= (c / tot) * math.log(p) / LOG_2
    return ce


def chi_square_uniform(counts: Dict[str, float], n: float, k: int) -> float:
    """Chi-square statistic against a uniform distribution (df = k - 1)."""
    if n <= 0 or k <= 1:
        return 0.0
    exp = n / k
    return sum((counts.get(s, 0.0) - exp) ** 2 / exp for s in counts)


def chi_square_sf(x: float, df: int) -> float:
    """Survival function of chi-square via the regularised upper incomplete
    gamma (series / continued fraction). Stdlib only."""
    if x <= 0 or df <= 0:
        return 1.0
    return _q_gamma(df / 2.0, x / 2.0)


def chi_square_sf_fast(x: float, df: int) -> float:
    """Wilson-Hilferty approximation to the chi-square survival function.

    O(1) and accurate to ~1e-3 for small df, which is all the walk-forward
    gate needs; the exact ``chi_square_sf`` is used for displayed numbers.
    """
    if x <= 0 or df <= 0:
        return 1.0
    z = ((x / df) ** (1.0 / 3.0) - (1.0 - 2.0 / (9.0 * df))) / math.sqrt(2.0 / (9.0 * df))
    return norm_sf(z)


def _q_gamma(a: float, x: float) -> float:
    """Regularised upper incomplete gamma Q(a, x)."""
    if x < a + 1.0:
        return 1.0 - _p_gamma_series(a, x)
    return _q_gamma_cf(a, x)


def _p_gamma_series(a: float, x: float, itmax: int = 300, eps: float = 3e-16) -> float:
    if x <= 0:
        return 0.0
    ap = a
    s = 1.0 / a
    d = s
    for _ in range(itmax):
        ap += 1.0
        d *= x / ap
        s += d
        if abs(d) < abs(s) * eps:
            break
    return s * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _q_gamma_cf(a: float, x: float, itmax: int = 300, eps: float = 3e-16) -> float:
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, itmax + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h * math.exp(-x + a * math.log(x) - math.lgamma(a))


def z_to_stars(p: float) -> str:
    """Human-readable significance marker."""
    if p <= 0.001:
        return "***"
    if p <= 0.01:
        return "**"
    if p <= 0.05:
        return "*"
    if p <= 0.10:
        return "."
    return "ns"


def running_accuracy(hits: Sequence[bool]) -> List[float]:
    """Cumulative hit rate curve (for the learning-curve chart)."""
    out: List[float] = []
    k = 0
    for i, h in enumerate(hits, 1):
        k += 1 if h else 0
        out.append(100.0 * k / i)
    return out
