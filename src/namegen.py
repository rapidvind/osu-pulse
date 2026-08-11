import random

PHONETIC = [
    "Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel",
    "India", "Juliett", "Kilo", "Lima", "Mike", "November", "Oscar", "Papa",
    "Quebec", "Romeo", "Sierra", "Tango", "Uniform", "Victor", "Whiskey",
    "Xray", "Yankee", "Zulu",
]

PRODUCE = [
    "Mango", "Kiwi", "Papaya", "Guava", "Lychee", "Fig", "Plum", "Peach",
    "Cherry", "Lemon", "Lime", "Melon", "Grape", "Olive", "Kale", "Beet",
    "Carrot", "Pepper", "Radish", "Turnip", "Onion", "Garlic", "Ginger",
    "Chili", "Broccoli", "Spinach", "Pumpkin", "Squash", "Cabbage", "Celery",
    "Parsnip", "Leek", "Yam", "Okra", "Basil", "Apricot", "Coconut",
]


def random_session_name():
    return f"{random.choice(PHONETIC)}-{random.choice(PRODUCE)}"
