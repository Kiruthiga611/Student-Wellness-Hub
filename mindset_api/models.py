from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from datetime import timedelta, time
import json
from django.core.mail import send_mail
from django.conf import settings

import random
from django.db.models import Q
import re


# ==================== ACADEMIC CALENDAR ====================

class AcademicEvent(models.Model):
    """
    Academic Calendar Events for Context-Aware Insights.
    
    Tracks academic periods (exams, deadlines, breaks) to provide
    context-aware recommendations and understand student stress patterns.
    """
    event_name = models.CharField(
        max_length=200,
        help_text="Name of the academic event (e.g., 'Final Exams', 'Project Deadline')"
    )
    start_date = models.DateField(
        help_text="Event start date"
    )
    end_date = models.DateField(
        help_text="Event end date"
    )
    description = models.TextField(
        blank=True,
        help_text="Optional event description"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_active_on(self, check_date=None):
        """Check if this event is active on a given date."""
        if check_date is None:
            check_date = timezone.now().date()
        return self.start_date <= check_date <= self.end_date

    def __str__(self):
        return f"{self.event_name} ({self.start_date} to {self.end_date})"

    class Meta:
        ordering = ['start_date']
        verbose_name = 'Academic Event'
        verbose_name_plural = 'Academic Events'
        indexes = [
            models.Index(fields=['start_date', 'end_date']),
        ]


# ==================== MENTAL HEALTH TRACKING ====================

class MoodEntry(models.Model):
    """
    Mental Health Mood Entry — Data Fusion Engine.

    Combines three signals to produce reliable DAS levels:

      Layer 1 – TextBlob AI:          raw sentiment polarity from free-text note
      Layer 2 – Keyword tuning:       academic stressor words lower the score by 0.2,
                                      catching neutral sentences like "I have an exam"
                                      that TextBlob otherwise scores as 0.0
      Layer 3 – Ground-truth gate:    if AI is still neutral (−0.1 … +0.1) but the
                                      student explicitly chose ANX or STR, the user's
                                      explicit selection overrides AI to set the
                                      relevant DAS level to 'High'

    This three-layer approach means DAS fields are NEVER empty:
    if there is no note at all, the user_selected_mood alone drives the levels.
    """

    # ── Mood choice constants ─────────────────────────────────────────
    MOOD_SAD = 'SAD'
    MOOD_ANX = 'ANX'
    MOOD_STR = 'STR'
    MOOD_HAP = 'HAP'
    MOOD_NEU = 'NEU'

    MOOD_CHOICES = [
        (MOOD_SAD, 'Sad / Low'),
        (MOOD_ANX, 'Anxious'),
        (MOOD_STR, 'Stressed'),
        (MOOD_HAP, 'Happy'),
        (MOOD_NEU, 'Neutral'),
    ]

    DAS_CHOICES = [
        ('Low',      'Low'),
        ('Moderate', 'Moderate'),
        ('High',     'High'),
    ]

    # Academic stressor keywords for Layer 2 tuning.
    # Extend this list freely; no migration needed.
    ACADEMIC_STRESSORS = [
        'exam', 'exams', 'test', 'quiz',
        'grades', 'grade', 'gpa',
        'deadline', 'deadlines', 'due',
        'fail', 'failed', 'failing',
        'assignment', 'project', 'finals', 'midterm',
        'presentation', 'submit', 'submission',
    ]
    STRESSOR_PENALTY = 0.2   # subtracted from sentiment_score when a keyword is found

    # ── Core fields ───────────────────────────────────────────────────
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='mood_entries',
        help_text="Student who logged this mood"
    )
    timestamp = models.DateTimeField(
        auto_now_add=True, help_text="When this mood was logged"
    )
    note = models.TextField(
        blank=True, help_text="Free-text mood description (optional)"
    )

    # ── Layer 3 input: explicit user selection ─────────────────────────
    user_selected_mood = models.CharField(
        max_length=3, choices=MOOD_CHOICES, default=MOOD_NEU,
        help_text="Student's explicit mood choice: SAD, ANX, STR, HAP, or NEU"
    )

    # ── Fused output fields (always populated after save) ─────────────
    sentiment_score = models.FloatField(
        null=True, blank=True,
        help_text="Tuned sentiment score after keyword penalty (−1 to 1). "
                  "Null only when no note AND no explicit mood provided."
    )
    depression_level = models.CharField(
        max_length=20, choices=DAS_CHOICES, default='Low',
        help_text="Fused depression level — never empty"
    )
    anxiety_level = models.CharField(
        max_length=20, choices=DAS_CHOICES, default='Low',
        help_text="Fused anxiety level — never empty"
    )
    stress_level = models.CharField(
        max_length=20, choices=DAS_CHOICES, default='Low',
        help_text="Fused stress level — never empty"
    )

    # ── Private helpers ───────────────────────────────────────────────

    def _apply_keyword_tuning(self, score, note_lower):
        """
        Layer 2 — Keyword Override.

        Searches the lowercased note for academic stressor words.
        Subtracts STRESSOR_PENALTY (0.2) if any keyword is found,
        clamping the result to the valid range [−1.0, 1.0].

        This prevents TextBlob's neutral 0.0 from masking real stress
        in sentences like "I have an exam tomorrow and feel okay."
        """
        words = set(note_lower.split())
        if words & set(self.ACADEMIC_STRESSORS):
            score = max(score - 0.2, -1.0)  # "grades" found → 0.0 becomes -0.2
        return score


    def _das_from_score(self, score):
        """
        Layer 1+2 — Threshold mapping from tuned sentiment score to DAS levels.

        Thresholds are intentionally asymmetric: anxiety triggers earlier
        (needs a less negative score to reach High) because academic anxiety
        often presents with mildly negative rather than strongly negative text.
        """
        # Depression
        if score >= 0.1:
            depression = 'Low'
        elif score >= -0.3:
            depression = 'Moderate'
        else:
            depression = 'High'

        # Anxiety — triggers earlier than depression
        if score >= 0.1:
            anxiety = 'Low'
        elif score >= -0.1:
            anxiety = 'Moderate'
        else:
            anxiety = 'High'

        # Stress
        if score >= 0.05:
            stress = 'Low'
        elif score >= -0.35:
            stress = 'Moderate'
        else:
            stress = 'High'

        return depression, anxiety, stress

    def _apply_ground_truth_gate(self, depression, anxiety, stress):
        """
        Layer 3 — Ground-Truth Validation Gate.

        If AI+keyword tuning produces a neutral result (score close to 0)
        but the student explicitly chose ANX or STR, the student's direct
        self-report is more reliable than the text analysis.

        Rules:
          user_selected_mood == ANX  →  force anxiety_level  to 'High'
          user_selected_mood == STR  →  force stress_level   to 'High'
          user_selected_mood == SAD  →  force depression_level to 'High'
                                        and stress_level to 'Moderate' minimum
          user_selected_mood == HAP  →  cap levels at 'Low'
                                        (student says they are fine)
        """
        mood = self.user_selected_mood

        if mood == self.MOOD_ANX:
            anxiety = 'High'

        elif mood == self.MOOD_STR:
            stress = 'High'
            # Stressed students typically show at least moderate anxiety
            if anxiety == 'Low':
                anxiety = 'Moderate'

        elif mood == self.MOOD_SAD:
            depression = 'High'
            if stress == 'Low':
                stress = 'Moderate'

        elif mood == self.MOOD_HAP:
            # Student reports happiness — trust them; cap everything at Low
            depression = 'Low'
            anxiety    = 'Low'
            stress     = 'Low'

        # MOOD_NEU: no override; AI result stands

        return depression, anxiety, stress

    def _das_from_mood_only(self):
        """
        Fallback when there is no note at all — derive DAS purely from
        the user_selected_mood so DAS fields are never left empty.
        """
        mapping = {
            self.MOOD_SAD: ('High',     'Moderate', 'Moderate'),
            self.MOOD_ANX: ('Moderate', 'High',     'Moderate'),
            self.MOOD_STR: ('Moderate', 'Moderate', 'High'),
            self.MOOD_HAP: ('Low',      'Low',      'Low'),
            self.MOOD_NEU: ('Low',      'Low',      'Low'),
        }
        return mapping.get(self.user_selected_mood, ('Low', 'Low', 'Low'))

    # ── Model save ────────────────────────────────────────────────────

    def save(self, *args, **kwargs):
        """
        Data-Fusion Engine — runs on every create or update.

        Pipeline:
          1. TextBlob raw score  (Layer 1)
          2. Keyword penalty     (Layer 2)
          3. Threshold → DAS     (Layer 1+2)
          4. Ground-truth gate   (Layer 3)
        """
        if self.note:
            try:
                from textblob import TextBlob

                # Layer 1 — raw AI sentiment
                raw_score = float(TextBlob(self.note).sentiment.polarity)

                # Layer 2 — keyword tuning
                tuned_score = self._apply_keyword_tuning(
                    raw_score, self.note.lower()
                )
                self.sentiment_score = round(tuned_score, 4)

                # Layer 1+2 — threshold mapping
                depression, anxiety, stress = self._das_from_score(tuned_score)

            except Exception:
                # TextBlob unavailable — fall through to mood-only path
                self.sentiment_score = None
                depression, anxiety, stress = self._das_from_mood_only()

        else:
            # No note — derive DAS entirely from user's explicit choice
            self.sentiment_score = None
            depression, anxiety, stress = self._das_from_mood_only()

        # Layer 3 — ground-truth gate (runs regardless of whether note exists)
        depression, anxiety, stress = self._apply_ground_truth_gate(
            depression, anxiety, stress
        )

        self.depression_level = depression
        self.anxiety_level    = anxiety
        self.stress_level     = stress

        super().save(*args, **kwargs)
        
        crisis = CrisisDetector.check_all(self.user)
    
        if crisis and crisis['severity'] in ['critical', 'high']:
        # Create crisis event
           crisis_event = CrisisEvent.objects.create(
            user=self.user,
            trigger_type=crisis['trigger'],
            severity=crisis['severity'],
            detection_data=crisis['data']
        )
        
        # Get resources
        resources = CrisisResource.objects.filter(
            is_active=True,
            severity_level='immediate'
        )[:3]
        
        crisis_event.resources_displayed.set(resources)
        
        # Send push notification to show crisis modal in app
        NotificationService.send_push_notification(
            user=self.user,
            title="Support Available",
            message="We noticed you might be struggling. We're here to help.",
            data={
                'type': 'crisis_detected',
                'severity': crisis['severity'],
                'crisis_event_id': crisis_event.id
            }
        )
    def __str__(self):
        return (
            f"{self.user.username} [{self.get_user_selected_mood_display()}] "
            f"— D:{self.depression_level} A:{self.anxiety_level} S:{self.stress_level} "
            f"@ {self.timestamp.strftime('%Y-%m-%d %H:%M')}"
        )

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Mood Entry'
        verbose_name_plural = 'Mood Entries'



# ==================== SLEEP TRACKING ====================
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth.models import User
from datetime import datetime
from django.utils import timezone
class SleepLog(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sleep_logs',
        help_text="Student tracking their sleep"
    )
    date = models.DateField(help_text="Date of sleep (e.g., night of Feb 10)")
    
    # NEW FIELDS: From, To, and Interruptions
    sleep_from = models.TimeField(null=True, blank=True, help_text="Time you went to bed")
    sleep_to = models.TimeField(null=True, blank=True, help_text="Time you woke up")
    interruption_count = models.PositiveIntegerField(default=0, help_text="Number of times sleep was interrupted")
    
    # Updated to be auto-calculated
    hours_slept = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(24.0)],
        default=0.0,
        help_text="Total hours (auto-calculated from From/To)"
    )
    
    # NEW FIELD: Sleep Quality Tag (Replaces the hyphen in your UI)
    quality_tag = models.CharField(
        max_length=20, 
        default="-", 
        help_text="Good, Poor, or Not Bad"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def save(self, *args, **kwargs):
    # 1. Calculate hours_slept (keep the decimal for backend calculations)
        if self.sleep_from and self.sleep_to:
            start = datetime.combine(self.date, self.sleep_from)
            end = datetime.combine(self.date, self.sleep_to)
            if end <= start:
                from datetime import timedelta
                end += timedelta(days=1)
        
            diff = end - start
            self.hours_slept = round(diff.total_seconds() / 3600, 2)
    
    # 2. Determine Quality Tag
        if self.hours_slept >= 7 and self.interruption_count <= 1:
            self.quality_tag = "Good"
        elif self.hours_slept < 5 or self.interruption_count >= 3:
            self.quality_tag = "Poor"
        else:
            self.quality_tag = "Not Bad"
    
        super().save(*args, **kwargs)

# ADD THIS NEW METHOD
    def get_duration_display(self):
        """Return sleep duration in user-friendly format: '6h 40m'"""
        if not self.hours_slept:
            return "0h 0m"
    
        hours = int(self.hours_slept)
        minutes = int((self.hours_slept - hours) * 60)
        return f"{hours}h {minutes}m"

    def __str__(self):
        return f"{self.user.username} - {self.quality_tag} ({self.get_duration_display()}) on {self.date}"
    
    class Meta:
        ordering = ['-date']
        verbose_name = 'Sleep Log'
        verbose_name_plural = 'Sleep Logs'
        unique_together = ['user', 'date']


# ==================== STUDY TRACKING ====================

class StudySession(models.Model):
    """
    Study Session Tracker (Samsung Health-inspired).
    
    Records study sessions with automatic duration calculation.
    Helps monitor academic engagement and prevent burnout.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='study_sessions',
        help_text="Student logging the study session"
    )
    subject = models.CharField(
        max_length=200,
        help_text="Subject or topic studied (e.g., 'Mathematics', 'Python Programming')"
    )
    start_time = models.DateTimeField(
        help_text="When the study session started"
    )
    end_time = models.DateTimeField(
        help_text="When the study session ended"
    )
    duration_minutes = models.IntegerField(
        editable=False,
        help_text="Auto-calculated duration in minutes"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        """Auto-calculate duration on save."""
        if self.start_time and self.end_time:
            delta = self.end_time - self.start_time
            self.duration_minutes = int(delta.total_seconds() / 60)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.subject} ({self.duration_minutes} mins)"

    class Meta:
        ordering = ['-start_time']
        verbose_name = 'Study Session'
        verbose_name_plural = 'Study Sessions'
        indexes = [
            models.Index(fields=['user', 'start_time']),
        ]


# ==================== WELLNESS RESOURCES ====================

class WellnessResource(models.Model):
    """
    Wellness Resource Catalogue — powers the Samsung Health-style carousel.

    Each row represents one card the frontend can render.  Admins curate
    this table via the Django admin panel; the WellnessSummaryView queries
    it at runtime and returns a ranked subset as `recommended_resources`.

    Filtering tags (comma-separated in the `tags` field) let the engine
    surface the right cards without storing category-specific logic in Python.
    Example tag strings:
        "breathing,anxiety,stress"
        "sleep,recovery,hygiene"
        "focus,study,pomodoro"
        "journal,mood,gratitude"
    """

    CATEGORY_CHOICES = [
        ('Mood',     'Mood'),
        ('Focus',    'Focus'),
        ('Recovery', 'Recovery'),
    ]

    # ── Content fields ────────────────────────────────────────────────
    title    = models.CharField(
                   max_length=200,
                   help_text="Card headline shown in the carousel, e.g. 'Box Breathing'")
    category = models.CharField(
                   max_length=20, choices=CATEGORY_CHOICES,
                   help_text="Wellness pillar this card belongs to")
    image_url    = models.URLField(
                       blank=True,
                       help_text="Thumbnail URL displayed on the card face")
    content_link = models.URLField(
                       help_text="URL or deep-link opened when the student taps the card")

    # ── Frontend rendering hints ──────────────────────────────────────
    # Stored here so the frontend never hard-codes presentation logic.
    color  = models.CharField(
                 max_length=10, default='#4A90D9',
                 help_text="Hex background colour for the card, e.g. '#4A3728'")
    action = models.CharField(
                 max_length=80, default='open',
                 help_text="Action token the frontend routes on: 'breathe', "
                           "'journal', 'sleep_tips', 'meditate', 'focus'")

    # ── Recommendation engine metadata ───────────────────────────────
    tags = models.CharField(
               max_length=300, blank=True,
               help_text="Comma-separated filter tags used by the recommendation "
                         "engine, e.g. 'breathing,stress,anxiety'")
    priority = models.PositiveSmallIntegerField(
                   default=100,
                   help_text="Lower = shown earlier within its slot. "
                             "Used as a tie-breaker when multiple cards match a rule.")

    is_active = models.BooleanField(
                    default=True,
                    help_text="Inactive cards are never returned by the API")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def tag_list(self):
        """Return the tags field as a cleaned Python list of lowercase strings."""
        return [t.strip().lower() for t in self.tags.split(',') if t.strip()]

    def as_card(self):
        """
        Return the dict shape the frontend maps directly to a Card component.
        This is the exact format returned inside `recommended_resources`.
        """
        return {
            'title':        self.title,
            'category':     self.category,
            'color':        self.color,
            'action':       self.action,
            'image_url':    self.image_url,
            'content_link': self.content_link,
        }

    def __str__(self):
        return f"[{self.category}] {self.title}"

    class Meta:
        ordering = ['priority', 'category', 'title']
        verbose_name = 'Wellness Resource'
        verbose_name_plural = 'Wellness Resources'
        indexes = [
            models.Index(fields=['category', 'is_active']),
        ]

# ==================== USER PERSONALIZATION & GAMIFICATION ====================

class UserStats(models.Model):
    """
    User Statistics & Streaks (Gamification Layer).
    
    Tracks engagement patterns, streaks, and behavioral insights
    to provide personalized encouragement and pattern detection.
    """
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='stats'
    )
    
    # Streak tracking
    current_streak = models.IntegerField(
        default=0,
        help_text="Current consecutive days of check-ins"
    )
    longest_streak = models.IntegerField(
        default=0,
        help_text="Longest streak ever achieved"
    )
    last_checkin_date = models.DateField(
        null=True, blank=True,
        help_text="Last date user logged any entry"
    )
    total_checkins = models.IntegerField(
        default=0,
        help_text="Total number of mood entries logged"
    )
    
    # Feature usage tracking
    features_used = models.JSONField(
        default=dict,
        help_text="Count of feature usage: {'mood': 45, 'sleep': 30, 'breathing': 12}"
    )
    
    # Personal bests
    best_health_score = models.FloatField(
        default=0.0,
        help_text="Highest health score achieved"
    )
    best_health_score_date = models.DateField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def update_streak(self):
        """Update streak based on today's check-in."""
        today = timezone.now().date()
        
        # First check-in ever
        if not self.last_checkin_date:
            self.current_streak = 1
            self.longest_streak = 1
            self.last_checkin_date = today
            self.save()
            return
        
        # Already logged today
        if self.last_checkin_date == today:
            return
        
        # Consecutive day
        if self.last_checkin_date == today - timedelta(days=1):
            self.current_streak += 1
        # Streak broken
        else:
            self.current_streak = 1
        
        # Update longest
        if self.current_streak > self.longest_streak:
            self.longest_streak = self.current_streak
        
        self.last_checkin_date = today
        self.save()
    
    def track_feature_use(self, feature_name):
        """Increment usage counter for a feature."""
        if feature_name not in self.features_used:
            self.features_used[feature_name] = 0
        self.features_used[feature_name] += 1
        self.save()
    
    def get_favorite_features(self, top_n=3):
        """Return most-used features."""
        sorted_features = sorted(
            self.features_used.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_features[:top_n]
    
    def __str__(self):
        return f"{self.user.username} - {self.current_streak} day streak"
    
    class Meta:
        verbose_name = 'User Statistics'
        verbose_name_plural = 'User Statistics'


class UserPreferences(models.Model):
    """
    User Preferences & Personalization Settings.
    
    Controls notification timing, feature visibility, and adaptive UI.
    """
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='preferences'
    )
    
    # Notification preferences
    morning_checkin_enabled = models.BooleanField(
        default=True,
        help_text="Send morning check-in prompt"
    )
    morning_checkin_time = models.TimeField(
        default='09:00',
        help_text="Preferred morning check-in time"
    )
    evening_checkin_enabled = models.BooleanField(
        default=True,
        help_text="Send evening reflection prompt"
    )
    evening_checkin_time = models.TimeField(
        default='21:00',
        help_text="Preferred evening reflection time"
    )
    post_study_prompt = models.BooleanField(
        default=True,
        help_text="Prompt mood check after study sessions"
    )
    
    # Adaptive interface
    hidden_features = models.JSONField(
        default=list,
        help_text="Features user has chosen to hide: ['study_tracking']"
    )
    favorite_resources = models.JSONField(
        default=list,
        help_text="Resource IDs user frequently accesses"
    )
    
    # Theme preferences
    THEME_CHOICES = [
        ('auto', 'Auto (based on mood)'),
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('calming', 'Calming (Green/Blue)'),
    ]
    theme_preference = models.CharField(
        max_length=10,
        choices=THEME_CHOICES,
        default='auto'
    )
    
    # Crisis support acknowledgment
    crisis_resources_shown = models.BooleanField(
        default=False,
        help_text="User has seen crisis resources"
    )
    crisis_resources_last_shown = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.username} - Preferences"
    
    class Meta:
        verbose_name = 'User Preference'
        verbose_name_plural = 'User Preferences'


