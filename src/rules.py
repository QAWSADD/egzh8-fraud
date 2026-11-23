"""Auditable validation, watchlist rules and calibrated-score decisions."""

VISA = "Visa Anti-Enumeration and Account Testing Best Practices for Merchants"
DATA = "MLG-ULB benchmark and project input schema"
POLICY = "Educational review policy"
MODEL = "Cost-sensitive threshold on chronological validation"
BENCHMARK_SECONDS = 172800

CATALOG = {
    "R1": ("validation", "Проверьте структуру и типы полей.", DATA),
    "R2": ("validation", "Сумма должна быть от 0 до 100 000 000.", DATA),
    "R3": ("validation", "Время должно быть целым неотрицательным числом секунд.", DATA),
    "R4": ("validation", "Для модели предусмотрено 28 анонимных компонентов.", DATA),
    "R5": ("validation", "Число операций за 10 минут должно быть от 1 до 10 000.", POLICY),
    "R6": ("validation", "Интервал от предыдущей операции задан неверно.", POLICY),
    "R7": ("validation", "Интервал до предыдущей операции не согласуется с числом операций за 10 минут.", POLICY),
    "R8": ("validation", "Компоненты V1–V28 должны быть числами или пустыми значениями.", DATA),
    "R9": ("hard", "Есть совпадение с учебным списком наблюдения.", POLICY),
    "R10": ("hard", "Высокая частота и короткий интервал между операциями.", VISA),
    "R11": ("hard", "Необычно крупная сумма сочетается с высокой частотой.", VISA),
    "R12": ("hard", "Для оценки моделью недостаточно анонимных компонентов.", DATA),
    "R13": ("post", "Оценка модели близка к порогу. Нужна ручная проверка.", MODEL),
    "R14": ("post", "Оценка модели выше порога. Операцию стоит проверить.", MODEL),
    "R15": ("post", "Оценка модели ниже порога, дополнительных сигналов нет.", MODEL),
    "R16": ("post", "Сумма выше 99,5-го процентиля обучающей выборки.", VISA),
    "R17": ("post", "Время выходит за пределы двухдневного периода учебных данных.", DATA),
    "R18": ("post", "Короткий интервал с предыдущей операцией.", VISA),
    "R19": ("post", "Повышенное число операций в десятиминутном окне.", VISA),
    "R20": ("post", "Пропущенные компоненты заменены медианами обучающей выборки.", DATA),
}


def hit(code):
    group, reason, source = CATALOG[code]
    return {"id": code, "group": group, "reason": reason, "source": source}


def before(tx, stats):
    count, gap = tx["count_10m"], tx["seconds_since_previous"]
    if count is not None and gap is not None and ((count > 1) != (gap <= 600)):
        return "invalid", [hit("R7")]
    if tx["watchlist_match"]:
        return "flagged", [hit("R9")]
    if count is not None and count >= 8 and gap is not None and gap <= 6:
        return "flagged", [hit("R10")]
    if count is not None and count >= 8 and tx["amount"] >= stats["extreme_amount"]:
        return "flagged", [hit("R11")]
    if sum(value is not None for value in (tx["components"] or ())) < 21:
        return "review", [hit("R12")]
    return None, []


def after(tx, score, stats):
    threshold, width = stats["threshold"], stats["review_width"]
    trace = []
    if any(value is None for value in tx["components"]):
        trace.append(hit("R20"))
    signals = [
        (tx["amount"] >= stats["high_amount"], "R16"),
        (tx["time"] > BENCHMARK_SECONDS, "R17"),
        (tx["seconds_since_previous"] is not None and tx["seconds_since_previous"] <= 10, "R18"),
        (tx["count_10m"] is not None and tx["count_10m"] >= 5, "R19"),
    ]
    warnings = [hit(code) for condition, code in signals if condition]
    if abs(score - threshold) <= width:
        return "review", [hit("R13"), *warnings, *trace]
    if score >= threshold:
        return "flagged", [hit("R14"), *warnings, *trace]
    if warnings:
        return "review", warnings + trace
    return "clear", [hit("R15"), *trace]
