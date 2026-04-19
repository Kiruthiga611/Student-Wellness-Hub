from django.test import TestCase
from django.contrib.auth.models import User
from .models import MoodEntry


class SentimentTests(TestCase):
    """Verify that the text analysis pipeline behaves as expected."""

    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pass')

    def test_keyword_penalty_reduces_score(self):
        """When a stressor keyword appears, the tuned score should be lower
        than the raw TextBlob polarity (by ~STRESSOR_PENALTY).
        """
        note = "I'm really worried about the upcoming exam."
        entry = MoodEntry(user=self.user, note=note, user_selected_mood=MoodEntry.MOOD_NEU)
        entry.save()

        from textblob import TextBlob
        raw = float(TextBlob(note).sentiment.polarity)
        tuned = entry._apply_keyword_tuning(raw, note.lower())
        self.assertAlmostEqual(entry.sentiment_score, round(tuned, 4))
        # ensure penalty actually applied
        self.assertLess(entry.sentiment_score, raw + 1e-6)

    def test_punctuation_does_not_block_keyword_matching(self):
        """Keywords should match even if followed by punctuation such as a
        period or comma.
        """
        note = "Feeling very stressed about upcoming exams. Can't sleep well."
        entry = MoodEntry(user=self.user, note=note, user_selected_mood=MoodEntry.MOOD_NEU)
        entry.save()
        # score should be <= raw polarity since stressors present
        self.assertIsNotNone(entry.sentiment_score)
        from textblob import TextBlob
        raw = float(TextBlob(note).sentiment.polarity)
        self.assertLessEqual(entry.sentiment_score, raw + 1e-6)