# ==================== ENHANCED MOOD TRACKING ====================

class EnhancedMoodEntry(models.Model):
    """
    Enhanced Mood Entry with Context-Aware Features.
    
    Extends the base MoodEntry with:
    - Time-of-day context (morning/evening)
    - Mood intensity slider (1-10)
    - Energy level tracking
    - Daily wins/drains
    - Voice note support
    """
    # Link to original MoodEntry (one-to-one relationship)
    # In production, you'd merge this into MoodEntry directly
    mood_entry = models.OneToOneField(
        'MoodEntry',
        on_delete=models.CASCADE,
        related_name='enhancement',
        null=True, blank=True
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    # Context-aware fields
    TIME_OF_DAY_CHOICES = [
        ('morning', 'Morning'),
        ('afternoon', 'Afternoon'),
        ('evening', 'Evening'),
        ('night', 'Night'),
    ]
    time_of_day = models.CharField(
        max_length=10,
        choices=TIME_OF_DAY_CHOICES,
        default='evening'
    )
    
    # Intensity tracking
    mood_intensity = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        default=5,
        help_text="Mood intensity on 1-10 scale"
    )
    energy_level = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        default=50,
        help_text="Energy level percentage (0-100)"
    )
    
    # Daily reflection
    day_rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        null=True, blank=True,
        help_text="Overall day rating (1-5 stars)"
    )
    wins_today = models.TextField(
        blank=True,
        help_text="Today's wins, accomplishments, or positive moments"
    )
    energy_drains = models.JSONField(
        default=list,
        help_text="What drained energy: ['overthinking', 'social_anxiety']"
    )
    
    # Academic worries
    worries_today = models.JSONField(
        default=list,
        help_text="Specific worries: ['exam', 'assignment', 'social']"
    )
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Enhanced Mood Entry'
        verbose_name_plural = 'Enhanced Mood Entries'
    
    def __str__(self):
        return f"{self.user.username} - {self.time_of_day} check-in"


# ==================== MICRO-COMMITMENTS ====================

