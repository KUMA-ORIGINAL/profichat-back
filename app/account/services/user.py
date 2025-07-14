import uuid


def generate_unique_username():
    return f"user_{uuid.uuid4().hex[:10]}"
