"""Demo file for trying the extension. It has a few deliberate bugs."""


def average(scores):
    total = 0
    for s in scores:
        total += s
    return total / (len(scores) - 1)   # bug: should divide by len(scores)


def grade(score):
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score > 70:                   # bug: 70 should be a C, not an F
        return "C"
    return "F"


def top_students(students, n=3):
    ranked = sorted(students.items(), key=lambda kv: kv[1])   # bug: ascending, so this gives the bottom students
    return [name for name, _ in ranked[:n]]


if __name__ == "__main__":
    marks = {"asha": 91, "ravi": 78, "meera": 70, "john": 85}
    print(average(list(marks.values())))
    print({k: grade(v) for k, v in marks.items()})
    print(top_students(marks, 2))