class MicroCommitment(models.Model):
    """
    Micro-Commitments for Behavioral Intervention.
    
    Supports both predefined behavioral interventions and custom user commitments.
    Track completion for positive reinforcement.
    """
    COMMITMENT_TYPES = [
        ('breathing', '3 Deep Breaths'),
        ('water', 'Drink Water'),
        ('walk', 'Step Outside (2 min)'),
        ('friend', 'Text a Friend'),
        ('stretch', 'Quick Stretch'),
        ('gratitude', 'Write One Gratitude'),
    ]
    
    CATEGORIES = [
        ('self_care', 'Self Care'),
        ('health', 'Health'),
        ('social', 'Social'),
        ('academic', 'Academic'),
        ('mindfulness', 'Mindfulness'),
        ('exercise', 'Exercise'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    mood_entry = models.ForeignKey(
        'MoodEntry',
        on_delete=models.CASCADE,
        related_name='commitments',
        null=True,
        blank=True
    )
    
    # Predefined commitment type (optional for custom commitments)
    commitment_type = models.CharField(
        max_length=20,
        choices=COMMITMENT_TYPES,
        null=True,
        blank=True
    )
    
    # Custom commitment fields
    commitment_text = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Custom commitment text entered by user"
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORIES,
        null=True,
        blank=True,
        help_text="Category for custom commitments"
    )
    target_date = models.DateField(
        null=True,
        blank=True,
        help_text="Target date for completion"
    )
    
    committed_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Completion tracking
    reminder_sent = models.BooleanField(default=False)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    
    def mark_complete(self):
        """Mark commitment as completed."""
        self.completed_at = timezone.now()
        self.save()
        
        # Trigger positive reinforcement
        # (You'd send a notification or show celebration UI)
        return True
    
    @property
    def is_completed(self):
        return self.completed_at is not None
    
    @property
    def time_to_complete(self):
        """Time taken to complete in minutes."""
        if not self.completed_at:
            return None
        delta = self.completed_at - self.committed_at
        return int(delta.total_seconds() / 60)
    
    @property
    def display_text(self):
        """Get the display text for the commitment."""
        if self.commitment_text:
            return self.commitment_text
        elif self.commitment_type:
            return self.get_commitment_type_display()
        else:
            return "Untitled Commitment"
    
    def __str__(self):
        status = "✓" if self.is_completed else "○"
        return f"{status} {self.user.username} - {self.display_text}"
    
    class Meta:
        ordering = ['-committed_at']
        verbose_name = 'Micro Commitment'
        verbose_name_plural = 'Micro Commitments'


# ==================== PATTERN DETECTION ====================

class DetectedPattern(models.Model):
    """
    ML-Detected Behavioral Patterns.
    
    Stores patterns like "anxiety spikes on Mondays" for proactive support.
    """
    PATTERN_TYPES = [
        ('weekly_spike', 'Weekly Anxiety Spike'),
        ('pre_exam_stress', 'Pre-Exam Stress Pattern'),
        ('sleep_mood_correlation', 'Sleep-Mood Correlation'),
        ('study_burnout', 'Study Session Burnout'),
        ('social_anxiety_timing', 'Social Anxiety Timing'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    pattern_type = models.CharField(max_length=30, choices=PATTERN_TYPES)
    
    # Pattern details
    detected_at = models.DateTimeField(auto_now_add=True)
    confidence = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Confidence score (0-1) based on data points"
    )
    
    # Pattern metadata
    metadata = models.JSONField(
        default=dict,
        help_text="Pattern details: {'day': 'Monday', 'time': '14:00', 'trigger': 'class'}"
    )
    
    # User interaction
    acknowledged = models.BooleanField(default=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    helpful = models.BooleanField(
        null=True,
        help_text="User feedback: was this insight helpful?"
    )
    
    # Active/dismissed
    is_active = models.BooleanField(
        default=True,
        help_text="False if pattern no longer valid or user dismissed"
    )
    
    def get_insight_message(self):
        """Generate human-readable insight."""
        if self.pattern_type == 'weekly_spike':
            day = self.metadata.get('day', 'a certain day')
            return f"Your anxiety tends to spike on {day}s. Plan self-care ahead."
        
        elif self.pattern_type == 'sleep_mood_correlation':
            threshold = self.metadata.get('sleep_hours', 7)
            improvement = self.metadata.get('mood_improvement', '2x')
            return f"When you sleep {threshold}+ hours, your mood is {improvement} better."
        
        elif self.pattern_type == 'pre_exam_stress':
            days_before = self.metadata.get('days_before', 2)
            return f"You typically feel stressed {days_before} days before exams. Prepare coping strategies."
        
        return "Pattern detected in your wellness data."
    
    def __str__(self):
        return f"{self.user.username} - {self.get_pattern_type_display()}"
    
    class Meta:
        ordering = ['-detected_at']
        verbose_name = 'Detected Pattern'
        verbose_name_plural = 'Detected Patterns'
        indexes = [
            models.Index(fields=['user', 'is_active']),
        ]


# ==================== PERSONAL INSIGHTS ====================

class PersonalInsight(models.Model):
    """
    Personalized Insights Generated Weekly.
    
    Examples:
    - "You studied 12 hours this week vs 8 hours last week (+50%)"
    - "Your best sleep nights were Tuesday-Thursday (avg 8.2h)"
    - "Breathing exercises correlated with 1.5x better mood"
    """
    INSIGHT_TYPES = [
        ('trend', 'Trend Analysis'),
        ('correlation', 'Correlation Discovery'),
        ('achievement', 'Achievement Highlight'),
        ('recommendation', 'Personalized Recommendation'),
        ('warning', 'Early Warning'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    insight_type = models.CharField(max_length=20, choices=INSIGHT_TYPES)
    
    # Content
    title = models.CharField(
        max_length=200,
        help_text="Insight headline: 'Your Best Week Yet!'"
    )
    message = models.TextField(
        help_text="Full insight message with actionable advice"
    )
    
    # Data backing
    data_points = models.JSONField(
        default=dict,
        help_text="Supporting data: {'sleep_avg': 7.2, 'mood_avg': 0.6}"
    )
    
    # Metadata
    generated_at = models.DateTimeField(auto_now_add=True)
    for_week_starting = models.DateField(
        help_text="Week this insight covers"
    )
    
    # User interaction
    viewed = models.BooleanField(default=False)
    viewed_at = models.DateTimeField(null=True, blank=True)
    helpful_rating = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="User's helpfulness rating (1-5)"
    )
    
    # Priority (for sorting)
    priority = models.IntegerField(
        default=3,
        help_text="1=highest, 5=lowest"
    )
    
    class Meta:
        ordering = ['priority', '-generated_at']
        verbose_name = 'Personal Insight'
        verbose_name_plural = 'Personal Insights'
    
    def __str__(self):
        return f"{self.user.username} - {self.title}"


# ==================== CRISIS SUPPORT ====================

class CrisisCheckpoint(models.Model):
    """
    Crisis Detection & Resource Provision Log.
    
    Tracks when crisis indicators are detected and resources shown.
    Important for safety and liability.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    detected_at = models.DateTimeField(auto_now_add=True)
    
    # Detection criteria
    SEVERITY_LEVELS = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]
    severity = models.CharField(max_length=10, choices=SEVERITY_LEVELS)
    
    # Indicators
    indicators = models.JSONField(
        default=list,
        help_text="List of indicators: ['3_high_anxiety_today', 'sleep_<4h_3days']"
    )
    
    # Resources shown
    resources_shown = models.JSONField(
        default=list,
        help_text="Resources presented: ['campus_counseling', 'crisis_text_line']"
    )
    
    # User response
    resources_viewed = models.BooleanField(default=False)
    resources_viewed_at = models.DateTimeField(null=True, blank=True)
    user_dismissed = models.BooleanField(default=False)
    user_contacted_resource = models.BooleanField(
        null=True,
        help_text="Self-reported: did user reach out?"
    )
    
    # Follow-up
    follow_up_scheduled = models.BooleanField(default=False)
    follow_up_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-detected_at']
        verbose_name = 'Crisis Checkpoint'
        verbose_name_plural = 'Crisis Checkpoints'
    
    def __str__(self):
        return f"{self.user.username} - {self.severity.upper()} at {self.detected_at}"


# ==================== CARE PACKAGES ====================

class CarePackage(models.Model):
    """
    Pre-Exam / High-Stress Period Care Packages.
    
    Curated collection of resources activated before stressful events.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    academic_event = models.ForeignKey(
        'AcademicEvent',
        on_delete=models.CASCADE,
        related_name='care_packages'
    )
    
    # Activation
    activated_at = models.DateTimeField(auto_now_add=True)
    event_starts_at = models.DateField(
        help_text="When the stressful event begins"
    )
    
    # Package contents
    resources_included = models.JSONField(
        default=list,
        help_text="List of WellnessResource IDs included"
    )
    tips = models.JSONField(
        default=list,
        help_text="Text tips: ['Get 8h sleep', 'Eat breakfast', 'Arrive early']"
    )
    
    # Adjustments made
    sleep_goal_adjusted = models.BooleanField(default=False)
    new_sleep_goal = models.FloatField(null=True, blank=True)
    
    # User interaction
    viewed = models.BooleanField(default=False)
    viewed_at = models.DateTimeField(null=True, blank=True)
    helpful = models.BooleanField(null=True)
    
    class Meta:
        ordering = ['-activated_at']
        verbose_name = 'Care Package'
        verbose_name_plural = 'Care Packages'
    
    def __str__(self):
        return f"Care Package for {self.user.username} - {self.academic_event.event_name}"


# ==================== COMMUNITY STATS (ANONYMOUS) ====================

class CommunitySnapshot(models.Model):
    """
    Daily Anonymous Community Statistics.
    
    Used for "You're not alone" social proof without identifying individuals.
    Aggregated daily by a background task.
    """
    snapshot_date = models.DateField(unique=True)
    
    # Activity stats
    active_users_count = models.IntegerField(default=0)
    total_mood_entries = models.IntegerField(default=0)
    
    # Aggregate wellness
    avg_health_score = models.FloatField(null=True)
    avg_anxiety_level = models.FloatField(
        null=True,
        help_text="Average anxiety on 1-3 scale (1=Low, 2=Moderate, 3=High)"
    )
    avg_stress_level = models.FloatField(null=True)
    avg_sleep_hours = models.FloatField(null=True)
    
    # Popular activities
    most_used_resource_id = models.IntegerField(null=True)
    breathing_exercises_count = models.IntegerField(default=0)
    
    # Context
    active_events = models.JSONField(
        default=list,
        help_text="Academic events active today: ['Finals Week', 'Midterms']"
    )
    
    generated_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-snapshot_date']
        verbose_name = 'Community Snapshot'
        verbose_name_plural = 'Community Snapshots'
    
    def __str__(self):
        return f"Community Stats - {self.snapshot_date}"


# ==================== DELETED ITEMS (SOFT DELETE) ====================

class DeletedMoodEntry(models.Model):
    """
    Soft-deleted mood entries for 30-day undo window.
    
    Allows users to undo accidental deletions.
    """
    original_id = models.IntegerField(
        null=True,   # Allows the database to store "None"
        blank=True,  # Allows the Admin form to be submitted empty
        help_text="The ID of the mood entry before it was deleted"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # Original data (JSON snapshot)
    original_data = models.JSONField()
    
    # Deletion tracking
    deleted_at = models.DateTimeField(auto_now_add=True)
    deleted_by_user = models.BooleanField(
        default=True,
        help_text="False if auto-deleted by admin"
    )
    
    # Restoration tracking
    restored = models.BooleanField(default=False)
    restored_at = models.DateTimeField(null=True, blank=True)
    
    # Auto-cleanup after 30 days
    permanent_delete_at = models.DateTimeField()
    
    def save(self, *args, **kwargs):
        if not self.permanent_delete_at:
            self.permanent_delete_at = timezone.now() + timedelta(days=30)
        super().save(*args, **kwargs)
    
    def restore(self):
        """Restore the deleted entry."""
        # Recreate MoodEntry from original_data
        # Implementation depends on your restoration logic
        self.restored = True
        self.restored_at = timezone.now()
        self.save()
    
    class Meta:
        ordering = ['-deleted_at']
        verbose_name = 'Deleted Mood Entry'
        verbose_name_plural = 'Deleted Mood Entries'
    
    def __str__(self):
        return f"Deleted entry #{self.original_id} - {self.user.username}"

# ==================== TEEN STRESS CATEGORIES ====================
 
class StressCategory(models.Model):
    """
    Different types of teen stress beyond academics.
    Addresses real teenage struggles: social, relationships, family, identity, etc.
    """
    CATEGORY_TYPES = [
        ('academic', 'Academic Pressure'),
        ('social', 'Social Anxiety & Friendships'),
        ('romantic', 'Romantic Relationships'),
        ('family', 'Family Dynamics'),
        ('identity', 'Identity & Self-Image'),
        ('bullying', 'Bullying & Peer Pressure'),
        ('social_media', 'Social Media & FOMO'),
        ('future', 'Future & Career Uncertainty'),
        ('body_image', 'Body Image & Appearance'),
        ('loneliness', 'Loneliness & Isolation'),
        ('finances', 'Money Worries'),
        ('global_issues', 'World Events & Climate'),
    ]
    
    name = models.CharField(max_length=100)
    category_type = models.CharField(max_length=20, choices=CATEGORY_TYPES, unique=True)
    description = models.TextField(help_text="What this stress category means")
    emoji = models.CharField(max_length=10, default="😟")
    color = models.CharField(max_length=7, default="#FF6B6B")
    
    # Educational content
    why_it_happens = models.TextField(
        help_text="Why teens experience this type of stress",
        blank=True
    )
    common_signs = models.JSONField(
        default=list,
        help_text="List of common signs/symptoms"
    )
    coping_strategies = models.JSONField(
        default=list,
        help_text="Healthy ways to cope with this stress"
    )
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name_plural = "Stress Categories"
        ordering = ['name']
    
    def __str__(self):
        return f"{self.emoji} {self.name}"
 
 
# ==================== TEEN STRESS ASSESSMENT QUIZ ====================
 
class StressAssessmentQuestion(models.Model):
    """
    Quiz questions to assess different types of teen stress.
    Questions are empathetic, age-appropriate, and non-judgmental.
    """
    category = models.ForeignKey(
        StressCategory,
        on_delete=models.CASCADE,
        related_name='questions'
    )
    
    question_text = models.TextField(
        help_text="The question to ask (empathetic, teen-friendly language)"
    )
    
    # Question metadata
    order = models.IntegerField(default=0, help_text="Display order")
    is_required = models.BooleanField(default=True)
    weight = models.FloatField(
        default=1.0,
        help_text="How much this question impacts the stress score (0.5-2.0)"
    )
    
    # Response options (scale: 0 = Never, 4 = All the time)
    RESPONSE_OPTIONS = [
        (0, "Never / Not at all"),
        (1, "Rarely / A little"),
        (2, "Sometimes / Moderately"),
        (3, "Often / Quite a bit"),
        (4, "All the time / Extremely"),
    ]
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['category', 'order']
    
    def __str__(self):
        return f"{self.category.name}: {self.question_text[:50]}..."
 
 
class StressAssessmentResponse(models.Model):
    """
    User's responses to stress assessment quiz.
    Tracks how teens experience different types of stress.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    session_date = models.DateTimeField(auto_now_add=True)
    
    # Responses stored as JSON: {question_id: score}
    responses = models.JSONField( # or TextField depending on your current setup
    null=True, 
    blank=True,
    help_text="Stored quiz answers from the student"
    )
    
    # Calculated scores per category
    category_scores = models.JSONField(
        default=dict,
        help_text="Category type to percentage score mapping"
    )
    
    # Overall metrics
    overall_stress_score = models.FloatField(
        default=0.0,
        help_text="Overall stress level (0-100)"
    )
    
    # Top stress sources
    primary_stressor = models.CharField(max_length=50, blank=True)
    secondary_stressor = models.CharField(max_length=50, blank=True)
    
    # User feedback
    found_helpful = models.BooleanField(null=True, blank=True)
    feedback_text = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-session_date']
    
    def __str__(self):
        return f"{self.user.username} - {self.session_date.date()} - Stress: {self.overall_stress_score:.1f}%"
    
    def get_stress_level_label(self):
        """Return human-friendly stress level."""
        score = self.overall_stress_score
        if score < 20:
            return "Very Low - You're doing great! 💚"
        elif score < 40:
            return "Low - Managing well! 💙"
        elif score < 60:
            return "Moderate - Some support needed 💛"
        elif score < 80:
            return "High - Let's work on this together 🧡"
        else:
            return "Very High - You deserve support ❤️"
 
 
# ==================== EDUCATIONAL CONTENT FOR TEENS ====================
 
class DASEducation(models.Model):
    """
    Educational content explaining DAS (Depression, Anxiety, Stress).
    Helps teens understand what they're experiencing and why.
    Written in teen-friendly, non-clinical language.
    """
    DAS_TYPES = [
        ('depression', 'Depression'),
        ('anxiety', 'Anxiety'),
        ('stress', 'Stress'),
    ]
    
    das_type = models.CharField(max_length=20, choices=DAS_TYPES, unique=True)
    
    # What is it?
    simple_explanation = models.TextField(
        help_text="Simple, teen-friendly explanation of what this is"
    )
    
    # Why does it happen?
    why_it_happens = models.TextField(
        help_text="Why teens experience this (biological, social, environmental)"
    )
    
    # What does it feel like?
    common_experiences = models.JSONField(
        default=list,
        help_text="List of common feelings/experiences"
    )
    
    # Physical symptoms
    physical_signs = models.JSONField(
        default=list,
        help_text="Physical symptoms teens might notice"
    )
    
    # Emotional/mental symptoms
    emotional_signs = models.JSONField(
        default=list,
        help_text="Emotional/mental symptoms"
    )
    
    # Behavioral changes
    behavioral_signs = models.JSONField(
        default=list,
        help_text="Changes in behavior"
    )
    
    # Why it's okay to feel this way
    validation_message = models.TextField(
        help_text="Reassuring message that it's normal and okay"
    )
    
    # What helps
    helpful_strategies = models.JSONField(
        default=list,
        help_text="Evidence-based coping strategies"
    )
    
    # When to seek help
    when_to_get_help = models.TextField(
        help_text="Signs that professional help is needed"
    )
    
    # Myth busting
    common_myths = models.JSONField(
        default=list,
        help_text="List of myths and the truths"
    )
    
    emoji = models.CharField(max_length=10, default="💙")
    color = models.CharField(max_length=7, default="#667eea")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "DAS Education Content"
        verbose_name_plural = "DAS Education Content"
    
    def __str__(self):
        return f"{self.emoji} Understanding {self.get_das_type_display()}"
 
 
# ==================== MOOD ELEVATION & PAMPERING ====================
 
class MoodBooster(models.Model):
    """
    Quick mood elevation activities specifically for teens.
    Age-appropriate, evidence-based interventions.
    """
    BOOSTER_TYPES = [
        ('instant', 'Instant Relief (< 1 min)'),
        ('quick', 'Quick Pick-Me-Up (1-5 min)'),
        ('moderate', 'Mood Shift (5-15 min)'),
        ('deep', 'Deep Reset (15+ min)'),
    ]
    
    MOOD_TARGETS = [
        ('sad', 'When feeling sad'),
        ('anxious', 'When feeling anxious'),
        ('stressed', 'When feeling stressed'),
        ('lonely', 'When feeling lonely'),
        ('angry', 'When feeling angry'),
        ('overwhelmed', 'When feeling overwhelmed'),
        ('tired', 'When feeling tired/drained'),
        ('bored', 'When feeling bored/empty'),
    ]
    
    title = models.CharField(max_length=200)
    emoji = models.CharField(max_length=10, default="✨")
    
    booster_type = models.CharField(max_length=20, choices=BOOSTER_TYPES)
    mood_target = models.CharField(max_length=20, choices=MOOD_TARGETS)
    
    # Content
    description = models.TextField(
        help_text="What this activity is"
    )
    
    instructions = models.TextField(
        help_text="Step-by-step instructions (teen-friendly)"
    )
    
    why_it_works = models.TextField(
        help_text="Simple science behind why this helps",
        blank=True
    )
    
    # Difficulty & accessibility
    difficulty_level = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1=Super easy, 5=Takes effort"
    )
    
    requires_privacy = models.BooleanField(
        default=False,
        help_text="Does this need a private space?"
    )
    
    requires_materials = models.BooleanField(
        default=False,
        help_text="Does this need any materials?"
    )
    
    materials_needed = models.TextField(
        blank=True,
        help_text="What materials if any"
    )
    
    # Effectiveness tracking
    times_tried = models.IntegerField(default=0)
    times_helped = models.IntegerField(default=0)
    average_rating = models.FloatField(default=0.0)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-average_rating', 'title']
    
    def __str__(self):
        return f"{self.emoji} {self.title}"
    
    @property
    def success_rate(self):
        """Percentage of times this helped."""
        if self.times_tried == 0:
            return 0
        return (self.times_helped / self.times_tried) * 100
 
 
class MoodBoosterUsage(models.Model):
    """
    Tracks when teens use mood boosters and if they helped.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    booster = models.ForeignKey(MoodBooster, on_delete=models.CASCADE)
    
    tried_at = models.DateTimeField(auto_now_add=True)
    
    # Before/after mood
    mood_before = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Mood before (1=worst, 10=best)"
    )
    mood_after = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Mood after (1=worst, 10=best)"
    )
    
    # Feedback
    did_it_help = models.BooleanField(null=True, blank=True)
    rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-tried_at']
    
    def __str__(self):
        return f"{self.user.username} tried {self.booster.title}"
    
    @property
    def mood_improvement(self):
        """Calculate mood improvement."""
        if self.mood_after:
            return self.mood_after - self.mood_before
        return None
 
# ==================== REASSURANCE & AFFIRMATIONS ====================
 
class DailyAffirmation(models.Model):
    """
    Positive, age-appropriate affirmations for teens.
    Rotating daily messages that pamper and reassure.
    """
    AFFIRMATION_CATEGORIES = [
        ('self_worth', 'Self-Worth & Value'),
        ('capability', 'Capability & Strength'),
        ('belonging', 'Belonging & Connection'),
        ('growth', 'Growth & Learning'),
        ('uniqueness', 'Uniqueness & Authenticity'),
        ('resilience', 'Resilience & Courage'),
        ('compassion', 'Self-Compassion'),
        ('hope', 'Hope & Future'),
        
    ]
    
    category = models.CharField(max_length=20, choices=AFFIRMATION_CATEGORIES)
    
    message = models.TextField(
        help_text="The affirmation message (warm, genuine, teen-appropriate)"
    )
    
    follow_up = models.TextField(
        blank=True,
        help_text="Optional follow-up reflection or question"
    )
    
    emoji = models.CharField(max_length=10, default="💖")
    
    # Targeting
    for_mood = models.CharField(
        max_length=20,
        blank=True,
        help_text="Show when user is feeling... (optional)"
    )
    
    times_shown = models.IntegerField(default=0)
    times_saved = models.IntegerField(default=0)
    times_shared = models.IntegerField(default=0)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['category', '-times_shown']
    
    def __str__(self):
        return f"{self.emoji} {self.message[:50]}..."
 
 
class SavedAffirmation(models.Model):
    """
    Affirmations that resonated with a user.
    Personal collection of meaningful messages.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    affirmation = models.ForeignKey(DailyAffirmation, on_delete=models.CASCADE)
    saved_at = models.DateTimeField(auto_now_add=True)
    
    # Personal note
    why_it_resonated = models.TextField(
        blank=True,
        help_text="Why this message meant something"
    )
    
    times_revisited = models.IntegerField(default=0)
    last_viewed = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'affirmation']
        ordering = ['-saved_at']
    
    def __str__(self):
        return f"{self.user.username} saved: {self.affirmation.message[:30]}..."
 
 
# ==================== ENHANCED MOOD ENTRY FOR TEENS ====================
 
class TeenMoodContext(models.Model):
    """
    Extended mood context specifically for teen experiences.
    Captures the nuances of teenage life beyond academics.
    """
    mood_entry = models.OneToOneField(
        'MoodEntry',  # Your existing MoodEntry model
        on_delete=models.CASCADE,
        related_name='teen_context'
    )
    
    # What's going on in their life
    primary_trigger = models.CharField(
        max_length=50,
        blank=True,
        help_text="Main thing affecting mood today"
    )
    
    secondary_triggers = models.CharField(
        default=list,
        help_text="Other contributing factors"
    )
    
    # Social context
    social_interaction_quality = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="How were interactions today? (1=bad, 5=great)"
    )
    
    felt_supported = models.BooleanField(
        null=True,
        blank=True,
        help_text="Did you feel supported by someone today?"
    )
    
    felt_lonely = models.BooleanField(
        null=True,
        blank=True,
        help_text="Did you feel lonely today?"
    )
    
    # Screen time & social media
    screen_time_hours = models.FloatField(
        null=True,
        blank=True,
        help_text="Approximate screen time today"
    )
    
    social_media_mood_impact = models.CharField(
        max_length=20,
        blank=True,
        choices=[
            ('positive', 'Made me feel better'),
            ('neutral', 'No real impact'),
            ('negative', 'Made me feel worse'),
            ('mixed', 'Both good and bad'),
        ]
    )
    
    # Physical wellness
    ate_today = models.BooleanField(
        null=True,
        blank=True,
        help_text="Did you eat proper meals today?"
    )
    
    physical_activity = models.BooleanField(
        null=True,
        blank=True,
        help_text="Did you move/exercise today?"
    )
    
    # Coping
    tried_coping_strategy = models.BooleanField(default=False)
    coping_strategy_used = models.TextField(blank=True)
    coping_was_helpful = models.BooleanField(null=True, blank=True)
    
    class Meta:
        verbose_name = "Teen Mood Context"
        verbose_name_plural = "Teen Mood Context"
    
    def __str__(self):
        return f"Context for {self.mood_entry}"
 
# ==================== CRISIS DETECTION & INTERVENTION ====================
 
class CrisisResource(models.Model):
    """
    Mental health crisis resources (hotlines, text lines, chat services).
    Displayed immediately when crisis is detected.
    """
    RESOURCE_TYPES = [
        ('hotline', 'Phone Hotline'),
        ('text', 'Text/SMS Service'),
        ('chat', 'Online Chat'),
        ('app', 'Mobile App'),
        ('website', 'Website Resource'),
        ('in_person', 'In-Person Location'),
    ]
    
    SEVERITY_LEVELS = [
        ('immediate', 'Immediate Crisis (suicide, self-harm)'),
        ('urgent', 'Urgent Support Needed'),
        ('general', 'General Mental Health Support'),
    ]
    
    name = models.CharField(max_length=200)
    resource_type = models.CharField(max_length=20, choices=RESOURCE_TYPES)
    severity_level = models.CharField(max_length=20, choices=SEVERITY_LEVELS)
    
    # Contact information
    phone_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="For hotlines (e.g., 988, 1-800-273-8255)"
    )
    
    sms_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="For text services (e.g., 741741)"
    )
    
    website_url = models.URLField(
        blank=True,
        help_text="For chat services or online resources"
    )
    
    # Display information
    short_description = models.TextField(
        help_text="Brief description shown in crisis modal"
    )
    
    detailed_info = models.TextField(
        blank=True,
        help_text="Full information about the resource"
    )
    
    hours_available = models.CharField(
        max_length=100,
        default="24/7",
        help_text="When this resource is available"
    )
    
    languages_supported = models.JSONField(
        default=list,
        help_text="List of languages (e.g., ['English', 'Spanish'])"
    )
    
    # Targeting
    is_lgbtq_focused = models.BooleanField(default=False)
    is_teen_focused = models.BooleanField(default=True)
    is_campus_resource = models.BooleanField(
        default=False,
        help_text="Campus-specific resource"
    )
    
    campus_location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Physical location on campus"
    )
    
    # Ordering and visibility
    priority = models.IntegerField(
        default=0,
        help_text="Higher priority resources shown first"
    )
    is_active = models.BooleanField(default=True)
    
    # Analytics
    times_shown = models.IntegerField(default=0)
    times_clicked = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-priority', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.get_resource_type_display()})"
    
    @property
    def click_through_rate(self):
        """Calculate how often this resource is clicked when shown."""
        if self.times_shown == 0:
            return 0
        return (self.times_clicked / self.times_shown) * 100
 
 
class CrisisEvent(models.Model):
    """
    Logged whenever crisis is detected.
    LEGAL REQUIREMENT: Never delete these records.
    Used for safety monitoring and institutional liability protection.
    """
    TRIGGER_TYPES = [
        ('high_anxiety', 'Repeated High Anxiety'),
        ('severe_depression', 'Severe Depression Indicators'),
        ('self_harm', 'Self-Harm Mention'),
        ('suicidal_ideation', 'Suicidal Ideation Detected'),
        ('sleep_deprivation', 'Extreme Sleep Deprivation'),
        ('substance_use', 'Concerning Substance Use'),
        ('eating_disorder', 'Eating Disorder Indicators'),
        ('trauma_disclosure', 'Trauma Disclosure'),
        ('multiple_high_stress', 'Multiple High Stress Indicators'),
        ('manual_sos', 'User Clicked SOS Button'),
    ]
    
    SEVERITY_LEVELS = [
        ('low', 'Low - Monitoring'),
        ('medium', 'Medium - Support Recommended'),
        ('high', 'High - Urgent Support'),
        ('critical', 'Critical - Immediate Intervention'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    detected_at = models.DateTimeField(auto_now_add=True)
    
    # Detection details
    trigger_type = models.CharField(max_length=30, choices=TRIGGER_TYPES)
    severity = models.CharField(max_length=20, choices=SEVERITY_LEVELS)
    
    detection_data = models.JSONField(
        help_text="What triggered the crisis detection (scores, keywords, etc.)"
    )
    
    # Resources shown
    resources_displayed = models.ManyToManyField(
        CrisisResource,
        related_name='crisis_events',
        blank=True
    )
    
    # User actions
    user_viewed_resources = models.BooleanField(default=False)
    resources_clicked = models.JSONField(
        default=list,
        help_text="Which resources user clicked on"
    )
    
    user_contacted_resource = models.BooleanField(
        default=False,
        help_text="User confirmed they contacted a resource"
    )
    
    user_dismissed = models.BooleanField(
        default=False,
        help_text="User dismissed the crisis alert"
    )
    
    dismissed_at = models.DateTimeField(null=True, blank=True)
    
    # Follow-up
    follow_up_scheduled = models.BooleanField(default=False)
    follow_up_completed = models.BooleanField(default=False)
    follow_up_date = models.DateTimeField(null=True, blank=True)
    
    # Notifications sent
    notifications_sent = models.JSONField(
        default=dict,
        help_text="What notifications were sent (push, email, SMS, admin)"
    )
    
    # Admin response
    admin_reviewed = models.BooleanField(default=False)
    admin_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_crises'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-detected_at']
        verbose_name = 'Crisis Event'
        verbose_name_plural = 'Crisis Events'
    
    def __str__(self):
        return f"{self.user.username} - {self.get_severity_display()} - {self.detected_at.date()}"
    
    def mark_resource_clicked(self, resource_id):
        """Track when user clicks a resource."""
        if resource_id not in self.resources_clicked:
            self.resources_clicked.append(resource_id)
            self.save()
 
 
class TrustedContact(models.Model):
    """
    Emergency contacts user designates to be notified during crisis.
    User must explicitly opt-in to this feature.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='trusted_contacts')
    
    # Contact info
    name = models.CharField(max_length=200)
    relationship = models.CharField(
        max_length=100,
        help_text="e.g., Parent, Friend, Sibling, Counselor"
    )
    
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    
    # Notification preferences
    notify_via_email = models.BooleanField(default=False)
    notify_via_sms = models.BooleanField(default=False)
    
    # Severity threshold
    notify_on_severity = models.CharField(
        max_length=20,
        choices=[
            ('medium', 'Medium and above'),
            ('high', 'High and above'),
            ('critical', 'Critical only'),
        ],
        default='critical'
    )
    
    # Consent
    user_confirmed_consent = models.BooleanField(
        default=False,
        help_text="User confirmed they have permission to add this contact"
    )
    
    contact_confirmed = models.BooleanField(
        default=False,
        help_text="Contact confirmed they want to receive alerts"
    )
    
    is_active = models.BooleanField(default=True)
    
    # Tracking
    times_notified = models.IntegerField(default=0)
    last_notified = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username}'s contact: {self.name} ({self.relationship})"
 
 
class SOSButton(models.Model):
    """
    Tracks when user manually presses SOS/Help button.
    Immediate crisis intervention triggered.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    pressed_at = models.DateTimeField(auto_now_add=True)
    
    # Context
    user_note = models.TextField(
        blank=True,
        help_text="Optional note from user about what they need"
    )
    
    current_mood = models.IntegerField(
        null=True,
        blank=True,
        help_text="Mood rating when SOS pressed (1-10)"
    )
    
    current_location = models.CharField(
        max_length=200,
        blank=True,
        help_text="User-provided location (optional)"
    )
    
    # Response
    crisis_event = models.OneToOneField(
        CrisisEvent,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    
    user_got_help = models.BooleanField(
        default=False,
        help_text="User confirmed they got help"
    )
    
    resolution_note = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-pressed_at']
        verbose_name = 'SOS Button Press'
        verbose_name_plural = 'SOS Button Presses'
    
    def __str__(self):
        return f"SOS: {self.user.username} - {self.pressed_at}"
 
 
# ==================== NOTIFICATION SYSTEM ====================
 
class NotificationService:
    """
    Handles sending crisis notifications via multiple channels.
    """
    
    @staticmethod
    def send_push_notification(user, title, message, data=None):
        """
        Send push notification to user's device.
        Requires Firebase Cloud Messaging or similar service.
        """
        # Get user's device tokens
        try:
            from .models import UserDevice  # You'll need to create this model
            devices = UserDevice.objects.filter(user=user, notifications_enabled=True)
            
            if not devices.exists():
                return {'success': False, 'reason': 'No devices registered'}
            
            # Example with Firebase (you'll need to set this up)
            # from firebase_admin import messaging
            
            success_count = 0
            for device in devices:
                try:
                    # FCM example
                    # message = messaging.Message(
                    #     notification=messaging.Notification(
                    #         title=title,
                    #         body=message
                    #     ),
                    #     data=data or {},
                    #     token=device.fcm_token
                    # )
                    # messaging.send(message)
                    
                    success_count += 1
                except Exception as e:
                    print(f"Failed to send to device {device.id}: {e}")
            
            return {
                'success': True,
                'devices_notified': success_count,
                'channel': 'push'
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def send_email_notification(to_email, subject, message, html_message=None):
        """
        Send email notification.
        """
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[to_email],
                html_message=html_message,
                fail_silently=False
            )
            
            return {
                'success': True,
                'channel': 'email',
                'recipient': to_email
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def send_sms_notification(phone_number, message):
        """
        Send SMS notification.
        Requires Twilio, AWS SNS, or similar service.
        """
        try:
            # Example with Twilio
            # from twilio.rest import Client
            # 
            # client = Client(
            #     settings.TWILIO_ACCOUNT_SID,
            #     settings.TWILIO_AUTH_TOKEN
            # )
            # 
            # message = client.messages.create(
            #     body=message,
            #     from_=settings.TWILIO_PHONE_NUMBER,
            #     to=phone_number
            # )
            
            return {
                'success': True,
                'channel': 'sms',
                'recipient': phone_number
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def notify_admin_dashboard(crisis_event):
        """
        Create admin dashboard alert for counselors to see.
        """
        try:
            # Create an AdminAlert model (you'll need to create this)
            # AdminAlert.objects.create(
            #     alert_type='crisis',
            #     severity=crisis_event.severity,
            #     user=crisis_event.user,
            #     crisis_event=crisis_event,
            #     message=f"Crisis detected for {crisis_event.user.username}",
            #     requires_review=True
            # )
            
            return {
                'success': True,
                'channel': 'admin_dashboard'
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
 
 
# ==================== CRISIS DETECTION LOGIC ====================
 
class CrisisDetector:
    """
    Analyzes user data to detect crisis situations.
    Multiple detection methods for different types of crises.
    """
    
    @staticmethod
    def check_mood_patterns(user):
        """
        Detect crisis from mood entry patterns.
        """
        from .models import MoodEntry
        from datetime import timedelta
        
        now = timezone.now()
        today = now.date()
        
        # Get recent entries
        recent_entries = MoodEntry.objects.filter(
            user=user,
            timestamp__gte=now - timedelta(days=7)
        )
        
        if not recent_entries.exists():
            return None
        
        # Check 1: Multiple high anxiety today
        today_high_anxiety = recent_entries.filter(
            timestamp__date=today,
            anxiety_level='High'
        ).count()
        
        if today_high_anxiety >= 3:
            return {
                'trigger': 'high_anxiety',
                'severity': 'high',
                'data': {
                    'count': today_high_anxiety,
                    'period': 'today'
                },
                'message': "You've logged high anxiety multiple times today."
            }
        
        # Check 2: Consistent very negative sentiment
        very_negative = recent_entries.filter(
            sentiment_score__lt=-0.7
        ).count()
        
        if very_negative >= 4:
            return {
                'trigger': 'severe_depression',
                'severity': 'high',
                'data': {
                    'count': very_negative,
                    'period': '7 days'
                },
                'message': "Your mood has been consistently very low lately."
            }
        
        # Check 3: Sudden mood drop
        if recent_entries.count() >= 5:
            latest_5 = list(recent_entries.order_by('-timestamp')[:5])
            latest_avg = sum(e.sentiment_score for e in latest_5) / 5
            
            if latest_avg < -0.5:
                return {
                    'trigger': 'severe_depression',
                    'severity': 'medium',
                    'data': {
                        'average_sentiment': latest_avg
                    },
                    'message': "Your mood seems to have dropped recently."
                }
        
        return None
    
    @staticmethod
    def check_stress_assessment(user):
        """
        Detect crisis from stress assessment results.
        """
        from .models import StressAssessmentResponse
        
        # Get most recent assessment
        latest = StressAssessmentResponse.objects.filter(
            user=user
        ).order_by('-session_date').first()
        
        if not latest:
            return None
        
        # Very high overall stress
        if latest.overall_stress_score >= 80:
            return {
                'trigger': 'multiple_high_stress',
                'severity': 'high',
                'data': {
                    'stress_score': latest.overall_stress_score,
                    'primary_stressor': latest.primary_stressor
                },
                'message': "Your stress assessment shows very high stress levels."
            }
        
        # High stress in concerning categories
        concerning_categories = ['bullying', 'family', 'identity']
        for category in concerning_categories:
            score = latest.category_scores.get(category, 0)
            if score >= 75:
                return {
                    'trigger': 'multiple_high_stress',
                    'severity': 'high',
                    'data': {
                        'category': category,
                        'score': score
                    },
                    'message': f"You're experiencing very high stress related to {category}."
                }
        
        return None
    
    @staticmethod
    def check_sleep_deprivation(user):
        """
        Detect extreme sleep deprivation (crisis indicator).
        """
        from .models import SleepLog
        from datetime import timedelta
        
        # Last 3 days
        three_days_ago = timezone.now() - timedelta(days=3)
        recent_sleep = SleepLog.objects.filter(
            user=user,
            date__gte=three_days_ago.date()
        )
        
        if recent_sleep.count() < 3:
            return None
        
        # Check for consistent very low sleep
        low_sleep_count = recent_sleep.filter(hours_slept__lt=4).count()
        
        if low_sleep_count >= 3:
            return {
                'trigger': 'sleep_deprivation',
                'severity': 'medium',
                'data': {
                    'days': 3,
                    'average_hours': recent_sleep.aggregate(
                        models.Avg('hours_slept')
                    )['hours_slept__avg']
                },
                'message': "You've been getting very little sleep. This can seriously affect your mental health."
            }
        
        return None
    
    @staticmethod
    def check_all(user):
        """
        Run all crisis detection checks.
        Returns highest severity crisis detected or None.
        """
        checks = [
            CrisisDetector.check_mood_patterns(user),
            CrisisDetector.check_stress_assessment(user),
            CrisisDetector.check_sleep_deprivation(user)
        ]
        
        # Filter out None results
        detected_crises = [c for c in checks if c is not None]
        
        if not detected_crises:
            return None
        
        # Return highest severity
        severity_order = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}
        detected_crises.sort(
            key=lambda x: severity_order.get(x['severity'], 0),
            reverse=True
        )
        
        return detected_crises[0]
 
 

# ==================== PRIVACY SETTINGS ====================
 
class UserPrivacySettings(models.Model):
    """
    User's privacy preferences and consent tracking.
    Makes privacy controls visible and user-controlled.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='privacy_settings'
    )
    
    # Data visibility
    data_visible_to_counselors = models.BooleanField(
        default=False,
        help_text="Allow campus counselors to see your check-ins (for follow-up support)"
    )
    
    data_visible_to_researchers = models.BooleanField(
        default=False,
        help_text="Allow anonymized data for mental health research"
    )
    
    # Crisis notifications
    crisis_alerts_enabled = models.BooleanField(
        default=True,
        help_text="Show crisis resources when high stress detected"
    )
    
    can_notify_trusted_contacts = models.BooleanField(
        default=False,
        help_text="Allow app to notify trusted contacts in crisis"
    )
    
    # App notifications
    reminder_notifications = models.BooleanField(
        default=True,
        help_text="Daily check-in reminders"
    )
    
    encouragement_notifications = models.BooleanField(
        default=True,
        help_text="Supportive messages and affirmations"
    )
    
    # Data retention
    auto_delete_old_entries = models.BooleanField(
        default=False,
        help_text="Automatically delete mood entries older than 90 days"
    )
    
    # Consent tracking
    accepted_privacy_policy = models.BooleanField(default=False)
    privacy_policy_accepted_at = models.DateTimeField(null=True, blank=True)
    privacy_policy_version = models.CharField(max_length=10, default="1.0")
    
    # What user knows
    viewed_privacy_statement = models.BooleanField(default=False)
    last_privacy_review = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "User Privacy Settings"
        verbose_name_plural = "User Privacy Settings"
    
    def __str__(self):
        return f"{self.user.username}'s Privacy Settings"
    
    def accept_privacy_policy(self, version="1.0"):
        """User accepts privacy policy."""
        self.accepted_privacy_policy = True
        self.privacy_policy_accepted_at = timezone.now()
        self.privacy_policy_version = version
        self.save()
    
    def review_privacy_statement(self):
        """Track when user reviews privacy info."""
        self.viewed_privacy_statement = True
        self.last_privacy_review = timezone.now()
        self.save()
 
 
