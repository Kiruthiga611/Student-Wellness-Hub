"""
Seed script for Student Mental Health Tracker.
Creates 5 test users and 10 MoodEntry records each with realistic student journal notes.
Triggers save() so TextBlob sentiment analysis runs on each note.
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mental_health_backend.settings')
django.setup()

from django.contrib.auth.models import User
from mindset_api.models import MoodEntry
from faker import Faker

fake = Faker()

# Realistic student journal notes (triggers sentiment analysis in save())
STUDENT_NOTES = [
    "Stressed about finals next week.",
    "Feeling great after the gym this morning.",
    "Lacking sleep due to coding all night.",
    "Anxious about the presentation tomorrow.",
    "Had a productive study session with friends.",
    "Overwhelmed with assignments piling up.",
    "Feeling optimistic about my project progress.",
    "Struggling to focus, need a break.",
    "Happy after getting feedback on my essay.",
    "Exhausted from back-to-back lectures.",
    "Motivated by my professor's encouragement.",
    "Lonely, missing my family back home.",
    "Proud of finishing the assignment early.",
    "Frustrated with the group project dynamics.",
    "Calm after a relaxing walk outside.",
    "Worried about my grades this semester.",
    "Excited for the weekend, no classes!",
    "Burnout kicking in, need to rest.",
    "Grateful for my study group's support.",
    "Confused about the lab instructions.",
]

def get_note(index):
    """Get a note - cycle through predefined list for realistic student journal entries."""
    return STUDENT_NOTES[index % len(STUDENT_NOTES)]


def seed():
    print("=" * 50)
    print("Seeding Student Mental Health Tracker database")
    print("=" * 50)

    # Create 5 test users
    usernames = ['StudentA', 'StudentB', 'StudentC', 'StudentD', 'StudentE']
    users = []

    for username in usernames:
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'email': f'{username.lower()}@university.edu',
                'password': 'pbkdf2_sha256$test',  # Placeholder; use set_password for real
            }
        )
        if created:
            user.set_password('testpass123')
            user.save()
            print(f"  Created user: {username}")
        else:
            print(f"  User exists: {username}")
        users.append(user)

    print(f"\nCreating 10 MoodEntry records per user (save() will run sentiment analysis)...\n")

    note_index = 0
    for user in users:
        print(f"  Seeding {user.username}...")
        for i in range(10):
            note = get_note(note_index)
            note_index += 1
            mood_value = fake.random_int(min=1, max=5)
            entry = MoodEntry(
                user=user,
                mood_value=mood_value,
                note=note,
            )
            entry.save()  # Triggers save() -> TextBlob sentiment analysis
            sent = f"{entry.sentiment_score:.3f}" if entry.sentiment_score is not None else "N/A"
            note_preview = note[:50] + "..." if len(note) > 50 else note
            print(f"    [{i+1}/10] mood={mood_value} | sentiment={sent} | \"{note_preview}\"")
        print()

    total = MoodEntry.objects.count()
    print("=" * 50)
    print(f"Done! Created {total} MoodEntry records with sentiment analysis.")
    print("=" * 50)


if __name__ == '__main__':
    seed()
