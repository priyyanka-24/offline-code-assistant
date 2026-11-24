class UserNotFound(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def find_user(users: list[dict], email: str) -> dict:
    """Look a user up by email (case-insensitive). Raises UserNotFound if there is none."""
    wanted = normalize_email(email)
    for u in users:
        if normalize_email(u["email"]) == wanted:
            return u
    raise UserNotFound(email)