class DataAccessLog(models.Model):
    """
    Log who accessed user's data and when.
    Transparency: users can see exactly who viewed their info.
    """
    ACCESS_TYPES = [
        ('user_view', 'User Viewed Own Data'),
        ('counselor_view', 'Counselor Viewed (with permission)'),
        ('admin_view', 'Admin Viewed'),
        ('export', 'Data Export'),
        ('delete', 'Data Deletion'),
        ('crisis_alert', 'Crisis Alert Triggered'),
    ]
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='data_access_logs'
    )
    
    accessed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='data_accesses'
    )
    
    access_type = models.CharField(max_length=20, choices=ACCESS_TYPES)
    
    # What was accessed
    data_accessed = models.TextField(
        help_text="Description of what data was accessed"
    )
    
    # Context
    reason = models.TextField(
        blank=True,
        help_text="Why this access occurred"
    )
    
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    accessed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-accessed_at']
        verbose_name = "Data Access Log"
    
    def __str__(self):
        return f"{self.user.username} - {self.get_access_type_display()} - {self.accessed_at.date()}"
 
 
class PrivacyEducation(models.Model):
    """
    Privacy education content shown to users.
    Explains what happens to their data in simple terms.
    """
    TOPIC_TYPES = [
        ('who_sees', 'Who Can See My Data'),
        ('parents', 'Can Parents Access This'),
        ('school', 'Does This Go In My Record'),
        ('deletion', 'How To Delete My Data'),
        ('crisis', 'What Happens In Crisis'),
        ('research', 'How Data Helps Research'),
    ]
    
    topic = models.CharField(max_length=20, choices=TOPIC_TYPES, unique=True)
    
    # Simple explanation
    question = models.CharField(
        max_length=200,
        help_text="User's question (e.g., 'Who can see my data?')"
    )
    
    short_answer = models.TextField(
        help_text="Quick 1-2 sentence answer"
    )
    
    detailed_answer = models.TextField(
        help_text="Full explanation with examples"
    )
    
    # Examples
    example_scenarios = models.JSONField(
        default=list,
        help_text="Real examples of how this works"
    )
    
    # User controls
    related_setting = models.CharField(
        max_length=100,
        blank=True,
        help_text="Privacy setting this relates to"
    )
    
    priority = models.IntegerField(
        default=0,
        help_text="Higher priority shown first"
    )
    
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-priority', 'question']
    
    def __str__(self):
        return self.question
    
