from school_utils import letter_grade, load_marks


def class_report(path):
    marks = load_marks(path)
    passed = [name for name, p in marks.items() if letter_grade(p) != "F"]
    return f"{len(passed)}/{len(marks)} students passed"


def scholarship(path):
    """Students who scored at least 45 out of 50 in the exam get a scholarship."""
    marks = load_marks(path)
    return [name for name, score in marks.items() if score >= 45]
