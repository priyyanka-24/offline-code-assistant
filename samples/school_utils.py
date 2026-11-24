GRADE_CUTOFFS = {"A": 90, "B": 80, "C": 70}   # minimum percentage for each grade


def letter_grade(percent):
    for letter, cutoff in GRADE_CUTOFFS.items():
        if percent >= cutoff:
            return letter
    return "F"


def load_marks(path):
    """Read 'name,score' lines. Exams are marked out of 50, so scores are doubled into percentages."""
    marks = {}
    with open(path) as f:
        for line in f:
            name, score = line.strip().split(",")
            marks[name] = int(score) * 2
    return marks