# ==================== ADAPTIVE QUIZ SYSTEM ====================
 
class QuizSession(models.Model):
    """
    Tracks adaptive quiz sessions.
    Intelligently selects which questions to ask based on previous answers.
    """
    QUIZ_MODES = [
        ('quick', 'Quick Check (10 questions)'),
        ('standard', 'Standard (15 questions)'),
        ('comprehensive', 'Comprehensive (20 questions)'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    quiz_mode = models.CharField(
        max_length=20,
        choices=QUIZ_MODES,
        default='quick'
    )
    
    # User's category selection (if using category-selection mode)
    selected_categories = models.JSONField(
        default=list,
        help_text="Which stress categories user selected to assess"
    )
    
    # Questions asked and answered
    questions_asked = models.JSONField(
        default=list,
        help_text="List of question IDs asked in this session"
    )
    
    responses = models.JSONField(
        default=dict,
        help_text="Question ID to score mapping"
    )
    
    # Progress tracking
    current_question_index = models.IntegerField(default=0)
    total_questions = models.IntegerField(default=10)
    
    # Results (calculated on completion)
    assessment_response = models.ForeignKey(
        'StressAssessmentResponse',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quiz_session'
    )
    
    is_complete = models.BooleanField(default=False)
    completion_time_seconds = models.IntegerField(null=True, blank=True)
    
    class Meta:
        ordering = ['-started_at']
    
    def __str__(self):
        return f"{self.user.username} - Quiz {self.started_at.date()}"
    
    @property
    def progress_percentage(self):
        """Calculate progress through quiz."""
        if self.total_questions == 0:
            return 0
        return int((self.current_question_index / self.total_questions) * 100)
    
    @property
    def questions_remaining(self):
        """How many questions left."""
        return self.total_questions - self.current_question_index
    
    def mark_complete(self):
        """Mark quiz as completed."""
        self.is_complete = True
        self.completed_at = timezone.now()
        if self.started_at:
            delta = self.completed_at - self.started_at
            self.completion_time_seconds = int(delta.total_seconds())
        self.save()
 
 
# ==================== ADAPTIVE QUESTION SELECTOR ====================
 
class AdaptiveQuestionSelector:
    """
    Intelligently selects which questions to ask based on:
    1. User's selected categories (if any)
    2. Previous answers (adaptive branching)
    3. Question importance/weight
    """
    
    @staticmethod
    def get_initial_questions(mode='quick'):
        """
        Get starter questions (2 per category).
        These are high-level screening questions.
        """
        from .models import StressCategory, StressAssessmentQuestion
        
        questions_per_category = 1 if mode == 'quick' else 2
        
        # Get all active categories
        categories = StressCategory.objects.filter(is_active=True)
        
        initial_questions = []
        for category in categories:
            # Get highest-weight questions from this category
            category_questions = StressAssessmentQuestion.objects.filter(
                category=category,
                is_active=True
            ).order_by('-weight', 'order')[:questions_per_category]
            
            initial_questions.extend(category_questions)
        
        # Randomize order to prevent bias
        random.shuffle(initial_questions)
        
        return initial_questions
    
    @staticmethod
    def get_follow_up_questions(session):
        """
        Based on initial answers, ask follow-up questions in high-scoring categories.
        """
        from .models import StressCategory, StressAssessmentQuestion
        
        # Calculate which categories have high scores so far
        category_scores = {}
        
        for question_id, score in session.responses.items():
            try:
                question = StressAssessmentQuestion.objects.get(id=question_id)
                cat_type = question.category.category_type
                
                if cat_type not in category_scores:
                    category_scores[cat_type] = []
                
                category_scores[cat_type].append(score)
            except StressAssessmentQuestion.DoesNotExist:
                continue
        
        # Calculate average score per category
        category_averages = {
            cat: sum(scores) / len(scores)
            for cat, scores in category_scores.items()
        }
        
        # Sort categories by average score (highest first)
        sorted_categories = sorted(
            category_averages.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # Ask 3-5 more questions from top 2-3 categories
        follow_up_questions = []
        top_categories = sorted_categories[:3]  # Top 3 problem areas
        
        for cat_type, avg_score in top_categories:
            if avg_score >= 2:  # Only if showing some stress
                category = StressCategory.objects.get(category_type=cat_type)
                
                # Get questions not yet asked
                asked_ids = session.questions_asked
                available_questions = StressAssessmentQuestion.objects.filter(
                    category=category,
                    is_active=True
                ).exclude(id__in=asked_ids).order_by('-weight')
                
                # Add 1-2 more questions from this category
                follow_up_questions.extend(available_questions[:2])
        
        return follow_up_questions[:5]  # Max 5 follow-up questions
    
    @staticmethod
    def get_next_question(session):
        """
        Get the next question to ask in this adaptive quiz.
        """
        from .models import StressAssessmentQuestion
        
        # If just started, get initial questions
        if session.current_question_index == 0:
            initial = AdaptiveQuestionSelector.get_initial_questions(session.quiz_mode)
            session.questions_asked = [q.id for q in initial]
            session.total_questions = len(initial) + 5  # Estimate
            session.save()
            return initial[0] if initial else None
        
        # If we've asked all initial questions
        if session.current_question_index >= len(session.questions_asked):
            # Time for follow-ups based on scores
            follow_ups = AdaptiveQuestionSelector.get_follow_up_questions(session)
            
            if follow_ups:
                # Add follow-up questions to session
                new_question_ids = [q.id for q in follow_ups]
                session.questions_asked.extend(new_question_ids)
                session.total_questions = len(session.questions_asked)
                session.save()
                return follow_ups[0]
            else:
                # No more questions needed
                return None
        
        # Get next question from our list
        next_question_id = session.questions_asked[session.current_question_index]
        try:
            return StressAssessmentQuestion.objects.get(id=next_question_id)
        except StressAssessmentQuestion.DoesNotExist:
            return None
 
 
# ==================== CATEGORY SELECTION MODE ====================
 
class CategorySelectionQuiz:
    """
    Alternative mode: User selects which categories to assess,
    then only gets questions about those categories.
    """
    
    @staticmethod
    def get_questions_for_categories(category_types, questions_per_category=3):
        """
        Get questions only for selected categories.
        
        Example:
        User selects: ['social', 'romantic', 'body_image']
        → Gets 3 questions each = 9 questions total
        """
        from .models import StressCategory, StressAssessmentQuestion
        
        all_questions = []
        
        for cat_type in category_types:
            try:
                category = StressCategory.objects.get(
                    category_type=cat_type,
                    is_active=True
                )
                
                # Get top weighted questions from this category
                questions = StressAssessmentQuestion.objects.filter(
                    category=category,
                    is_active=True
                ).order_by('-weight', 'order')[:questions_per_category]
                
                all_questions.extend(questions)
            except StressCategory.DoesNotExist:
                continue
        
        # Randomize order
        random.shuffle(all_questions)
        
        return all_questions
    
# ==================== TIERED SUPPORT RECOMMENDATIONS ====================
 
class SupportRecommendation(models.Model):
    """
    Support recommendations based on stress level.
    NOT just crisis hotlines - appropriate support for each level.
    """
    STRESS_LEVELS = [
        ('minimal', 'Minimal (0-30%)'),
        ('low', 'Low (30-50%)'),
        ('moderate', 'Moderate (50-70%)'),
        ('high', 'High (70-85%)'),
        ('crisis', 'Crisis (85%+)'),
    ]
    
    RECOMMENDATION_TYPES = [
        ('self_care', 'Self-Care Activity'),
        ('mood_booster', 'Mood Booster'),
        ('counseling', 'Counseling/Therapy'),
        ('support_group', 'Support Group'),
        ('crisis_resource', 'Crisis Resource'),
        ('academic_support', 'Academic Support'),
        ('peer_support', 'Peer Support'),
    ]
    
    stress_level = models.CharField(max_length=20, choices=STRESS_LEVELS)
    recommendation_type = models.CharField(max_length=30, choices=RECOMMENDATION_TYPES)
    
    title = models.CharField(max_length=200)
    description = models.TextField()
    
    # Action details
    action_label = models.CharField(
        max_length=100,
        help_text="Button text (e.g., 'Try Now', 'Schedule Appointment', 'Learn More')"
    )
    
    action_type = models.CharField(
        max_length=20,
        choices=[
            ('internal', 'In-App Action'),
            ('external_link', 'External Link'),
            ('phone', 'Phone Call'),
            ('email', 'Email'),
        ],
        default='internal'
    )
    
    action_value = models.TextField(
        help_text="URL, phone number, email, or internal route"
    )
    
    # Urgency
    urgency_level = models.IntegerField(
        default=1,
        help_text="1=Gentle suggestion, 5=Urgent recommendation"
    )
    
    # Messaging
    message_tone = models.CharField(
        max_length=20,
        choices=[
            ('encouraging', 'Encouraging'),
            ('gentle', 'Gentle'),
            ('firm', 'Firm but Kind'),
            ('urgent', 'Urgent'),
        ],
        default='encouraging'
    )
    
    priority = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['stress_level', '-priority']
    
    def __str__(self):
        return f"{self.get_stress_level_display()}: {self.title}"
 
 
# ==================== PROGRESS TRACKING ====================
 
class ProgressMilestone(models.Model):
    """
    Celebrate user achievements and improvements.
    Focus on progress, not just problems.
    """
    MILESTONE_TYPES = [
        ('streak', 'Check-in Streak'),
        ('improvement', 'Mood/Stress Improvement'),
        ('coping_usage', 'Used Coping Strategies'),
        ('completion', 'Completed Assessment'),
        ('resource_accessed', 'Accessed Support Resource'),
        ('consistency', 'Consistent Self-Care'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    milestone_type = models.CharField(max_length=30, choices=MILESTONE_TYPES)
    
    # Achievement details
    title = models.CharField(max_length=200)
    description = models.TextField()
    emoji = models.CharField(max_length=10, default="🎉")
    
    # Data
    metric_value = models.FloatField(
        help_text="The actual number (e.g., 7 days, 20% improvement)"
    )
    metric_label = models.CharField(
        max_length=100,
        help_text="What the number means (e.g., 'days', 'percent improvement')"
    )
    
    achieved_at = models.DateTimeField(auto_now_add=True)
    
    # User engagement
    user_viewed = models.BooleanField(default=False)
    user_shared = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-achieved_at']
    
    def __str__(self):
        return f"{self.user.username}: {self.title}"
 
 
class WeeklyProgressReport(models.Model):
    """
    Weekly summary of user's progress.
    Highlights improvements, not just current status.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    week_start = models.DateField()
    week_end = models.DateField()
    
    # Engagement metrics
    check_ins_this_week = models.IntegerField(default=0)
    mood_boosters_tried = models.IntegerField(default=0)
    coping_strategies_used = models.IntegerField(default=0)
    
    # Outcomes
    avg_stress_this_week = models.FloatField(null=True, blank=True)
    avg_stress_last_week = models.FloatField(null=True, blank=True)
    stress_change = models.FloatField(
        null=True,
        blank=True,
        help_text="Negative = improvement, Positive = increase"
    )
    
    avg_mood_this_week = models.FloatField(null=True, blank=True)
    avg_mood_last_week = models.FloatField(null=True, blank=True)
    mood_change = models.FloatField(
        null=True,
        blank=True,
        help_text="Positive = improvement"
    )
    
    # Highlights
    biggest_improvement = models.TextField(blank=True)
    most_helpful_activity = models.TextField(blank=True)
    
    # Recommendations
    suggested_focus = models.TextField(
        blank=True,
        help_text="What to focus on next week"
    )
    
    generated_at = models.DateTimeField(auto_now_add=True)
    user_viewed = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-week_start']
        unique_together = ['user', 'week_start']
    
    def __str__(self):
        return f"{self.user.username} - Week of {self.week_start}"
    
    @property
    def is_improving(self):
        """Check if user is trending better."""
        return (
            (self.stress_change and self.stress_change < -5) or
            (self.mood_change and self.mood_change > 5)
        )
    
    @property
    def progress_summary(self):
        """Human-readable progress summary."""
        if self.is_improving:
            return "You're making great progress! 📈"
        elif self.check_ins_this_week >= 5:
            return "You're staying consistent! 💪"
        else:
            return "Keep going - you're doing your best! 💙"
 
 
# ==================== TIERED SUPPORT GENERATOR ====================
 
class TieredSupportGenerator:
    """
    Generates appropriate support recommendations based on stress level.
    """
    
    @staticmethod
    def get_support_for_level(stress_score):
        """
        Get tiered support recommendations based on stress score.
        
        Returns:
        {
            'level': 'moderate',
            'message': '...',
            'tone': 'gentle',
            'recommendations': [...]
        }
        """
        if stress_score is None:
            stress_score = 0.0
        else:
            try:
                stress_score = float(stress_score)
            except (TypeError, ValueError):
                stress_score = 0.0
        # Determine stress level
        if stress_score < 30:
            level = 'minimal'
            message = "You're managing well! 💚 Keep up your self-care routine."
            tone = 'encouraging'
        elif stress_score < 50:
            level = 'low'
            message = "You're handling things pretty well. 💙 Let's make sure you stay supported."
            tone = 'encouraging'
        elif stress_score < 70:
            level = 'moderate'
            message = "You're dealing with a fair amount of stress. 💛 It's important to use coping strategies and reach out for support."
            tone = 'gentle'
        elif stress_score < 85:
            level = 'high'
            message = "You're under significant stress right now. 🧡 We're concerned - please consider reaching out to someone today."
            tone = 'firm'
        else:
            level = 'crisis'
            message = "You're experiencing very high stress levels. ❤️ Please reach out for support right now. You don't have to go through this alone."
            tone = 'urgent'
        
        # Get recommendations for this level
        recommendations = SupportRecommendation.objects.filter(
            stress_level=level,
            is_active=True
        ).order_by('-priority')[:5]
        
        return {
            'level': level,
            'score': stress_score,
            'message': message,
            'tone': tone,
            'recommendations': [
                {
                    'title': rec.title,
                    'description': rec.description,
                    'action_label': rec.action_label,
                    'action_type': rec.action_type,
                    'action_value': rec.action_value,
                    'urgency': rec.urgency_level
                }
                for rec in recommendations
            ],
            'next_steps': TieredSupportGenerator._get_next_steps(level, stress_score)
        }
    
    @staticmethod
    def _get_next_steps(level, score):
        """Get specific next steps for this stress level."""
        steps = {
            'minimal': [
                "Keep doing what you're doing - you're managing well",
                "Try a mood booster when you need a pick-me-up",
                "Check in with yourself regularly"
            ],
            'low': [
                "Continue your current coping strategies",
                "Try a new mood booster this week",
                "Stay connected with supportive friends/family"
            ],
            'moderate': [
                "Talk to someone you trust about what's going on",
                "Try the coping strategies we suggested",
                "Make time for activities that recharge you",
                "Consider talking to a campus counselor"
            ],
            'high': [
                "Please talk to a trusted adult or counselor today",
                "Use campus counseling walk-in hours if available",
                "Try gentle mood boosters (even small things help)",
                "Text Crisis Line (741741) if you need immediate support",
                "Remember: asking for help is brave and smart"
            ],
            'crisis': [
                "Please reach out to a crisis resource RIGHT NOW",
                "Call 988 or text 741741 - they're here 24/7",
                "Tell someone you trust that you're struggling",
                "Go to campus counseling or nearest ER if you feel unsafe",
                "You deserve support - please don't wait"
            ]
        }
        
        return steps.get(level, [])
 
 
# ==================== PROGRESS CALCULATOR ====================
 
class ProgressCalculator:
    """
    Calculates user progress and generates achievements.
    """
    
    @staticmethod
    def calculate_weekly_progress(user):
        """Generate weekly progress report."""
        from .models import MoodEntry, MoodBoosterUsage, StressAssessmentResponse
        
        # Define week boundaries
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        last_week_start = week_start - timedelta(days=7)
        last_week_end = week_start - timedelta(days=1)
        
        # Get this week's data
        this_week_moods = MoodEntry.objects.filter(
            user=user,
            timestamp__date__gte=week_start,
            timestamp__date__lte=week_end
        )
        
        this_week_boosters = MoodBoosterUsage.objects.filter(
            user=user,
            tried_at__date__gte=week_start,
            tried_at__date__lte=week_end
        )
        
        # Get last week's data for comparison
        last_week_moods = MoodEntry.objects.filter(
            user=user,
            timestamp__date__gte=last_week_start,
            timestamp__date__lte=last_week_end
        )
        
        # Calculate averages
        this_week_stress = this_week_moods.aggregate(
            models.Avg('stress_level')
        )['stress_level__avg']
        
        last_week_stress = last_week_moods.aggregate(
            models.Avg('stress_level')
        )['stress_level__avg']
        
        # Create or update report
        report, created = WeeklyProgressReport.objects.get_or_create(
            user=user,
            week_start=week_start,
            defaults={
                'week_end': week_end,
                'check_ins_this_week': this_week_moods.count(),
                'mood_boosters_tried': this_week_boosters.count(),
                'avg_stress_this_week': this_week_stress,
                'avg_stress_last_week': last_week_stress,
                'stress_change': (this_week_stress - last_week_stress) if (this_week_stress and last_week_stress) else None
            }
        )
        
        # Generate highlights
        if report.check_ins_this_week >= 5:
            report.biggest_improvement = f"Checked in {report.check_ins_this_week} times this week! 🌟"
        
        if report.stress_change and report.stress_change < -10:
            report.biggest_improvement = f"Stress decreased by {abs(report.stress_change):.0f}%! 📉"
        
        # Most helpful activity
        most_helpful = this_week_boosters.filter(
            did_it_help=True
        ).values('booster__title').annotate(
            count=models.Count('id')
        ).order_by('-count').first()
        
        if most_helpful:
            report.most_helpful_activity = most_helpful['booster__title']
        
        report.save()
        
        return report
    @classmethod
    def _get_encouragement(cls, score_input):
    # If a full object was passed instead of a number, get the score from it
        score = getattr(score_input, 'overall_score', score_input)
    
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0

        if score >= 80:
            return "You're doing amazing! Your consistency is paying off."
        elif score >= 50:
            return "Good progress! You're building solid healthy habits."
        return "Every small step counts. Keep moving forward!"
    
    @staticmethod
    def check_for_milestones(user):
        """Check if user achieved any new milestones."""
        from .models import MoodEntry, UserStats
        
        milestones = []
        
        # Get user stats
        stats, _ = UserStats.objects.get_or_create(user=user)
        
        # Check streak milestones
        if stats.current_streak == 7:
            milestone = ProgressMilestone.objects.create(
                user=user,
                milestone_type='streak',
                title="Week Warrior! 🔥",
                description=f"You've checked in for {stats.current_streak} days straight!",
                emoji="🔥",
                metric_value=stats.current_streak,
                metric_label="days"
            )
            milestones.append(milestone)
        
        # Check improvement milestones
        recent_assessments = StressAssessmentResponse.objects.filter(
            user=user
        ).order_by('-session_date')[:2]
        
        if len(recent_assessments) == 2:
            improvement = recent_assessments[1].overall_stress_score - recent_assessments[0].overall_stress_score
            
            if improvement >= 15:
                milestone = ProgressMilestone.objects.create(
                    user=user,
                    milestone_type='improvement',
                    title="Stress Slayer! 📉",
                    description=f"Your stress decreased by {improvement:.0f}%!",
                    emoji="📉",
                    metric_value=improvement,
                    metric_label="percent decrease"
                )
                milestones.append(milestone)
        
        return milestones
    
# ==================== FIX #4: INTERACTIVE MOOD BOOSTERS ====================
 
class InteractiveMoodBooster(models.Model):
    """
    Mood boosters with interactive components (animations, sounds, timers).
    Not just text instructions - actually guides you through the activity.
    """
    
    INTERACTION_TYPES = [
        ('breathing_animation', 'Animated Breathing Circle'),
        ('guided_audio', 'Audio Guidance'),
        ('timer_with_prompts', 'Timer with Step Prompts'),
        ('interactive_game', 'Interactive Mini-Game'),
        ('video_guided', 'Video Guided Activity'),
    ]
    
    # Link to base mood booster
    base_booster = models.OneToOneField(
        'MoodBooster',
        on_delete=models.CASCADE,
        related_name='interactive_version'
    )
    
    interaction_type = models.CharField(max_length=30, choices=INTERACTION_TYPES)
    
    # Interactive elements
    has_animation = models.BooleanField(default=False)
    animation_config = models.JSONField(
        default=dict,
        help_text="Animation settings (e.g., breathing circle timing)"
    )
    
    has_audio = models.BooleanField(default=False)
    audio_file_url = models.URLField(blank=True)
    
    has_haptic_feedback = models.BooleanField(
        default=False,
        help_text="Vibration cues (mobile only)"
    )
    
    # Step-by-step guidance
    interactive_steps = models.JSONField(
        default=list,
        help_text="""
        Example for breathing:
        [
            {"step": 1, "action": "breathe_in", "duration": 4, "prompt": "Breathe in...", "haptic": true},
            {"step": 2, "action": "hold", "duration": 4, "prompt": "Hold...", "haptic": false},
            {"step": 3, "action": "breathe_out", "duration": 4, "prompt": "Breathe out...", "haptic": true}
        ]
        """
    )
    
    # Completion
    auto_complete = models.BooleanField(
        default=True,
        help_text="Auto-detect when user completes activity"
    )
    
    completion_duration_seconds = models.IntegerField(
        default=120,
        help_text="How long activity takes (for auto-completion)"
    )
    
    class Meta:
        verbose_name = "Interactive Mood Booster"
    
    def __str__(self):
        return f"Interactive: {self.base_booster.title}"
 
 
# Example Interactive Booster Configs
"""
BREATHING ANIMATION CONFIG:
{
    "type": "circle",
    "breathe_in_duration": 4,
    "hold_duration": 4,
    "breathe_out_duration": 4,
    "cycles": 4,
    "circle_color": "#667eea",
    "background_color": "#f7fafc",
    "prompt_text_color": "#2d3748"
}
 
GUIDED MEDITATION CONFIG:
{
    "steps": [
        {"time": 0, "prompt": "Find a comfortable position", "duration": 10},
        {"time": 10, "prompt": "Close your eyes and relax", "duration": 10},
        {"time": 20, "prompt": "Notice your breathing", "duration": 20},
        {"time": 40, "prompt": "Let thoughts pass like clouds", "duration": 30}
    ],
    "background_audio": "https://example.com/calm-sounds.mp3",
    "total_duration": 120
}
"""
 
 
# ==================== FIX #5: SMART REMINDERS ====================
 
class ReminderPreference(models.Model):
    """
    User's reminder preferences.
    Customizable, smart, and respectful of boundaries.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='reminder_prefs'
    )
    
    # General settings
    reminders_enabled = models.BooleanField(default=True)
    
    # Check-in reminders
    daily_checkin_enabled = models.BooleanField(default=True)
    checkin_time = models.TimeField(
        default=time(20, 0),  # 8 PM default
        help_text="Preferred time for daily check-in reminder"
    )
    
    # Smart reminders (context-aware)
    after_stress_spike = models.BooleanField(
        default=True,
        help_text="Remind after detecting high stress"
    )
    
    after_mood_booster = models.BooleanField(
        default=True,
        help_text="Follow up after completing mood booster"
    )
    
    weekly_progress_summary = models.BooleanField(
        default=True,
        help_text="Weekly progress report"
    )
    
    # Quiet hours
    quiet_hours_enabled = models.BooleanField(default=False)
    quiet_start = models.TimeField(default=time(22, 0))  # 10 PM
    quiet_end = models.TimeField(default=time(8, 0))  # 8 AM
    
    # Frequency limits
    max_reminders_per_day = models.IntegerField(
        default=3,
        help_text="Maximum reminders per day"
    )
    
    # Days of week
    monday = models.BooleanField(default=True)
    tuesday = models.BooleanField(default=True)
    wednesday = models.BooleanField(default=True)
    thursday = models.BooleanField(default=True)
    friday = models.BooleanField(default=True)
    saturday = models.BooleanField(default=True)
    sunday = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Reminder Preferences"
    
    def __str__(self):
        return f"{self.user.username}'s Reminder Preferences"
    
    def is_quiet_time(self, check_time=None):
        """Check if current time is in quiet hours."""
        if not self.quiet_hours_enabled:
            return False
        
        check_time = check_time or timezone.now().time()
        
        if self.quiet_start < self.quiet_end:
            # Same day (e.g., 10 PM to 11 PM)
            return self.quiet_start <= check_time <= self.quiet_end
        else:
            # Crosses midnight (e.g., 10 PM to 8 AM)
            return check_time >= self.quiet_start or check_time <= self.quiet_end
    
    def should_send_today(self):
        """Check if reminders should be sent today."""
        today = timezone.now().strftime('%A').lower()
        return getattr(self, today, True)
 
 
class ScheduledReminder(models.Model):
    """
    Scheduled reminder to be sent to user.
    Can be recurring or one-time.
    """
    REMINDER_TYPES = [
        ('daily_checkin', 'Daily Check-in'),
        ('follow_up_stress', 'Follow-up After High Stress'),
        ('follow_up_booster', 'Follow-up After Mood Booster'),
        ('weekly_progress', 'Weekly Progress Summary'),
        ('encouragement', 'Random Encouragement'),
        ('milestone_celebration', 'Achievement Unlocked'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    reminder_type = models.CharField(max_length=30, choices=REMINDER_TYPES)
    
    # Timing
    scheduled_for = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    
    # Content
    title = models.CharField(max_length=200)
    message = models.TextField()
    
    # Action
    action_label = models.CharField(
        max_length=100,
        blank=True,
        help_text="Button text (e.g., 'Check In Now', 'View Progress')"
    )
    action_route = models.CharField(
        max_length=200,
        blank=True,
        help_text="Where to navigate when clicked"
    )
    
    # Status
    is_sent = models.BooleanField(default=False)
    was_opened = models.BooleanField(default=False)
    was_acted_on = models.BooleanField(default=False)
    
    # Recurring
    is_recurring = models.BooleanField(default=False)
    recurrence_rule = models.CharField(
        max_length=50,
        blank=True,
        help_text="e.g., 'daily', 'weekly'"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['scheduled_for']
    
    def __str__(self):
        return f"{self.user.username} - {self.get_reminder_type_display()}"
    
    def mark_sent(self):
        """Mark reminder as sent."""
        self.is_sent = True
        self.sent_at = timezone.now()
        self.save()
    
    def mark_opened(self):
        """User opened the notification."""
        self.was_opened = True
        self.save()
    
    def mark_acted_on(self):
        """User took action from notification."""
        self.was_acted_on = True
        self.save()
 
 
# ==================== FIX #6: CONTEXT-AWARE AFFIRMATIONS ====================
 
class ContextAwareAffirmation(models.Model):
    """
    Affirmations that adapt based on user's current situation.
    Not generic - specific to what they're going through.
    """
    
    # Base affirmation
    base_affirmation = models.ForeignKey(
        'DailyAffirmation',
        on_delete=models.CASCADE,
        related_name='context_versions'
    )
    
    # Context triggers
    CONTEXT_TYPES = [
        ('high_anxiety', 'After High Anxiety'),
        ('sleep_deprivation', 'After Poor Sleep'),
        ('social_stress', 'After Social Stress'),
        ('romantic_stress', 'After Relationship Stress'),
        ('academic_pressure', 'During Exam Period'),
        ('body_image_stress', 'Body Image Concerns'),
        ('loneliness', 'Feeling Lonely'),
        ('improvement', 'After Improvement'),
        ('setback', 'After Setback'),
    ]
    
    context_type = models.CharField(max_length=30, choices=CONTEXT_TYPES)
    
    # Contextual message
    contextual_message = models.TextField(
        help_text="Affirmation tailored to this specific context"
    )
    
    # Additional context
    explanation = models.TextField(
        blank=True,
        help_text="Why they might be feeling this way (optional)"
    )
    
    suggested_action = models.TextField(
        blank=True,
        help_text="Gentle suggestion for what to do (optional)"
    )
    
    priority = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-priority', 'context_type']
    
    def __str__(self):
        return f"{self.get_context_type_display()}: {self.contextual_message[:50]}..."
 
 
# Example Context-Aware Affirmations
"""
CONTEXT: high_anxiety
MESSAGE: "Social situations are hard because your brain is trying to protect you. 
That's not weakness - that's your survival instinct working overtime. You're 
navigating something genuinely difficult."
 
CONTEXT: sleep_deprivation
MESSAGE: "Sleep deprivation literally changes your brain chemistry. If today 
feels harder than usual, that's why. Be gentle with yourself - you're doing 
your best on less-than-ideal fuel."
 
CONTEXT: romantic_stress
MESSAGE: "First heartbreaks feel catastrophic because this is genuinely new pain 
your brain hasn't processed before. Future you will look back with wisdom, but 
right now, this hurts. That's okay."
 
CONTEXT: academic_pressure
MESSAGE: "Your worth isn't determined by your grades. You're a whole person with 
value that has nothing to do with test scores. Do your best, but know that you're 
enough regardless of the outcome."
 
CONTEXT: improvement
MESSAGE: "Look at you! Your stress decreased by 20% this week. That's not luck - 
that's you actively working on your wellbeing. You're literally rewiring your 
brain's stress response. Keep going!"
"""
 
 
# ==================== SMART REMINDER GENERATOR ====================
 
class SmartReminderGenerator:
    """
    Generates context-aware reminders based on user behavior.
    """
    
    @staticmethod
    def generate_after_high_stress(user):
        """Send supportive reminder after detecting high stress."""
        from datetime import timedelta
        
        # Schedule for 2 hours later
        send_time = timezone.now() + timedelta(hours=2)
        
        reminder = ScheduledReminder.objects.create(
            user=user,
            reminder_type='follow_up_stress',
            scheduled_for=send_time,
            title="How are you feeling?",
            message="You checked in with high stress earlier. Just wanted to see how you're doing now. 💙",
            action_label="Quick Check-in",
            action_route="/check-in"
        )
        
        return reminder
    
    @staticmethod
    def generate_after_mood_booster(user, booster_usage):
        """Ask how user feels after trying a mood booster."""
        from datetime import timedelta
        
        # Send 30 minutes after trying activity
        send_time = booster_usage.tried_at + timedelta(minutes=30)
        
        reminder = ScheduledReminder.objects.create(
            user=user,
            reminder_type='follow_up_booster',
            scheduled_for=send_time,
            title="How did it go?",
            message=f"You tried {booster_usage.booster.title} - did it help? Let us know! 🌟",
            action_label="Rate Activity",
            action_route=f"/mood-boosters/{booster_usage.booster.id}/rate"
        )
        
        return reminder
    
    @staticmethod
    def generate_weekly_progress(user):
        """Send weekly progress summary."""
        # Send Sunday evening
        reminder = ScheduledReminder.objects.create(
            user=user,
            reminder_type='weekly_progress',
            scheduled_for=timezone.now(),  # Calculate next Sunday
            title="Your Week in Review 📊",
            message="See how you did this week and celebrate your progress!",
            action_label="View Progress",
            action_route="/progress",
            is_recurring=True,
            recurrence_rule='weekly'
        )
        
        return reminder
 
 
# ==================== CONTEXT-AWARE AFFIRMATION SELECTOR ====================
 
class ContextAwareAffirmationSelector:
    """
    Selects the most appropriate affirmation based on user's recent activity.
    """
    
    @staticmethod
    def get_affirmation_for_user(user):
        """
        Get personalized affirmation based on user's recent context.
        """
        from .models import MoodEntry, SleepLog, StressAssessmentResponse
        from datetime import timedelta
        
        # Check recent mood entries
        recent_moods = MoodEntry.objects.filter(
            user=user,
            timestamp__gte=timezone.now() - timedelta(days=1)
        ).order_by('-timestamp')
        
        # Determine context
        context = None
        
        if recent_moods.exists():
            latest = recent_moods.first()
            
            # High anxiety
            if latest.anxiety_level == 'High':
                context = 'high_anxiety'
            
            # Check sleep
            recent_sleep = SleepLog.objects.filter(
                user=user,
                date__gte=timezone.now().date() - timedelta(days=1)
            ).first()
            
            if recent_sleep and recent_sleep.hours_slept < 5:
                context = 'sleep_deprivation'
        
        # Check recent stress assessment
        latest_assessment = StressAssessmentResponse.objects.filter(
            user=user
        ).order_by('-session_date').first()
        
        if latest_assessment and latest_assessment.primary_stressor:
            stress_context_map = {
                'social': 'social_stress',
                'romantic': 'romantic_stress',
                'academic': 'academic_pressure',
                'body_image': 'body_image_stress',
                'loneliness': 'loneliness'
            }
            
            context = stress_context_map.get(
                latest_assessment.primary_stressor,
                context
            )
        
        # Get affirmation for this context
        if context:
            affirmation = ContextAwareAffirmation.objects.filter(
                context_type=context,
                is_active=True
            ).order_by('-priority', '?').first()
            
            if affirmation:
                return {
                    'message': affirmation.contextual_message,
                    'explanation': affirmation.explanation,
                    'suggested_action': affirmation.suggested_action,
                    'context': affirmation.get_context_type_display()
                }
        
        # Default: random encouraging affirmation
        from .models import DailyAffirmation
        import random
        
        general = DailyAffirmation.objects.filter(
            is_active=True
        ).order_by('?').first()
        
        return {
            'message': general.message if general else "You're doing your best, and that's enough. 💙",
            'explanation': '',
            'suggested_action': '',
            'context': 'General encouragement'
        }

# ==================== ANONYMOUS COMMUNITY FEED ====================
 
class CommunityPost(models.Model):
    """
    Anonymous posts from students.
    NO usernames shown - just "Student" + random ID per post.
    """
    
    POST_CATEGORIES = [
        ('academic', '📚 Academic Stress'),
        ('social', '👥 Social Anxiety'),
        ('relationships', '💕 Relationships'),
        ('family', '🏠 Family'),
        ('identity', '🔍 Identity'),
        ('loneliness', '😔 Loneliness'),
        ('body_image', '💭 Body Image'),
        ('general', '💬 General Support'),
    ]
    
    # Author (anonymous to everyone else)
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='community_posts'
    )
    
    # Content
    category = models.CharField(max_length=20, choices=POST_CATEGORIES)
    content = models.TextField(
        max_length=500,
        help_text="Maximum 500 characters"
    )
    
    # Anonymous display
    anonymous_id = models.CharField(
        max_length=20,
        help_text="Random ID shown as 'Student #1234'"
    )
    
    # Engagement
    relate_count = models.IntegerField(default=0)
    reply_count = models.IntegerField(default=0)
    
    # Moderation
    is_flagged = models.BooleanField(default=False)
    flag_count = models.IntegerField(default=0)
    is_approved = models.BooleanField(default=False)
    is_ai_approved = models.BooleanField(
        default=False,
        help_text="AI moderation passed"
    )
    moderated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='moderated_posts'
    )
    moderation_notes = models.TextField(blank=True)
    
    # Metadata
    posted_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    
    # Campus context (optional)
    campus_wide = models.BooleanField(
        default=True,
        help_text="Visible to entire campus vs just your cohort"
    )
    
    class Meta:
        ordering = ['-last_activity']
        indexes = [
            models.Index(fields=['-last_activity', 'is_approved']),
            models.Index(fields=['category', '-posted_at']),
        ]
    
    def __str__(self):
        return f"Anonymous Post #{self.anonymous_id} - {self.category}"
    
    def save(self, *args, **kwargs):
        # Generate random anonymous ID if not set
        if not self.anonymous_id:
            import random
            self.anonymous_id = str(random.randint(1000, 9999))
        super().save(*args, **kwargs)
    
    @property
    def time_since_posted(self):
        """Human-readable time since posting."""
        delta = timezone.now() - self.posted_at
        
        if delta.seconds < 60:
            return "Just now"
        elif delta.seconds < 3600:
            minutes = delta.seconds // 60
            return f"{minutes} min ago"
        elif delta.seconds < 86400:
            hours = delta.seconds // 3600
            return f"{hours} hr ago"
        else:
            days = delta.days
            return f"{days} day{'s' if days != 1 else ''} ago"
    
    def can_user_relate(self, user):
        """Check if user already related to this post."""
        return not CommunityRelate.objects.filter(
            post=self,
            user=user
        ).exists()
    
    def can_user_reply(self, user):
        """Check if user can reply (not their own post)."""
        return user != self.author
 
 
class CommunityRelate(models.Model):
    """
    User clicked "I relate" on a post.
    Shows empathy without requiring comment.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    post = models.ForeignKey(CommunityPost, on_delete=models.CASCADE)
    related_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'post']
        ordering = ['-related_at']
    
    def __str__(self):
        return f"{self.user.username} relates to Post #{self.post.anonymous_id}"
 
 
class CommunityReply(models.Model):
    """
    Anonymous replies to community posts.
    Also uses random IDs.
    """
    post = models.ForeignKey(
        CommunityPost,
        on_delete=models.CASCADE,
        related_name='replies'
    )
    
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    
    content = models.TextField(max_length=300)
    
    anonymous_id = models.CharField(max_length=20)
    
    # Engagement
    helpful_count = models.IntegerField(default=0)
    
    # Moderation
    is_flagged = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=False)
    
    replied_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['replied_at']
    
    def __str__(self):
        return f"Reply #{self.anonymous_id} to Post #{self.post.anonymous_id}"
    
    def save(self, *args, **kwargs):
        if not self.anonymous_id:
            import random
            self.anonymous_id = str(random.randint(1000, 9999))
        super().save(*args, **kwargs)
 
 
class PostFlag(models.Model):
    """
    User reports inappropriate content.
    """
    FLAG_REASONS = [
        ('harmful', 'Harmful/Dangerous Content'),
        ('bullying', 'Bullying/Harassment'),
        ('identifying', 'Reveals Identifying Information'),
        ('spam', 'Spam/Off-topic'),
        ('other', 'Other'),
    ]
    
    post = models.ForeignKey(
        CommunityPost,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    
    reply = models.ForeignKey(
        CommunityReply,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    
    flagged_by = models.ForeignKey(User, on_delete=models.CASCADE)
    reason = models.CharField(max_length=20, choices=FLAG_REASONS)
    details = models.TextField(blank=True)
    
    flagged_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-flagged_at']
 
 
class CommunityPostingLimit(models.Model):
    """
    Enforce 1 post per day limit per user.
    Prevents spam.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    posts_today = models.IntegerField(default=0)
    last_post_date = models.DateField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'last_post_date']
    
    @classmethod
    def can_post_today(cls, user):
        """Check if user can post today."""
        today = timezone.now().date()
        limit, created = cls.objects.get_or_create(
            user=user,
            last_post_date=today,
            defaults={'posts_today': 0}
        )
        return limit.posts_today < 1  # Max 1 post per day
 
 
# ==================== JOURNALING SYSTEM ====================
 
class JournalPrompt(models.Model):
    """
    Daily journal prompts that rotate.
    """
    PROMPT_CATEGORIES = [
        ('gratitude', 'Gratitude'),
        ('reflection', 'Reflection'),
        ('goals', 'Goals & Aspirations'),
        ('challenges', 'Challenges'),
        ('self_care', 'Self-Care'),
        ('relationships', 'Relationships'),
        ('emotions', 'Emotions'),
    ]
    
    category = models.CharField(max_length=20, choices=PROMPT_CATEGORIES)
    prompt_text = models.TextField()
    
    # Alternative prompts for variety
    alternate_text_1 = models.TextField(blank=True)
    alternate_text_2 = models.TextField(blank=True)
    
    is_active = models.BooleanField(default=True)
    difficulty = models.CharField(
        max_length=10,
        choices=[
            ('easy', 'Easy - Quick Reflection'),
            ('moderate', 'Moderate - Some Thought'),
            ('deep', 'Deep - Soul-Searching'),
        ],
        default='moderate'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['category']
    
    def __str__(self):
        return f"{self.get_category_display()}: {self.prompt_text[:50]}..."
    
    @classmethod
    def get_daily_prompt(cls):
        """Get today's prompt (rotates daily)."""
        import random
        prompts = cls.objects.filter(is_active=True)
        if prompts.exists():
            # Use day of year to pick consistent prompt for the day
            day_of_year = timezone.now().timetuple().tm_yday
            index = day_of_year % prompts.count()
            return prompts[index]
        return None
 
 
class JournalEntry(models.Model):
    """
    User's journal entries.
    Completely private - only user can see.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='journal_entries'
    )
    
    # Entry type
    ENTRY_TYPES = [
        ('prompted', 'Prompted Entry'),
        ('free_write', 'Free Write'),
    ]
    
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPES)
    
    # Prompt used (if any)
    prompt = models.ForeignKey(
        JournalPrompt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    # Content
    title = models.CharField(max_length=200, blank=True)
    content = models.TextField()
    
    # Associated mood
    mood_tag = models.CharField(
        max_length=20,
        choices=[
            ('happy', '😊 Happy'),
            ('sad', '😔 Sad'),
            ('anxious', '😰 Anxious'),
            ('angry', '😠 Angry'),
            ('confused', '😕 Confused'),
            ('grateful', '🙏 Grateful'),
            ('hopeful', '✨ Hopeful'),
            ('overwhelmed', '🌊 Overwhelmed'),
        ],
        blank=True
    )
    
    # Metadata
    written_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Word count
    word_count = models.IntegerField(default=0)
    
    # Favorites
    is_favorite = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-written_at']
        verbose_name_plural = "Journal Entries"
    
    def __str__(self):
        return f"{self.user.username} - {self.written_at.date()}"
    
    def save(self, *args, **kwargs):
        # Calculate word count
        if self.content:
            self.word_count = len(self.content.split())
        super().save(*args, **kwargs)
    
    @property
    def preview(self):
        """First 100 characters for list view."""
        return self.content[:100] + "..." if len(self.content) > 100 else self.content
 
 
class JournalStreak(models.Model):
    """
    Track user's journaling streak.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='journal_streak'
    )
    
    current_streak = models.IntegerField(default=0)
    longest_streak = models.IntegerField(default=0)
    total_entries = models.IntegerField(default=0)
    last_entry_date = models.DateField(null=True, blank=True)
    
    def update_streak(self):
        """Update streak based on latest entry."""
        today = timezone.now().date()
        
        if not self.last_entry_date:
            self.current_streak = 1
            self.last_entry_date = today
        elif self.last_entry_date == today:
            # Already wrote today
            pass
        elif (today - self.last_entry_date).days == 1:
            # Consecutive day
            self.current_streak += 1
            self.last_entry_date = today
        else:
            # Streak broken
            self.current_streak = 1
            self.last_entry_date = today
        
        # Update longest
        if self.current_streak > self.longest_streak:
            self.longest_streak = self.current_streak
        
        self.total_entries += 1
        self.save()
 
 
# ==================== FRIEND ACCOUNTABILITY SYSTEM ====================
 
class WellnessBuddy(models.Model):
    """
    Friend connection for accountability.
    Both users must accept.
    """
    BUDDY_STATUS = [
        ('pending', 'Pending'),
        ('accepted', 'Connected'),
        ('declined', 'Declined'),
        ('blocked', 'Blocked'),
    ]
    
    # Initiator
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='buddy_requests_sent'
    )
    
    # Recipient
    buddy = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='buddy_requests_received'
    )
    
    status = models.CharField(max_length=20, choices=BUDDY_STATUS, default='pending')
    
    # Privacy settings (what buddy can see)
    share_streak = models.BooleanField(
        default=True,
        help_text="Buddy can see your check-in streak"
    )
    
    share_mood_trend = models.BooleanField(
        default=True,
        help_text="Buddy can see if mood is improving/declining"
    )
    
    share_last_checkin = models.BooleanField(
        default=True,
        help_text="Buddy can see when you last checked in"
    )
    
    # Notifications
    notify_on_checkin = models.BooleanField(
        default=False,
        help_text="Notify buddy when you check in"
    )
    
    notify_if_missed = models.BooleanField(
        default=True,
        help_text="Notify buddy if you haven't checked in for 3 days"
    )
    
    # Metadata
    requested_at = models.DateTimeField(auto_now_add=True)
    connected_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "Wellness buddy"
        verbose_name_plural = "Wellness buddies"
        unique_together = ['user', 'buddy']
        ordering = ['-requested_at']
    
    def __str__(self):
        return f"{self.user.username} → {self.buddy.username} ({self.status})"
    
    def accept(self):
        """Accept buddy request."""
        self.status = 'accepted'
        self.connected_at = timezone.now()
        self.save()
        
        # Create reverse connection
        WellnessBuddy.objects.get_or_create(
            user=self.buddy,
            buddy=self.user,
            defaults={
                'status': 'accepted',
                'connected_at': timezone.now()
            }
        )
    
    def get_buddy_status(self):
        """Get buddy's current wellness status (respecting privacy)."""
        from .models import UserStats, MoodEntry
        
        buddy_stats, _ = UserStats.objects.get_or_create(user=self.buddy)
        
        status = {}
        
        if self.share_streak:
            status['current_streak'] = buddy_stats.current_streak
        
        if self.share_last_checkin:
            last_mood = MoodEntry.objects.filter(
                user=self.buddy
            ).order_by('-timestamp').first()
            
            if last_mood:
                hours_ago = (timezone.now() - last_mood.timestamp).seconds // 3600
                status['last_checkin'] = f"{hours_ago} hours ago"
            else:
                status['last_checkin'] = "Not yet"
        
        if self.share_mood_trend:
            # Calculate trend from last 7 days
            recent_moods = MoodEntry.objects.filter(
                user=self.buddy,
                timestamp__gte=timezone.now() - timezone.timedelta(days=7)
            ).order_by('timestamp')
            
            if recent_moods.count() >= 2:
                first_half = list(recent_moods[:len(recent_moods)//2])
                second_half = list(recent_moods[len(recent_moods)//2:])
                
                avg_first = sum(m.sentiment_score for m in first_half) / len(first_half)
                avg_second = sum(m.sentiment_score for m in second_half) / len(second_half)
                
                if avg_second > avg_first + 0.5:
                    status['trend'] = 'improving'
                    status['trend_emoji'] = '📈'
                elif avg_second < avg_first - 0.5:
                    status['trend'] = 'struggling'
                    status['trend_emoji'] = '📉'
                else:
                    status['trend'] = 'stable'
                    status['trend_emoji'] = '➡️'
            else:
                status['trend'] = 'not_enough_data'
        
        return status
 
 
class BuddyEncouragement(models.Model):
    """
    Pre-written encouragement messages between buddies.
    """
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='encouragements_sent'
    )
    
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='encouragements_received'
    )
    
    message = models.TextField()
    
    sent_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-sent_at']
    
    def __str__(self):
        return f"{self.sender.username} → {self.recipient.username}"
 
 
# ==================== AI CONTENT MODERATION ====================
 
class AIContentModeration(models.Model):
    """
    AI moderation results for community posts.
    """
    post = models.OneToOneField(
        CommunityPost,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    
    reply = models.OneToOneField(
        CommunityReply,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    
    # AI analysis
    contains_crisis_language = models.BooleanField(default=False)
    contains_identifying_info = models.BooleanField(default=False)
    contains_bullying = models.BooleanField(default=False)
    toxicity_score = models.FloatField(
        default=0.0,
        help_text="0.0 = clean, 1.0 = very toxic"
    )
    
    # Decision
    ai_approved = models.BooleanField(default=True)
    flagged_for_review = models.BooleanField(default=False)
    
    moderated_at = models.DateTimeField(auto_now_add=True)
    
    @staticmethod
    def moderate_content(content):
        """
        Simple AI moderation (expand with actual ML model).
        """
        content_lower = content.lower()
        
        # Crisis keywords
        crisis_keywords = [
            'kill myself', 'end it all', 'suicide', 
            'want to die', 'harm myself'
        ]
        has_crisis = any(keyword in content_lower for keyword in crisis_keywords)
        
        # Identifying info patterns
        has_identifying = bool(
            re.search(r'\b\d{3}-\d{3}-\d{4}\b', content) or  # Phone
            re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', content) or  # Email
            re.search(r'\b\d{5}\b', content)  # ZIP code
        )
        
        # Bullying keywords
        bullying_keywords = ['loser', 'stupid', 'ugly', 'pathetic', 'worthless']
        has_bullying = any(keyword in content_lower for keyword in bullying_keywords)
        
        # Calculate toxicity (simplified)
        toxicity = 0.0
        if has_crisis:
            toxicity += 0.8
        if has_bullying:
            toxicity += 0.5
        
        # Decision
        approved = toxicity < 0.5 and not has_identifying
        flagged = has_crisis or toxicity >= 0.5
        
        return {
            'contains_crisis_language': has_crisis,
            'contains_identifying_info': has_identifying,
            'contains_bullying': has_bullying,
            'toxicity_score': min(toxicity, 1.0),
            'ai_approved': approved,
            'flagged_for_review': flagged
        }

# ==================== SMART NOTIFICATIONS ====================
 
class NotificationPersonality(models.Model):
    """
    User's notification personality preference.
    """
    PERSONALITY_TYPES = [
        ('encouraging', '✨ Encouraging & Warm'),
        ('minimal', '💬 Minimal & Direct'),
        ('funny', '😄 Funny & Playful'),
        ('motivational', '💪 Motivational & Strong'),
    ]
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='notification_personality'
    )
    
    personality_type = models.CharField(
        max_length=20,
        choices=PERSONALITY_TYPES,
        default='encouraging'
    )
    
    # Notification preferences (from earlier ReminderPreference model)
    # These work together
    
    def get_notification_text(self, notification_type, context=None):
        """
        Generate notification text based on personality.
        """
        templates = {
            'encouraging': {
                'daily_checkin': "Hey, 2 min to check in? {context} 💙",
                'streak_reminder': "You've been checking in for {days} days straight 🔥 One more for {badge}!",
                'buddy_checkin': "Your friend {name} just hit a {days}-day streak! Want to catch up? 😊",
                'campus_social_proof': "{count} students checked in today. Quick 30-second check? You got this ✨"
            },
            'minimal': {
                'daily_checkin': "Check-in reminder",
                'streak_reminder': "{days} day streak. Keep going 🔥",
                'buddy_checkin': "{name}: {days} days",
                'campus_social_proof': "{count} check-ins today"
            },
            'funny': {
                'daily_checkin': "Your mental health called. It wants attention 😅",
                'streak_reminder': "{days} days! You're basically a wellness wizard now 🧙",
                'buddy_checkin': "{name} is showing off their {days}-day streak. Jealous? 😏",
                'campus_social_proof': "{count} students adulting today. Your turn? 🎯"
            },
            'motivational': {
                'daily_checkin': "Champions check in. Let's go! 💪",
                'streak_reminder': "{days} DAYS STRONG 🔥 Don't break the chain!",
                'buddy_checkin': "{name} is crushing it: {days} days! Match their energy! 💪",
                'campus_social_proof': "JOIN {count} STUDENTS TAKING CHARGE TODAY! ⚡"
            }
        }
        
        personality_templates = templates.get(self.personality_type, templates['encouraging'])
        template = personality_templates.get(notification_type, '')
        
        # Fill in context
        if context:
            return template.format(**context)
        return template
        
    class Meta:
        verbose_name = "Notification Personality"
        verbose_name_plural = "Notification Personalities"
 
# ==================== CRISIS "CALL A FRIEND" ====================
 
class CrisisContactPriority(models.Model):
    """
    User's preferred crisis contacts with priority order.
    """
    CONTACT_TYPES = [
        ('friend', '👋 Friend'),
        ('family', '🏠 Family Member'),
        ('partner', '💕 Partner'),
        ('counselor', '🎓 Campus Counselor'),
        ('hotline', '📞 Crisis Hotline'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    contact_type = models.CharField(max_length=20, choices=CONTACT_TYPES)
    contact_name = models.CharField(max_length=100)
    
    # Contact method
    phone_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    
    # Pre-written message templates
    default_message = models.TextField(
        default="Hey, I'm having a rough time right now. Can we talk?",
        help_text="Pre-written message (user can edit before sending)"
    )
    
    # Priority (1 = first option)
    priority = models.IntegerField(default=1)
    
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['priority']
        unique_together = ['user', 'priority']
    
        verbose_name = "Crisis Contact Priority"
        verbose_name_plural = "Crisis Contact Priorities"
    
    def __str__(self):
        return f"{self.user.username} - {self.contact_name} (Priority {self.priority})"
 
 
# ==================== SPOTIFY INTEGRATION ====================
 
class MoodPlaylist(models.Model):
    """
    Curated mood-based playlists.
    """
    MOOD_TYPES = [
        ('anxious', '😰 Anxious'),
        ('sad', '😔 Sad'),
        ('angry', '😠 Angry'),
        ('stressed', '😫 Stressed'),
        ('happy', '😊 Happy'),
        ('energetic', '⚡ Energetic'),
        ('calm', '😌 Calm'),
        ('motivated', '💪 Motivated'),
    ]
    
    mood = models.CharField(max_length=20, choices=MOOD_TYPES)
    
    name = models.CharField(max_length=200)
    description = models.TextField()
    
    # Spotify playlist URL or ID
    spotify_url = models.URLField()
    spotify_playlist_id = models.CharField(max_length=100)
    
    # Apple Music (optional)
    apple_music_url = models.URLField(blank=True)
    
    # YouTube Music (optional)
    youtube_music_url = models.URLField(blank=True)
    
    # Metadata
    genre = models.CharField(
        max_length=50,
        blank=True,
        help_text="e.g., Lo-fi, Acoustic, Pop"
    )
    
    energy_level = models.CharField(
        max_length=20,
        choices=[
            ('low', 'Low Energy'),
            ('medium', 'Medium Energy'),
            ('high', 'High Energy'),
        ],
        default='medium'
    )
    
    play_count = models.IntegerField(default=0)
    
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    class Meta:
        ordering = ['mood', '-play_count']
    
    def __str__(self):
        return f"{self.get_mood_display()} - {self.name}"
 
 
class UserPlaylistHistory(models.Model):
    """
    Track which playlists user plays.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    playlist = models.ForeignKey(MoodPlaylist, on_delete=models.CASCADE)
    
    mood_when_played = models.CharField(max_length=20)
    
    played_at = models.DateTimeField(auto_now_add=True)
    
    # Did it help?
    helped = models.BooleanField(null=True, blank=True)
    
    class Meta:
        verbose_name = "User playlist history"
        verbose_name_plural = "User playlist histories"
        ordering = ['-played_at']
 
 
# ==================== CAMPUS CALENDAR INTEGRATION ====================
 
class CampusEvent(models.Model):
    """
    High-stress campus events (finals, midterms, etc.)
    """
    EVENT_TYPES = [
        ('finals', '📚 Finals Week'),
        ('midterms', '📝 Midterms'),
        ('registration', '🎓 Course Registration'),
        ('move_in', '🏠 Move-In Week'),
        ('graduation', '🎓 Graduation Week'),
        ('break_start', '✈️ Break Starts'),
        ('break_end', '🎒 Break Ends'),
        ('custom', '📅 Custom Event'),
    ]
    
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    start_date = models.DateField()
    end_date = models.DateField()
    
    # Stress level associated
    typical_stress_level = models.CharField(
        max_length=20,
        choices=[
            ('low', 'Low Stress'),
            ('moderate', 'Moderate Stress'),
            ('high', 'High Stress'),
            ('very_high', 'Very High Stress'),
        ],
        default='moderate'
    )
    
    # Campus-wide or user-specific
    is_campus_wide = models.BooleanField(default=True)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    
    # Support recommendations
    pre_event_support = models.TextField(
        blank=True,
        help_text="Support to offer BEFORE event (e.g., 'Create study plan')"
    )
    
    during_event_support = models.TextField(
        blank=True,
        help_text="Support DURING event (e.g., 'Extra check-ins')"
    )
    
    class Meta:
        ordering = ['start_date']
    
    def __str__(self):
        return f"{self.get_event_type_display()} - {self.start_date}"
    
    @property
    def days_until(self):
        """Days until event starts."""
        delta = self.start_date - timezone.now().date()
        return delta.days
    
    @property
    def is_happening_now(self):
        """Check if event is currently happening."""
        today = timezone.now().date()
        return self.start_date <= today <= self.end_date
    
    @property
    def is_upcoming(self):
        """Check if event is upcoming (within 7 days)."""
        return 0 < self.days_until <= 7
 
 
class EventSurvivalPlan(models.Model):
    """
    User's personalized plan for surviving high-stress events.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    event = models.ForeignKey(CampusEvent, on_delete=models.CASCADE)
    
    # Plan components
    study_breaks = models.TextField(
        blank=True,
        help_text="When/how to take breaks"
    )
    
    fun_activities = models.TextField(
        blank=True,
        help_text="One fun thing per day"
    )
    
    healthy_habits = models.TextField(
        blank=True,
        help_text="Sleep, meals, exercise goals"
    )
    
    support_people = models.TextField(
        blank=True,
        help_text="Who to reach out to"
    )
    
    breathing_reminders = models.BooleanField(
        default=True,
        help_text="Set breathing exercise reminders"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'event']
 
 
# ==================== SEED DATA FUNCTIONS ====================
 
def seed_mood_playlists():
    """
    Seed curated mood playlists.
    """
    playlists = [
        # Anxious
        {
            'mood': 'anxious',
            'name': 'Calm Down - Lo-fi Beats',
            'description': 'Gentle lo-fi beats to slow your thoughts',
            'spotify_url': 'https://open.spotify.com/playlist/37i9dQZF1DWWQRwui0ExPn',
            'spotify_playlist_id': '37i9dQZF1DWWQRwui0ExPn',
            'genre': 'Lo-fi',
            'energy_level': 'low'
        },
        {
            'mood': 'anxious',
            'name': 'Deep Focus',
            'description': 'Instrumental music for concentration',
            'spotify_url': 'https://open.spotify.com/playlist/37i9dQZF1DX8NTLI2TtZa6',
            'spotify_playlist_id': '37i9dQZF1DX8NTLI2TtZa6',
            'genre': 'Instrumental',
            'energy_level': 'low'
        },
        
        # Sad
        {
            'mood': 'sad',
            'name': 'It\'s Okay to Not Be Okay',
            'description': 'Sad songs when you need to feel your feelings',
            'spotify_url': 'https://open.spotify.com/playlist/37i9dQZF1DX7qK8ma5wgG1',
            'spotify_playlist_id': '37i9dQZF1DX7qK8ma5wgG1',
            'genre': 'Pop/Indie',
            'energy_level': 'low'
        },
        {
            'mood': 'sad',
            'name': 'Uplifting Anthems',
            'description': 'When you\'re ready to feel better',
            'spotify_url': 'https://open.spotify.com/playlist/37i9dQZF1DX3rxVfibe1L0',
            'spotify_playlist_id': '37i9dQZF1DX3rxVfibe1L0',
            'genre': 'Pop',
            'energy_level': 'medium'
        },
        
        # Stressed
        {
            'mood': 'stressed',
            'name': 'Nature Sounds - Rain & Ocean',
            'description': 'Natural sounds for instant calm',
            'spotify_url': 'https://open.spotify.com/playlist/37i9dQZF1DWXe9gFZP0gtP',
            'spotify_playlist_id': '37i9dQZF1DWXe9gFZP0gtP',
            'genre': 'Nature/Ambient',
            'energy_level': 'low'
        },
        
        # Motivated
        {
            'mood': 'motivated',
            'name': 'Beast Mode',
            'description': 'High-energy motivation',
            'spotify_url': 'https://open.spotify.com/playlist/37i9dQZF1DX76Wlfdnj7AP',
            'spotify_playlist_id': '37i9dQZF1DX76Wlfdnj7AP',
            'genre': 'Hip-Hop',
            'energy_level': 'high'
        },
    ]
    
    for playlist_data in playlists:
        MoodPlaylist.objects.get_or_create(
            spotify_playlist_id=playlist_data['spotify_playlist_id'],
            defaults=playlist_data
        )
    
    print(f"✅ Seeded {len(playlists)} mood playlists")
 
 
def seed_journal_prompts():
    """
    Seed journal prompts for daily rotation.
    """
    prompts = [
        # Gratitude
        {
            'category': 'gratitude',
            'prompt_text': 'What\'s one thing that made you smile today, even if it was small?',
            'difficulty': 'easy'
        },
        {
            'category': 'gratitude',
            'prompt_text': 'Who\'s someone you\'re grateful for right now, and why?',
            'difficulty': 'moderate'
        },
        
        # Reflection
        {
            'category': 'reflection',
            'prompt_text': 'What did you learn about yourself this week?',
            'difficulty': 'moderate'
        },
        {
            'category': 'reflection',
            'prompt_text': 'If you could give advice to yourself from one year ago, what would you say?',
            'difficulty': 'deep'
        },
        
        # Challenges
        {
            'category': 'challenges',
            'prompt_text': 'What\'s one thing that felt hard today? How did you handle it?',
            'difficulty': 'moderate'
        },
        {
            'category': 'challenges',
            'prompt_text': 'What\'s a challenge you\'re facing right now? What\'s one small step you could take?',
            'difficulty': 'moderate'
        },
        
        # Self-care
        {
            'category': 'self_care',
            'prompt_text': 'What does your body need right now? Rest, movement, nourishment, or something else?',
            'difficulty': 'easy'
        },
        {
            'category': 'self_care',
            'prompt_text': 'What\'s one way you took care of yourself today?',
            'difficulty': 'easy'
        },
        
        # Emotions
        {
            'category': 'emotions',
            'prompt_text': 'What emotion are you feeling most strongly right now? Where do you feel it in your body?',
            'difficulty': 'moderate'
        },
        {
            'category': 'emotions',
            'prompt_text': 'What would you tell a friend who was feeling exactly how you feel right now?',
            'difficulty': 'deep'
        },
    ]
    
    for prompt_data in prompts:
        JournalPrompt.objects.get_or_create(
            prompt_text=prompt_data['prompt_text'],
            defaults=prompt_data
        )
    
    print(f"✅ Seeded {len(prompts)} journal prompts")
 
 
def seed_campus_events(academic_year='2025-2026'):
    """
    Seed typical campus calendar events.
    """
    from datetime import date
    
    events = [
        {
            'event_type': 'finals',
            'title': 'Fall Finals Week',
            'start_date': date(2025, 12, 8),
            'end_date': date(2025, 12, 15),
            'typical_stress_level': 'very_high',
            'is_campus_wide': True,
            'pre_event_support': 'Create a study schedule. Stock up on healthy snacks. Plan breaks.',
            'during_event_support': 'Extra daily check-ins. Breathing exercise reminders. Campus counseling walk-ins available.'
        },
        {
            'event_type': 'midterms',
            'title': 'Fall Midterms',
            'start_date': date(2025, 10, 13),
            'end_date': date(2025, 10, 20),
            'typical_stress_level': 'high',
            'is_campus_wide': True,
            'pre_event_support': 'Review your notes. Form study groups. Get enough sleep.',
            'during_event_support': 'Daily mood boosters. Connect with study buddies.'
        },
    ]
    
    for event_data in events:
        CampusEvent.objects.get_or_create(
            event_type=event_data['event_type'],
            start_date=event_data['start_date'],
            defaults=event_data
        )
    
    print(f"✅ Seeded {len(events)} campus events")


