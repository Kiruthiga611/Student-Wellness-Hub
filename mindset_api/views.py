from rest_framework import viewsets, generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models import Avg, Count, Sum,Q
from datetime import timedelta, datetime
from django.db import models
import random
from rest_framework.parsers import JSONParser
# Models - organized by category
from .models import (
    # Community
    AIContentModeration, BuddyEncouragement, CommunityPost, CommunityPostingLimit, 
    CommunityRelate, CommunityReply, CommunitySnapshot, PostFlag,
    
    # Journaling
    JournalEntry, JournalPrompt, JournalStreak,
    
    # Health Tracking
    MoodEntry, SleepLog, StudySession, MicroCommitment,
    
    # Academic
    AcademicEvent, CampusEvent,
    
    # Wellness
    WellnessBuddy, WellnessResource, UserStats,
    
    # Patterns & Insights
    DetectedPattern, PersonalInsight,
    
    # Crisis Support
    CrisisCheckpoint, CrisisResource, CrisisEvent, TrustedContact, SOSButton,
    CrisisDetector, NotificationService, NotificationPersonality, CrisisContactPriority,
    
    # Support Systems
    CarePackage, TieredSupportGenerator, ProgressCalculator, ProgressMilestone,
    
    # Privacy
    UserPrivacySettings, PrivacyEducation, DataAccessLog,
    
    # Assessments
    QuizSession, CategorySelectionQuiz, AdaptiveQuestionSelector,
    StressCategory, StressAssessmentQuestion, StressAssessmentResponse,
    
    # Education & Boosters
    DASEducation, MoodBooster, MoodBoosterUsage, MoodPlaylist,
    DailyAffirmation, SavedAffirmation, TeenMoodContext,
)

from .serializers import (
    UserRegistrationSerializer,
    MoodEntrySerializer,
    SleepLogSerializer,
    StudySessionSerializer,
    MicroCommitmentSerializer,
    StressCategorySerializer,
    StressAssessmentQuestionSerializer,
    StressAssessmentResponseSerializer,
    DASEducationSerializer,
    MoodBoosterSerializer,
    DailyAffirmationSerializer,
    DetectedPatternSerializer,
    PersonalInsightSerializer,
)


def _parse_mood_scale_1_10(value, default=None):
    """Parse a 1–10 mood value from JSON/query; tolerate strings and missing data."""
    if value is None or value == '':
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        try:
            n = int(float(str(value).strip()))
        except (TypeError, ValueError):
            return default
    if 1 <= n <= 10:
        return n
    return default


def _normalize_sleep_request_data(data):
    """Map .http / frontend aliases (bedtime, waketime, hours, interruptions) to model/serializer fields."""
    if not isinstance(data, dict):
        return {}
    skip_keys = {'dream_recalled', 'bedtime', 'waketime', 'hours', 'quality'}
    out = {k: v for k, v in data.items() if k not in skip_keys}
    if out.get('sleep_from') is None and data.get('bedtime') is not None:
        out['sleep_from'] = data.get('bedtime')
    if out.get('sleep_to') is None:
        # Fix FE-13: accept both waketime (legacy) and wake_time (frontend sends this)
        val = data.get('waketime') or data.get('wake_time')
        if val is not None:
            out['sleep_to'] = val
    if 'interruption_count' not in out and 'interruptions' in data:
        try:
            out['interruption_count'] = int(data['interruptions'])
        except (TypeError, ValueError):
            out['interruption_count'] = 0
    return out


def _normalize_stress_submit_responses(raw):
    """
    Accept either legacy dict { "1": 4, ... } or list from .http:
    [ {"question_id": 1, "score": 4}, ... ]
    """
    if isinstance(raw, list):
        out = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            qid = item.get('question_id')
            if qid is None:
                continue
            out[str(qid)] = item.get('score')
        return out
    if isinstance(raw, dict):
        return raw
    return {}


COMMUNITY_CATEGORY_ALIASES = {
    'academic_stress': 'academic',
    'social_anxiety': 'social',
    'romantic': 'relationships',
}


# ==================== AUTHENTICATION VIEWS ====================

class RegisterView(generics.CreateAPIView):
    """
    User Registration for Student Wellness Hub.
    POST /api/register/
    Returns JWT tokens immediately so frontend can log in without a second call. (Fix FE-04)
    """
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response({
            'user': {
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
            },
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """
    JWT Token Authentication.
    POST /api/token/
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        
        user = authenticate(username=username, password=password)
        
        if user:
            refresh = RefreshToken.for_user(user)
            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'username': user.username,
                'first_name': user.first_name,   # Fix FE-05 / COMPAT-10
                'last_name': user.last_name,
                'email': user.email,
            })
        
        return Response(
            {'error': 'Invalid credentials'}, 
            status=status.HTTP_401_UNAUTHORIZED
        )



# ==================== USER PROFILE VIEW (Fix #3) ====================

class UserProfileView(APIView):
    """
    GET  /api/auth/profile/   — get logged-in user profile
    PATCH /api/auth/profile/  — update first_name, last_name, email
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        return Response({
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'date_joined': u.date_joined,
        })

    def patch(self, request):
        u = request.user
        u.email      = request.data.get('email',      u.email)
        u.first_name = request.data.get('first_name', u.first_name)
        u.last_name  = request.data.get('last_name',  u.last_name)
        u.save()
        return Response({
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'first_name': u.first_name,
            'last_name': u.last_name,
        })

# ==================== MOOD ENTRY VIEWSET ====================

class MoodEntryViewSet(viewsets.ModelViewSet):
    """
    Mental Health Mood Entry Management.
    
    Endpoints:
    - GET /api/mood-entries/ - List all mood entries
    - POST /api/mood-entries/ - Create new mood entry
    - GET /api/mood-entries/{id}/ - Retrieve specific entry
    - PUT/PATCH /api/mood-entries/{id}/ - Update entry
    - DELETE /api/mood-entries/{id}/ - Delete entry
    
    Note: sentiment_score and DAS levels are auto-calculated by TextBlob AI.
    Frontend should only send: note
    """
    serializer_class = MoodEntrySerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Return only the authenticated user's mood entries."""
        return MoodEntry.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        """Auto-assign the authenticated user when creating."""
        serializer.save(user=self.request.user)


# ==================== SLEEP LOG VIEWSET ====================

class SleepLogViewSet(viewsets.ModelViewSet):
    """
    Sleep Tracking Management.
    
    Endpoints:
    - GET /api/sleep-logs/ - List all sleep logs
    - POST /api/sleep-logs/ - Create new sleep log
    - GET /api/sleep-logs/{id}/ - Retrieve specific log
    - PUT/PATCH /api/sleep-logs/{id}/ - Update log
    - DELETE /api/sleep-logs/{id}/ - Delete log
    
    POST Body Example:
    {
        "date": "2026-02-15",
        "hours_slept": 7.5
    }
    """
    serializer_class = SleepLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Return only the authenticated user's sleep logs."""
        return SleepLog.objects.filter(user=self.request.user)
    
    def create(self, request, *args, **kwargs):
        # 1. Normalize data
        data = _normalize_sleep_request_data(dict(request.data))
        
        # 2. Add the user ID to the data dictionary so the validator sees it
        data['user'] = request.user.id
        
        # 3. Standard DRF flow
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save() # User is already in data
        
        # 4. Handle manual 'hours' override if needed
        raw = request.data
        if raw.get('hours') is not None and not (instance.sleep_from and instance.sleep_to):
            try:
                instance.hours_slept = float(raw['hours'])
                instance.save()
            except (TypeError, ValueError):
                pass
                
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        data = _normalize_sleep_request_data(dict(request.data))
        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    def perform_create(self, serializer):
        """Auto-assign the authenticated user when creating."""
        serializer.save(user=self.request.user)


# ==================== STUDY SESSION VIEWSET ====================

class StudySessionViewSet(viewsets.ModelViewSet):
    """
    Study Session Tracking Management.
    
    Endpoints:
    - GET /api/study-sessions/ - List all study sessions
    - POST /api/study-sessions/ - Create new study session
    - GET /api/study-sessions/{id}/ - Retrieve specific session
    - PUT/PATCH /api/study-sessions/{id}/ - Update session
    - DELETE /api/study-sessions/{id}/ - Delete session
    
    POST Body Example:
    {
        "subject": "Mathematics",
        "start_time": "2026-02-15T14:00:00Z",
        "end_time": "2026-02-15T16:30:00Z"
    }
    
    Note: duration_minutes is auto-calculated from start_time and end_time.
    """
    serializer_class = StudySessionSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Return only the authenticated user's study sessions."""
        return StudySession.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        """Auto-assign the authenticated user when creating."""
        serializer.save(user=self.request.user)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """POST /api/study-sessions/{id}/start/ — mark session started now."""
        session = self.get_object()
        session.start_time = timezone.now()
        session.save()
        return Response({'status': 'started', 'start_time': session.start_time})

    @action(detail=True, methods=['post'])
    def end(self, request, pk=None):
        """POST /api/study-sessions/{id}/end/ — mark session ended, auto-calc duration."""
        session = self.get_object()
        session.end_time = timezone.now()
        session.save()
        return Response({'status': 'ended', 'end_time': session.end_time, 'duration_minutes': session.duration_minutes})


# ==================== HOLISTIC WELLNESS SUMMARY VIEW ====================

class WellnessSummaryView(APIView):
    """
    HOLISTIC WELLNESS DASHBOARD (Samsung Health-inspired).
    
    GET /api/wellness-summary/
    a comprehensive 7-day wellness overview including:
    - Mental health metrics (mood, DAS levels)
    Provides 
    - Sleep patterns
    - Study habits
    - Holistic health score
    - Academic context awareness
    - Personalized AI recommendations
    
    This is the main endpoint for the frontend dashboard.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    # Ideal targets for normalization
    IDEAL_SLEEP_HOURS = 8.0
    IDEAL_STUDY_MINUTES = 240.0  # 4 hours per day
    
    def _get_7_day_data(self, user):
        """Fetch all wellness data for the past 7 days."""
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        
        # Mood entries
        mood_entries = MoodEntry.objects.filter(
            user=user,
            timestamp__date__gte=week_ago,
            timestamp__date__lte=today
        )
        
        # Sleep logs
        sleep_logs = SleepLog.objects.filter(
            user=user,
            date__gte=week_ago,
            date__lte=today
        )
        
        # Study sessions
        study_sessions = StudySession.objects.filter(
            user=user,
            start_time__date__gte=week_ago,
            start_time__date__lte=today
        )
        
        return mood_entries, sleep_logs, study_sessions
    
    def _calculate_mood_metrics(self, mood_entries):
        """Calculate mood average and DAS status."""
        scored_entries = mood_entries.exclude(sentiment_score__isnull=True)
        
        if scored_entries.exists():
            mood_avg = scored_entries.aggregate(
                avg=Avg('sentiment_score')
            )['avg']
            
            # Determine overall DAS status (most common level)
            das_levels = {
                'depression': self._most_common_level(scored_entries, 'depression_level'),
                'anxiety': self._most_common_level(scored_entries, 'anxiety_level'),
                'stress': self._most_common_level(scored_entries, 'stress_level')
            }
            
            return mood_avg, das_levels
        
        return None, {'depression': None, 'anxiety': None, 'stress': None}
    
    def _most_common_level(self, queryset, field_name):
        """Find the most common DAS level in the queryset."""
        counts = queryset.exclude(
            **{f'{field_name}__isnull': True}
        ).values(field_name).annotate(
            count=Count(field_name)
        ).order_by('-count')
        
        if counts:
            return counts[0][field_name]
        return None
    
    def _calculate_sleep_metrics(self, sleep_logs):
        """Calculate average sleep hours."""
        if sleep_logs.exists():
            return sleep_logs.aggregate(avg=Avg('hours_slept'))['avg']
        return None
    
    def _get_sleep_quality_distribution(self, sleep_logs):
        """
        Calculate distribution of sleep quality tags.
        
        Returns percentage breakdown of Good/Poor/Not Bad nights
        over the 7-day period, plus absolute counts.
        """
        if not sleep_logs.exists():
            return None
        
        total = sleep_logs.count()
        good = sleep_logs.filter(quality_tag='Good').count()
        poor = sleep_logs.filter(quality_tag='Poor').count()
        not_bad = sleep_logs.filter(quality_tag='Not Bad').count()
        
        return {
            'good_percent': round((good / total) * 100, 1) if total > 0 else 0,
            'poor_percent': round((poor / total) * 100, 1) if total > 0 else 0,
            'not_bad_percent': round((not_bad / total) * 100, 1) if total > 0 else 0,
            'good_nights': good,
            'poor_nights': poor,
            'not_bad_nights': not_bad
        }
    
    def _get_avg_interruptions(self, sleep_logs):
        """
        Calculate average sleep interruptions per night.
        
        Returns the mean interruption count across all logged nights
        in the 7-day window.
        """
        if not sleep_logs.exists():
            return None
        
        avg = sleep_logs.aggregate(avg=Avg('interruption_count'))['avg']
        return round(avg, 1) if avg else 0
    
    def _calculate_study_metrics(self, study_sessions):
        """Calculate average daily study minutes."""
        if study_sessions.exists():
            total_minutes = study_sessions.aggregate(
                total=Sum('duration_minutes')
            )['total']
            # Average per day over 7 days
            return total_minutes / 7.0
        return None
    
    def _get_active_academic_event(self):
        """Check for active academic events."""
        today = timezone.now().date()
        active_event = AcademicEvent.objects.filter(
            start_date__lte=today,
            end_date__gte=today
        ).first()
        
        return active_event.event_name if active_event else None
    
    def _calculate_holistic_health_score(self, mood_avg, sleep_avg, study_avg):
        """
        Calculate Holistic Health Score (0-100 scale).
        
        Formula: Weighted average of normalized metrics
        - Mood: 50% weight
        - Sleep: 30% weight
        - Study: 20% weight
        """
        # Normalize mood (-1 to 1) → (0 to 1)
        mood_normalized = (mood_avg + 1) / 2 if mood_avg is not None else 0.5
        
        # Normalize sleep (0 to 8+) → (0 to 1)
        sleep_normalized = min(sleep_avg / self.IDEAL_SLEEP_HOURS, 1.0) if sleep_avg else 0.5
        
        # Normalize study (0 to 240+) → (0 to 1)
        study_normalized = min(study_avg / self.IDEAL_STUDY_MINUTES, 1.0) if study_avg else 0.5
        
        # Weighted average
        health_score = (
            mood_normalized * 0.5 +
            sleep_normalized * 0.3 +
            study_normalized * 0.2
        ) * 100  # Scale to 0-100
        
        return round(health_score, 2)
    
    def _generate_personalized_recommendation(self, mood_avg, sleep_avg, study_avg, 
                                              das_levels, active_event):
        """
        AI Decision Engine for Personalized Recommendations.
        
        Analyzes all wellness metrics to provide context-aware advice.
        """
        recommendations = []
        
        # High-priority recommendations first
        
        # Rule 1: High Anxiety + Active Academic Event
        if das_levels['anxiety'] == 'High' and active_event:
            recommendations.append(
                f"🧘 High anxiety detected during {active_event}. "
                "Try breathing exercises and the Pomodoro technique "
                "(25 min study, 5 min break) to manage stress."
            )
        
        # Rule 2: Poor Sleep + Low Mood
        if sleep_avg and sleep_avg < 6.0 and mood_avg and mood_avg < -0.2:
            recommendations.append(
                "😴 Your sleep and mood are both low. "
                "Prioritize sleep: Try a power nap (20 mins) and "
                "reduce screen time 1 hour before bed."
            )
        
        # Rule 3: Excessive Study + High Stress
        if study_avg and study_avg > 240 and das_levels['stress'] == 'High':
            recommendations.append(
                "📚 You're studying a lot and showing high stress. "
                "Take regular 10-minute breaks every hour. "
                "Practice mindfulness or go for a short walk."
            )
        
        # Rule 4: Low Study + Active Event
        if study_avg and study_avg < 60 and active_event:
            recommendations.append(
                f"📖 Study time is low during {active_event}. "
                "Consider creating a study schedule with specific goals."
            )
        
        # Rule 5: Poor Sleep (General)
        if sleep_avg and sleep_avg < 6.5 and not any('sleep' in r.lower() for r in recommendations):
            recommendations.append(
                "😴 Your sleep is below optimal (6.5+ hours recommended). "
                "Establish a consistent bedtime routine."
            )
        
        # Default: Positive reinforcement
        if not recommendations:
            if mood_avg and mood_avg > 0.2:
                recommendations.append(
                    "🌟 Keep up the great work! Your wellness metrics look positive. "
                    "Consider exploring new hobbies or connecting with friends."
                )
            else:
                recommendations.append(
                    "👍 Your wellness metrics are stable. "
                    "Continue monitoring your well-being and reach out for support if needed."
                )
        
        return " | ".join(recommendations)
    
    def _get_primary_intervention(self, das_levels):
        """
        Primary Intervention Selector.

        Maps the most urgent DAS level to a single action token the
        Samsung Health-style dashboard uses to highlight the correct tile.

        Priority order (highest → lowest):
          anxiety  High  → BREATHING_EXERCISE
          stress   High  → MINDFULNESS_BREAK
          depression High → MOOD_JOURNAL
          any      Moderate → WELLNESS_CHECK_IN
          all      Low/None → None  (no urgent intervention needed)

        Returns a string token or None.
        """
        anxiety    = das_levels.get('anxiety')
        stress     = das_levels.get('stress')
        depression = das_levels.get('depression')

        if anxiety == 'High':
            return 'BREATHING_EXERCISE'
        if stress == 'High':
            return 'MINDFULNESS_BREAK'
        if depression == 'High':
            return 'MOOD_JOURNAL'
        if 'Moderate' in (anxiety, stress, depression):
            return 'WELLNESS_CHECK_IN'
        return None

    def _get_recommended_resources(self, das_levels, sleep_avg):
        """
        Smart Resource Filtering — Samsung Health-style carousel.

        Queries the WellnessResource table and returns up to MAX_CARDS
        card dicts, ordered by relevance to the student's current state.

        Priority rules (highest → lowest):
          1. stress_level == 'High'  → surface cards tagged 'breathing'
                                       then cards tagged 'meditation'
          2. sleep_avg < 6 hours     → surface cards tagged 'sleep'
          3. Fallback                → two Recovery cards, then two Mood,
                                       then two Focus (default catalogue)

        Each card dict shape:
          { title, category, color, action, image_url, content_link }
        ready for direct mapping to a frontend Card component.
        """
        MAX_CARDS  = 6
        LOW_SLEEP  = 6.0          # hours threshold for sleep-hygiene rule
        active_qs  = WellnessResource.objects.filter(is_active=True)

        seen_ids  = []
        resources = []

        def _collect(qs):
            """Append unseen cards from qs until MAX_CARDS is reached."""
            for resource in qs:
                if len(resources) >= MAX_CARDS:
                    return
                if resource.pk not in seen_ids:
                    seen_ids.append(resource.pk)
                    resources.append(resource.as_card())

        # ── Rule 1: High stress → breathing first, then meditation ─────
        if das_levels.get('stress') == 'High':
            _collect(active_qs.filter(tags__icontains='breathing'))
            _collect(active_qs.filter(tags__icontains='meditation'))

        # ── Rule 2: Low sleep → sleep-hygiene resources ─────────────────
        if sleep_avg is not None and sleep_avg < LOW_SLEEP:
            _collect(active_qs.filter(tags__icontains='sleep'))

        # ── Rule 3: Fallback — fill remaining slots from the catalogue ──
        for category in ('Recovery', 'Mood', 'Focus'):
            _collect(active_qs.filter(category=category)[:2])

        return resources

    def _check_mindfulness_alert(self, user):
        """
        Intervention Logic (Proactive Mental Health Feature).

        Inspects the user's most recent MoodEntry and returns True when
        anxiety_level is 'High'.  The frontend uses this flag to make the
        Breathing tile glow/bounce so the student's attention is drawn to
        an immediate coping action.

        Returns:
            bool – True if latest entry shows High anxiety, False otherwise.
        """
        latest = (
            MoodEntry.objects
            .filter(user=user)
            .exclude(anxiety_level__isnull=True)
            .order_by('-timestamp')
            .first()
        )
        return latest is not None and latest.anxiety_level == 'High'

    def get(self, request):
        """
        Main GET handler for Holistic Wellness Summary.
        
        Returns comprehensive wellness dashboard data.
        """
        user = request.user
        
        # ═══════════════════════════════════════════════════════════════
        # STEP 1: Fetch 7-Day Data
        # ═══════════════════════════════════════════════════════════════
        mood_entries, sleep_logs, study_sessions = self._get_7_day_data(user)
        
        # ═══════════════════════════════════════════════════════════════
        # STEP 2: Calculate Metrics
        # ═══════════════════════════════════════════════════════════════
        mood_avg, das_levels = self._calculate_mood_metrics(mood_entries)
        sleep_avg = self._calculate_sleep_metrics(sleep_logs)
        study_avg = self._calculate_study_metrics(study_sessions)
        
        # ═══════════════════════════════════════════════════════════════
        # STEP 3: Get Academic Context
        # ═══════════════════════════════════════════════════════════════
        active_event = self._get_active_academic_event()
        
        # ═══════════════════════════════════════════════════════════════
        # STEP 4: Calculate Holistic Health Score
        # ═══════════════════════════════════════════════════════════════
        health_score = self._calculate_holistic_health_score(
            mood_avg, sleep_avg, study_avg
        )
        
        # ═══════════════════════════════════════════════════════════════
        # STEP 5: Generate Personalized Recommendation
        # ═══════════════════════════════════════════════════════════════
        recommendation = self._generate_personalized_recommendation(
            mood_avg, sleep_avg, study_avg, das_levels, active_event
        )
        
        # ═══════════════════════════════════════════════════════════════
        # STEP 6: Proactive Intervention – Mindfulness Alert
        # ═══════════════════════════════════════════════════════════════
        trigger_mindfulness_alert = self._check_mindfulness_alert(user)

        # ═══════════════════════════════════════════════════════════════
        # STEP 7: Smart Resource Recommendations (Carousel Cards)
        #         + Primary Intervention Token
        # ═══════════════════════════════════════════════════════════════
        recommended_resources  = self._get_recommended_resources(das_levels, sleep_avg)
        primary_intervention   = self._get_primary_intervention(das_levels)

        # ═══════════════════════════════════════════════════════════════
        # STEP 8: Build Comprehensive Response
        # ═══════════════════════════════════════════════════════════════
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        
        response_data = {
            # Period Information
            'period': {
                'from': week_ago.strftime('%Y-%m-%d'),
                'to': today.strftime('%Y-%m-%d'),
                'days': 7
            },
            
            # Mental Health Metrics
            'mood': {
                'avg_score': round(mood_avg, 4) if mood_avg else None,
                'entries_count': mood_entries.count(),
                'status': 'Positive' if mood_avg and mood_avg > 0.2 else 
                         'Low' if mood_avg and mood_avg < -0.2 else 'Stable'
            },
            
            # DAS Levels
            'mental_health': {
                'depression_level': das_levels['depression'],
                'anxiety_level': das_levels['anxiety'],
                'stress_level': das_levels['stress']
            },
            
            # Sleep Metrics (Enhanced with Quality Analysis)
            'sleep': {
                'avg_hours': round(sleep_avg, 2) if sleep_avg else None,
                'logs_count': sleep_logs.count(),
                'status': 'Good' if sleep_avg and sleep_avg >= 7 else
                         'Poor' if sleep_avg and sleep_avg < 6 else 'Fair',
                'quality_distribution': self._get_sleep_quality_distribution(sleep_logs),
                'avg_interruptions': self._get_avg_interruptions(sleep_logs)
            },
            
            # Study Metrics
            'study': {
                'avg_minutes_per_day': round(study_avg, 2) if study_avg else None,
                'sessions_count': study_sessions.count(),
                'status': (
                    'Balanced'
                    if study_avg is not None and 120 <= study_avg <= 300
                    else 'Low'
                    if study_avg is not None and study_avg < 120
                    else 'High'
                    if study_avg is not None
                    else 'Unknown'
                ),
            },
            
            # Holistic Health Score (NEW)
            'holistic_health_score': health_score,
            
            # Academic Context
            'academic_context': {
                'active_event_name': active_event,
                'is_active': active_event is not None
            },
            
            # AI-Generated Recommendation (text summary)
            'personalized_recommendation': recommendation,

            # Samsung Health-style Carousel Cards
            # List of card dicts ordered by relevance to the student's
            # current stress/sleep state.  Map each item directly to a
            # Card component: title, category, color, action, image_url,
            # content_link are all present on every object.
            'recommended_resources': recommended_resources,

            # Proactive Intervention Flag
            # True  → latest MoodEntry has anxiety_level == 'High'
            # False → anxiety is normal; no special UI treatment needed
            'trigger_mindfulness_alert': trigger_mindfulness_alert,

            # Primary Intervention Token (Samsung Health-style dashboard driver)
            # Possible values:
            #   'BREATHING_EXERCISE' → anxiety_level is High
            #   'MINDFULNESS_BREAK'  → stress_level  is High
            #   'MOOD_JOURNAL'       → depression_level is High
            #   'WELLNESS_CHECK_IN'  → any level is Moderate
            #   None                 → all levels Low; no urgent action
            'primary_intervention': primary_intervention
        }
        
        return Response(response_data)


# ==================== MINDFULNESS ACTIONS VIEW ====================

class MindfulnessActionsView(APIView):
    """
    Dynamic Mindfulness Activity Menu.
    GET /api/mindfulness-actions/

    Returns a prioritised list of mindfulness activities.  Two ordering
    rules are applied before the list is returned, ensuring the most
    relevant activity always appears first:

    Priority 1 – Exam tomorrow:
        An AcademicEvent whose start_date is tomorrow causes 'Stress Relief'
        to move to position 0.

    Priority 2 – High study load today:
        Study sessions totalling > 120 minutes today causes 'Focus Meditation'
        to move to position 0.

    Both rules can be true simultaneously; exam-tomorrow wins (higher priority).
    All other activities follow in their default order.
    """
    permission_classes = [permissions.IsAuthenticated]

    # ------------------------------------------------------------------ #
    # Default activity catalogue – edit descriptions / durations here.   #
    # 'id' is the stable key the frontend uses to identify each tile.    #
    # ------------------------------------------------------------------ #
    DEFAULT_ACTIVITIES = [
        {
            'id': 'breathing',
            'title': 'Breathing Exercise',
            'description': '4-7-8 breathing to calm the nervous system quickly.',
            'duration_minutes': 5,
            'category': 'anxiety_relief',
        },
        {
            'id': 'focus_meditation',
            'title': 'Focus Meditation',
            'description': 'Guided session to restore concentration after long study blocks.',
            'duration_minutes': 10,
            'category': 'focus',
        },
        {
            'id': 'stress_relief',
            'title': 'Stress Relief',
            'description': 'Progressive muscle relaxation to decompress before exams.',
            'duration_minutes': 15,
            'category': 'stress_relief',
        },
        {
            'id': 'body_scan',
            'title': 'Body Scan',
            'description': 'Head-to-toe awareness exercise to release tension.',
            'duration_minutes': 12,
            'category': 'relaxation',
        },
        {
            'id': 'gratitude_journal',
            'title': 'Gratitude Journaling',
            'description': 'Write three things you appreciate today to shift your mindset.',
            'duration_minutes': 7,
            'category': 'mood_boost',
        },
        {
            'id': 'walk_break',
            'title': 'Mindful Walk Break',
            'description': 'Step outside for a short, screen-free walk to reset your focus.',
            'duration_minutes': 10,
            'category': 'physical',
        },
    ]

    # Thresholds
    HIGH_STUDY_MINUTES_TODAY = 120   # > 2 h of study today = high load

    def _has_exam_tomorrow(self):
        """
        Return (True, event_name) if any AcademicEvent starts tomorrow,
        else (False, None).
        """
        tomorrow = timezone.now().date() + timedelta(days=1)
        event = AcademicEvent.objects.filter(start_date=tomorrow).first()
        if event:
            return True, event.event_name
        return False, None

    def _study_load_is_high_today(self, user):
        """
        Return True if the user has logged more than HIGH_STUDY_MINUTES_TODAY
        minutes of study sessions starting today.
        """
        today = timezone.now().date()
        result = (
            StudySession.objects
            .filter(user=user, start_time__date=today)
            .aggregate(total=Sum('duration_minutes'))
        )
        total = result['total'] or 0
        return total > self.HIGH_STUDY_MINUTES_TODAY

    def _build_ordered_list(self, exam_tomorrow, high_study_load):
        """
        Clone the catalogue and move the priority item to index 0.

        Rule precedence (highest first):
          1. Exam tomorrow   → 'stress_relief' to front
          2. High study load → 'focus_meditation' to front
          3. No special case → default order preserved
        """
        # Work on a fresh copy so the class-level list is never mutated
        activities = [dict(a) for a in self.DEFAULT_ACTIVITIES]

        # Determine which id (if any) should be promoted
        if exam_tomorrow:
            priority_id = 'stress_relief'
        elif high_study_load:
            priority_id = 'focus_meditation'
        else:
            return activities   # Nothing to reorder

        # Pull the priority item out and reinsert at position 0
        priority_item = next(
            (a for a in activities if a['id'] == priority_id), None
        )
        if priority_item:
            activities.remove(priority_item)
            activities.insert(0, priority_item)

        return activities

    def get(self, request):
        user = request.user
        today = timezone.now().date()

        # ── 1. Evaluate ordering signals ────────────────────────────────
        exam_tomorrow, exam_name = self._has_exam_tomorrow()
        high_study_load = self._study_load_is_high_today(user)

        # ── 2. Build the ordered activity list ──────────────────────────
        activities = self._build_ordered_list(exam_tomorrow, high_study_load)

        # ── 3. Build context block so the frontend can explain ordering ──
        ordering_context = {
            'exam_tomorrow': exam_tomorrow,
            'exam_name': exam_name,             # None when no exam
            'high_study_load_today': high_study_load,
            'priority_reason': (
                f"'Stress Relief' promoted: {exam_name} starts tomorrow."
                if exam_tomorrow else
                "'Focus Meditation' promoted: high study load today."
                if high_study_load else
                "Default order – no special conditions detected."
            ),
        }

        return Response({
            'date': today.strftime('%Y-%m-%d'),
            'ordering_context': ordering_context,
            'activities': activities,
        })

# ==================== ENHANCED WELLNESS SUMMARY ====================

class SuperDuperWellnessSummaryView(APIView):
    """
    ENHANCED Wellness Summary with ALL Super Duper UX Features.
    
    Extends the base wellness-summary with:
    - Streak tracking
    - Pattern detection
    - Personal insights
    - Crisis detection
    - Community stats
    - Care packages
    - Behavioral predictions
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        user = request.user
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        
        # ═══════════════════════════════════════════════════════════════
        # BASE DATA (from original wellness-summary)
        # ═══════════════════════════════════════════════════════════════
        mood_entries = MoodEntry.objects.filter(
            user=user, timestamp__date__gte=week_ago
        )
        
        # Calculate base metrics
        mood_avg = mood_entries.aggregate(avg=Avg('sentiment_score'))['avg']
        das_levels = self._calculate_das_levels(mood_entries)
        
        # ═══════════════════════════════════════════════════════════════
        # GAMIFICATION: Streaks & Stats
        # ═══════════════════════════════════════════════════════════════
        stats, _ = UserStats.objects.get_or_create(user=user)
        
        streak_info = {
            'current_streak': stats.current_streak,
            'longest_streak': stats.longest_streak,
            'total_checkins': stats.total_checkins,
            'streak_milestone': self._get_streak_milestone(stats.current_streak),
            'days_until_next_milestone': self._days_to_next_milestone(stats.current_streak)
        }
        
        # ═══════════════════════════════════════════════════════════════
        # PATTERN DETECTION
        # ═══════════════════════════════════════════════════════════════
        detected_patterns = self._detect_patterns(user)
        active_patterns = DetectedPattern.objects.filter(
            user=user, is_active=True, acknowledged=False
        )[:3]  # Top 3 unacknowledged
        
        patterns_info = {
            'newly_detected': detected_patterns,
            'active_patterns': [
                {
                    'id': p.id,
                    'type': p.pattern_type,
                    'message': p.get_insight_message(),
                    'confidence': p.confidence
                }
                for p in active_patterns
            ]
        }
        
        # ═══════════════════════════════════════════════════════════════
        # PERSONAL INSIGHTS
        # ═══════════════════════════════════════════════════════════════
        insights = self._generate_weekly_insights(user)
        unread_insights = PersonalInsight.objects.filter(
            user=user, viewed=False
        ).order_by('priority')[:5]
        
        insights_info = {
            'unread_count': unread_insights.count(),
            'top_insights': [
                {
                    'id': i.id,
                    'title': i.title,
                    'message': i.message,
                    'type': i.insight_type,
                    'priority': i.priority
                }
                for i in unread_insights
            ]
        }
        
        # ═══════════════════════════════════════════════════════════════
        # CRISIS DETECTION
        # ═══════════════════════════════════════════════════════════════
        crisis_check = self._check_crisis_indicators(user)
        
        if crisis_check['show_resources']:
            # Log crisis checkpoint
            CrisisCheckpoint.objects.create(
                user=user,
                severity=crisis_check['severity'],
                indicators=crisis_check['indicators'],
                resources_shown=crisis_check['resources']
            )
        
        # ═══════════════════════════════════════════════════════════════
        # CARE PACKAGE (PRE-EXAM SUPPORT)
        # ═══════════════════════════════════════════════════════════════
        care_package = self._check_care_package(user)
        
        # ═══════════════════════════════════════════════════════════════
        # COMMUNITY STATS (SOCIAL PROOF)
        # ═══════════════════════════════════════════════════════════════
        community = self._get_community_stats(today)
        
        # ═══════════════════════════════════════════════════════════════
        # MICRO-COMMITMENTS (ACTIVE)
        # ═══════════════════════════════════════════════════════════════
        active_commitments = MicroCommitment.objects.filter(
            user=user,
            completed_at__isnull=True,
            committed_at__gte=timezone.now() - timedelta(hours=24)
        )
        
        commitments_info = {
            'active_count': active_commitments.count(),
            'pending': [
                {
                    'id': c.id,
                    'type': c.commitment_type,
                    'label': c.get_commitment_type_display(),
                    'committed_at': c.committed_at.isoformat()
                }
                for c in active_commitments
            ]
        }
        
        # ═════════════════════════════════════════════════════════════
        # BEHAVIORAL PREDICTIONS
        # ═══════════════════════════════════════════════════════════════
        predictions = self._get_predictions(user)
        
        # ═══════════════════════════════════════════════════════════════
        # BUILD ENHANCED RESPONSE
        # ═══════════════════════════════════════════════════════════════
        response_data = {
            # Original wellness summary data would go here
            # (mood, sleep, study, health_score, etc.)
            
            # NEW: Gamification
            'streaks': streak_info,
            
            # NEW: Pattern Detection
            'patterns': patterns_info,
            
            # NEW: Personal Insights
            'insights': insights_info,
            
            # NEW: Crisis Support
            'crisis_support': {
                'show_resources': crisis_check['show_resources'],
                'severity': crisis_check.get('severity'),
                'resources': crisis_check.get('resources', []),
                'message': crisis_check.get('message')
            },
            
            # NEW: Care Package
            'care_package': care_package,
            
            # NEW: Community Stats
            'community': community,
            
            # NEW: Micro-Commitments
            'commitments': commitments_info,
            
            # NEW: Predictions
            'predictions': predictions,
            
            # Enhanced metadata
            'meta': {
                'generated_at': timezone.now().isoformat(),
                'user_timezone': 'UTC',  # Get from user preferences
                'personalization_level': self._get_personalization_level(user)
            }
        }
        
        return Response(response_data)
    
    # ═══════════════════════════════════════════════════════════════
    # HELPER METHODS
    # ═══════════════════════════════════════════════════════════════
    
    def _calculate_das_levels(self, mood_entries):
        """Calculate average DAS levels from mood entries."""
        if not mood_entries.exists():
            return {'depression': 'Low', 'anxiety': 'Low', 'stress': 'Low'}
        
        # Most recent entry's DAS levels
        latest = mood_entries.first()
        return {
            'depression': latest.depression_level or 'Low',
            'anxiety': latest.anxiety_level or 'Low',
            'stress': latest.stress_level or 'Low'
        }
    
    def _get_streak_milestone(self, streak):
        """Return milestone message based on streak."""
        milestones = {
            3: "🔥 3-day streak! Building the habit.",
            7: "⭐ 1 week streak! You're consistent!",
            14: "💪 2 weeks! This is becoming routine.",
            30: "🎉 1 MONTH! You're crushing it!",
            60: "🏆 2 months! Wellness champion!",
            90: "👑 3 months! Incredible dedication!",
        }
        
        for days, message in sorted(milestones.items(), reverse=True):
            if streak >= days:
                return message
        
        return "Keep logging to build your streak!"
    
    def _days_to_next_milestone(self, streak):
        """Days until next milestone."""
        milestones = [3, 7, 14, 30, 60, 90, 180, 365]
        for milestone in milestones:
            if streak < milestone:
                return milestone - streak
        return None  # Already past all milestones
    
    def _detect_patterns(self, user):
        """
        ML Pattern Detection.
        
        Analyzes historical data to find recurring patterns.
        """
        detected = []
        
        # Pattern 1: Weekly anxiety spike
        weekly_pattern = self._detect_weekly_spike(user)
        if weekly_pattern:
            detected.append(weekly_pattern)
        
        # Pattern 2: Sleep-mood correlation
        sleep_correlation = self._detect_sleep_mood_correlation(user)
        if sleep_correlation:
            detected.append(sleep_correlation)
        
        # Pattern 3: Pre-exam stress
        exam_pattern = self._detect_pre_exam_pattern(user)
        if exam_pattern:
            detected.append(exam_pattern)
        
        # Save new patterns to database
        for pattern_data in detected:
            DetectedPattern.objects.get_or_create(
                user=user,
                pattern_type=pattern_data['type'],
                defaults={
                    'confidence': pattern_data['confidence'],
                    'metadata': pattern_data['metadata']
                }
            )
        
        return detected
    
    def _detect_weekly_spike(self, user):
        """Detect if anxiety spikes on specific day of week."""
        entries = MoodEntry.objects.filter(
            user=user,
            timestamp__gte=timezone.now() - timedelta(days=30)
        )
        
        # Group by day of week
        day_anxiety = {}
        for entry in entries:
            day = entry.timestamp.strftime('%A')
            if day not in day_anxiety:
                day_anxiety[day] = []
            
            # Convert anxiety_level to numeric
            anxiety_score = {'Low': 1, 'Moderate': 2, 'High': 3}.get(
                entry.anxiety_level, 1
            )
            day_anxiety[day].append(anxiety_score)
        
        # Find day with highest avg anxiety
        if day_anxiety:
            day_avgs = {day: sum(scores)/len(scores) 
                       for day, scores in day_anxiety.items()}
            worst_day = max(day_avgs, key=day_avgs.get)
            avg_anxiety = day_avgs[worst_day]
            
            # Trigger if worst day is significantly higher (>1.5 avg)
            if avg_anxiety >= 2.0 and len(day_anxiety[worst_day]) >= 3:
                return {
                    'type': 'weekly_spike',
                    'confidence': min(len(day_anxiety[worst_day]) / 4, 1.0),
                    'metadata': {
                        'day': worst_day,
                        'avg_anxiety': round(avg_anxiety, 2),
                        'occurrences': len(day_anxiety[worst_day])
                    }
                }
        
        return None
    
    def _detect_sleep_mood_correlation(self, user):
        """Detect correlation between sleep and next-day mood."""
        from .models import SleepLog
        
        sleep_logs = SleepLog.objects.filter(
            user=user,
            date__gte=timezone.now().date() - timedelta(days=30)
        )
        
        correlations = []
        for log in sleep_logs:
            next_day = log.date + timedelta(days=1)
            mood = MoodEntry.objects.filter(
                user=user,
                timestamp__date=next_day
            ).first()
            
            if mood and mood.sentiment_score is not None:
                correlations.append({
                    'sleep': log.hours_slept,
                    'mood': mood.sentiment_score
                })
        
        # Calculate correlation
        if len(correlations) >= 5:
            good_sleep = [c for c in correlations if c['sleep'] >= 7]
            poor_sleep = [c for c in correlations if c['sleep'] < 6]
            
            if good_sleep and poor_sleep:
                avg_mood_good = sum(c['mood'] for c in good_sleep) / len(good_sleep)
                avg_mood_poor = sum(c['mood'] for c in poor_sleep) / len(poor_sleep)
                
                improvement = avg_mood_good - avg_mood_poor
                
                if improvement > 0.2:  # Significant improvement
                    return {
                        'type': 'sleep_mood_correlation',
                        'confidence': min(len(correlations) / 10, 1.0),
                        'metadata': {
                            'sleep_hours': 7,
                            'mood_improvement': f"{improvement*100:.0f}%",
                            'sample_size': len(correlations)
                        }
                    }
        
        return None
    
    def _detect_pre_exam_pattern(self, user):
        """Detect stress pattern before exams."""
        # Get past exams
        past_exams = AcademicEvent.objects.filter(
            end_date__lt=timezone.now().date(),
            end_date__gte=timezone.now().date() - timedelta(days=60)
        )
        
        stress_before_exam = []
        for exam in past_exams:
            # Check mood 2 days before exam
            two_days_before = exam.start_date - timedelta(days=2)
            mood = MoodEntry.objects.filter(
                user=user,
                timestamp__date=two_days_before,
                stress_level='High'
            ).first()
            
            if mood:
                stress_before_exam.append(exam)
        
        # If stressed before 2+ exams, it's a pattern
        if len(stress_before_exam) >= 2:
            return {
                'type': 'pre_exam_stress',
                'confidence': min(len(stress_before_exam) / 3, 1.0),
                'metadata': {
                    'days_before': 2,
                    'occurrences': len(stress_before_exam)
                }
            }
        
        return None
    
    def _generate_weekly_insights(self, user):
        """Generate personal insights for the week."""
        today = timezone.now().date()
        week_start = today - timedelta(days=7)
        
        insights = []
        
        # Insight 1: Week-over-week comparison
        this_week_mood = MoodEntry.objects.filter(
            user=user,
            timestamp__date__gte=week_start
        ).aggregate(avg=Avg('sentiment_score'))['avg']
        
        last_week_mood = MoodEntry.objects.filter(
            user=user,
            timestamp__date__gte=week_start - timedelta(days=7),
            timestamp__date__lt=week_start
        ).aggregate(avg=Avg('sentiment_score'))['avg']
        
        if this_week_mood and last_week_mood:
            change = this_week_mood - last_week_mood
            if abs(change) > 0.1:
                direction = "improved" if change > 0 else "declined"
                insights.append({
                    'type': 'trend',
                    'title': f'Your mood {direction} this week',
                    'message': f'Compared to last week, your average mood {direction} by {abs(change)*100:.0f}%.',
                    'priority': 2,
                    'data_points': {
                        'this_week': round(this_week_mood, 2),
                        'last_week': round(last_week_mood, 2)
                    }
                })
        
        # Save insights to database
        for insight_data in insights:
            PersonalInsight.objects.create(
                user=user,
                insight_type=insight_data['type'],
                title=insight_data['title'],
                message=insight_data['message'],
                priority=insight_data['priority'],
                data_points=insight_data.get('data_points', {}),
                for_week_starting=week_start
            )
        
        return insights
    
    def _check_crisis_indicators(self, user):
        """Check for crisis indicators and return resources if needed."""
        today = timezone.now().date()
        
        indicators = []
        severity = 'low'
        
        # Indicator 1: Multiple high anxiety entries today
        high_anxiety_today = MoodEntry.objects.filter(
            user=user,
            timestamp__date=today,
            anxiety_level='High'
        ).count()
        
        if high_anxiety_today >= 3:
            indicators.append('3_high_anxiety_today')
            severity = 'high'
        
        # Indicator 2: Consecutive days of poor sleep
        from .models import SleepLog
        poor_sleep_days = SleepLog.objects.filter(
            user=user,
            date__gte=today - timedelta(days=3),
            hours_slept__lt=4
        ).count()
        
        if poor_sleep_days >= 3:
            indicators.append('sleep_<4h_3days')
            severity = 'medium' if severity == 'low' else 'high'
        
        # Indicator 3: Severe negative sentiment
        severe_negative = MoodEntry.objects.filter(
            user=user,
            timestamp__gte=timezone.now() - timedelta(days=2),
            sentiment_score__lt=-0.7
        ).count()
        
        if severe_negative >= 2:
            indicators.append('severe_negative_sentiment')
            severity = 'high'
        
        # Return crisis resources if any indicators found
        if indicators:
            return {
                'show_resources': True,
                'severity': severity,
                'indicators': indicators,
                'resources': [
                    {
                        'name': 'Campus Counseling',
                        'phone': '1-800-XXX-XXXX',
                        'hours': 'M-F 9am-5pm',
                        'type': 'phone'
                    },
                    {
                        'name': 'Crisis Text Line',
                        'contact': 'Text HOME to 741741',
                        'hours': '24/7',
                        'type': 'text'
                    },
                    {
                        'name': 'National Suicide Prevention Lifeline',
                        'phone': '988',
                        'hours': '24/7',
                        'type': 'phone'
                    }
                ],
                'message': "We've noticed you're going through a tough time. Please reach out to someone who can help."
            }
        
        return {'show_resources': False}
    
    def _check_care_package(self, user):
        """Check if user needs a pre-exam care package."""
        tomorrow = timezone.now().date() + timedelta(days=1)
        
        # Check for exams starting tomorrow
        upcoming_event = AcademicEvent.objects.filter(
            start_date=tomorrow
        ).first()
        
        if upcoming_event:
            # Check if care package already created
            existing = CarePackage.objects.filter(
                user=user,
                academic_event=upcoming_event
            ).exists()
            
            if not existing:
                # Create care package
                package = CarePackage.objects.create(
                    user=user,
                    academic_event=upcoming_event,
                    event_starts_at=upcoming_event.start_date,
                    resources_included=[1, 2, 3],  # IDs of helpful resources
                    tips=[
                        'Get 8 hours of sleep tonight',
                        'Eat a healthy breakfast',
                        'Arrive 15 minutes early',
                        'Take deep breaths if anxious'
                    ],
                    sleep_goal_adjusted=True,
                    new_sleep_goal=8.0
                )
                
                return {
                    'available': True,
                    'event_name': upcoming_event.event_name,
                    'starts': upcoming_event.start_date.isoformat(),
                    'tips': package.tips,
                    'resources_count': len(package.resources_included),
                    'message': f"📚 {upcoming_event.event_name} starts tomorrow. We've prepared a care package to help you succeed."
                }
        
        return {'available': False}
    
    def _get_community_stats(self, date):
        """Get community statistics for social proof."""
        snapshot = CommunitySnapshot.objects.filter(
            snapshot_date=date
        ).first()
        
        if snapshot:
            return {
                'active_users_today': snapshot.active_users_count,
                'avg_anxiety': snapshot.avg_anxiety_level,
                'breathing_sessions_today': snapshot.breathing_exercises_count,
                'message': f"Right now, {snapshot.active_users_count} students are using the app. You're not alone."
            }
        
        # Fallback if no snapshot
        active_now = MoodEntry.objects.filter(
            timestamp__gte=timezone.now() - timedelta(hours=1)
        ).values('user').distinct().count()
        
        return {
            'active_users_today': active_now,
            'message': f"{active_now} students checked in recently. You're part of a caring community."
        }
    
    def _get_predictions(self, user):
        """Predict upcoming challenges based on patterns."""
        predictions = []
        
        # Predict stress based on detected patterns
        patterns = DetectedPattern.objects.filter(
            user=user,
            is_active=True,
            pattern_type='weekly_spike'
        ).first()
        
        if patterns:
            spike_day = patterns.metadata.get('day')
            today_name = timezone.now().strftime('%A')
            
            # If spike day is tomorrow
            tomorrow_name = (timezone.now() + timedelta(days=1)).strftime('%A')
            if spike_day == tomorrow_name:
                predictions.append({
                    'type': 'anxiety_spike',
                    'when': 'tomorrow',
                    'confidence': patterns.confidence,
                    'message': f"Based on your pattern, anxiety may increase tomorrow ({spike_day}). Plan self-care ahead.",
                    'suggestions': ['breathing_exercise', 'light_schedule', 'support_system']
                })
        
        return predictions
    
    def _get_personalization_level(self, user):
        """Calculate how personalized the experience is (0-100)."""
        stats = UserStats.objects.filter(user=user).first()
        if not stats:
            return 0
        
        # Base on data collected
        data_points = stats.total_checkins
        patterns = DetectedPattern.objects.filter(user=user, is_active=True).count()
        insights = PersonalInsight.objects.filter(user=user).count()
        
        # Score out of 100
        score = min(100, (data_points * 2) + (patterns * 10) + (insights * 5))
        return score


# ==================== MICRO-COMMITMENT TRACKING ====================

class MicroCommitmentViewSet(viewsets.ModelViewSet):
    """
    API for managing micro-commitments.
    
    Endpoints:
    - POST /api/micro-commitments/ - Create commitment
    - PATCH /api/micro-commitments/{id}/complete/ - Mark complete
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MicroCommitmentSerializer
    
    def get_queryset(self):
        return MicroCommitment.objects.filter(user=self.request.user)
    
    def create(self, request):
        """Create a new micro-commitment."""
        # Check if this is a custom commitment or predefined type
        commitment_text = request.data.get('commitment_text')
        commitment_type = request.data.get('commitment_type')
        category = request.data.get('category')
        target_date = request.data.get('target_date')
        raw_mood = request.data.get('mood_entry_id') or request.data.get('mood_entry')
        mood_entry_id = None
        if raw_mood is not None and raw_mood != '':
            try:
                mid = int(raw_mood)
                if MoodEntry.objects.filter(id=mid, user=request.user).exists():
                    mood_entry_id = mid
            except (TypeError, ValueError):
                pass
        
        # Validate that we have either commitment_type or commitment_text
        if not commitment_type and not commitment_text:
            return Response(
                {'error': 'Either commitment_type or commitment_text is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # For custom commitments, default category if omitted (relaxed API)
        if commitment_text and not category:
            category = 'self_care'
        
        commitment = MicroCommitment.objects.create(
            user=request.user,
            mood_entry_id=mood_entry_id,
            commitment_type=commitment_type,
            commitment_text=commitment_text,
            category=category,
            target_date=target_date
        )
        
        if hasattr(request.user, 'stats'):
            request.user.stats.track_feature_use('micro_commitments')
        
        # Positive reinforcement message
        encouragement = [
            "Great choice! You can do this. 💪",
            "Perfect! Small steps lead to big changes. ✨",
            "You got this! Taking action is what matters. 🌟",
            "Awesome! You're taking care of yourself. 💙",
        ]

        return Response({
            'id': commitment.id,
            'type': commitment.commitment_type,
            'text': commitment.commitment_text,
            'category': commitment.category,
            'display_text': commitment.display_text,
            'committed_at': commitment.committed_at.isoformat(),
            'message': encouragement[0],
        }, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['patch','post'])
    def complete(self, request, pk=None):
        """Mark commitment as completed."""
        commitment = self.get_object()
        if commitment.is_completed:
            return Response({
                'message': 'Already completed!',
                'completed_at': commitment.completed_at.isoformat()
            })
        commitment.mark_complete()
        
        # Positive reinforcement message
        celebrations = [
            "🎉 You did it! Every small step matters.",
            "✨ Great job completing that! You're taking care of yourself.",
            "💪 Awesome! That took courage. Proud of you.",
            "🌟 You followed through! That's real progress.",
            "🎊 Well done! You're building healthy habits.",
            "💙 You completed it! Self-care is important.",
        ]
        return Response({
            'success': True,
            'completed': True,
            'completed_at': commitment.completed_at.isoformat(),
            'time_to_complete_minutes': commitment.time_to_complete,
            'message': random.choice(celebrations),
            'streak_bonus': self._check_commitment_streak(request.user)
        })
    
    @action(detail=False, methods=['get'])
    def pending(self, request):
        """
        Get all pending (not completed) commitments for current user.
        
        GET /api/micro-commitments/pending/
        """
        pending_commitments = self.get_queryset().filter(
            completed_at__isnull=True
        ).order_by('-committed_at')
        
        serializer = self.get_serializer(pending_commitments, many=True)
        
        return Response({
            'count': pending_commitments.count(),
            'pending_commitments': serializer.data
        })
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """
        Get commitment completion statistics.
        
        GET /api/micro-commitments/stats/
        """
        all_commitments = self.get_queryset()
        completed = all_commitments.filter(completed_at__isnull=False)
        pending = all_commitments.filter(completed_at__isnull=True)
        
        # Calculate completion rate
        total = all_commitments.count()
        completed_count = completed.count()
        completion_rate = (completed_count / total * 100) if total > 0 else 0
        
        # Get most common commitment type
        from django.db.models import Count
        popular_type = all_commitments.values('commitment_type').annotate(
            count=Count('id')
        ).order_by('-count').first()
        
        return Response({
            'total_commitments': total,
            'completed': completed_count,
            'pending': pending.count(),
            'completion_rate': round(completion_rate, 1),
            'most_common_type': popular_type['commitment_type'] if popular_type else None,
            'message': self._get_encouragement_message(completion_rate)
        })
    
    def _check_commitment_streak(self, user):
        """Check if user has completed commitments X days in a row."""
        # Simple implementation - can be enhanced
        recent_completed = MicroCommitment.objects.filter(
            user=user,
            completed_at__isnull=False,
            completed_at__gte=timezone.now() - timedelta(days=7)
        ).count()
        
        if recent_completed >= 7:
            return {
                'bonus': True,
                'message': "🔥 7-day commitment streak! You're unstoppable!"
            }
        elif recent_completed >= 3:
            return {
                'bonus': True,
                'message': "⭐ 3 commitments this week! Keep it up!"
            }
        return {'bonus': False}
    
    def _get_encouragement_message(self, completion_rate):
        """Get encouraging message based on completion rate."""
        if completion_rate >= 80:
            return "🌟 Outstanding! You complete most of your commitments!"
        elif completion_rate >= 60:
            return "💪 Great job! You're following through consistently."
        elif completion_rate >= 40:
            return "👍 Good start! Keep building that habit."
        else:
            return "🌱 Every completion counts. You're learning!"
 
        

# ==================== PATTERN ACKNOWLEDGMENT ====================

class PatternViewSet(viewsets.ReadOnlyModelViewSet):
    """
    View detected patterns.
    
    Endpoints:
    - GET /api/patterns/ - List active patterns
    - POST /api/patterns/{id}/acknowledge/ - Acknowledge pattern
    - POST /api/patterns/{id}/dismiss/ - Dismiss pattern
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DetectedPatternSerializer
    
    def get_queryset(self):
        return DetectedPattern.objects.filter(
            user=self.request.user,
            is_active=True
        )
    
    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        """User acknowledges they've seen the pattern."""
        pattern = self.get_object()
        pattern.acknowledged = True
        pattern.acknowledged_at = timezone.now()
        pattern.save()
        
        return Response({'acknowledged': True})
    
    @action(detail=True, methods=['post'])
    def dismiss(self, request, pk=None):
        """User dismisses pattern as not helpful."""
        pattern = self.get_object()
        pattern.is_active = False
        pattern.helpful = False
        pattern.save()
        
        return Response({'dismissed': True})
    
    @action(detail=True, methods=['post'])
    def mark_helpful(self, request, pk=None):
        """User marks pattern as helpful."""
        pattern = self.get_object()
        pattern.helpful = True
        pattern.save()
        
        return Response({'marked_helpful': True})


# ==================== INSIGHTS ====================

class InsightsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Personal insights endpoint.
    
    GET /api/insights/ - List unread insights
    POST /api/insights/{id}/mark_read/ - Mark as read
    POST /api/insights/{id}/rate/ - Rate helpfulness
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PersonalInsightSerializer
    
    def get_queryset(self):
        return PersonalInsight.objects.filter(user=self.request.user)
    
    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        insight = self.get_object()
        insight.viewed = True
        insight.viewed_at = timezone.now()
        insight.save()
        
        return Response({'viewed': True})
    
    @action(detail=True, methods=['post'])
    def rate(self, request, pk=None):
        """Rate insight helpfulness (1-5)."""
        insight = self.get_object()
        try:
            rating = int(request.data.get('rating', 3))
        except (TypeError, ValueError):
            rating = 3
        rating = max(1, min(5, rating))
        insight.helpful_rating = rating
        insight.save()
        return Response({'rated': True, 'rating': rating})


# ==================== BACKGROUND TASKS (Celery) ====================

# These would run as scheduled tasks in production

def generate_community_snapshot():
    """
    Daily task to generate community snapshot.
    Run at midnight via Celery beat.
    """
    from django.db.models import Avg
    
    today = timezone.now().date()
    
    # Aggregate stats
    active_users = MoodEntry.objects.filter(
        timestamp__date=today
    ).values('user').distinct().count()
    
    total_moods = MoodEntry.objects.filter(
        timestamp__date=today
    ).count()
    
    avg_anxiety = MoodEntry.objects.filter(
        timestamp__date=today
    ).aggregate(
        avg=Avg(
            models.Case(
                models.When(anxiety_level='Low', then=1),
                models.When(anxiety_level='Moderate', then=2),
                models.When(anxiety_level='High', then=3),
                default=1,
                output_field=models.FloatField()
            )
        )
    )['avg']
    
    # Active events today
    active_events = list(
        AcademicEvent.objects.filter(
            start_date__lte=today,
            end_date__gte=today
        ).values_list('event_name', flat=True)
    )
    
    # Create snapshot
    CommunitySnapshot.objects.create(
        snapshot_date=today,
        active_users_count=active_users,
        total_mood_entries=total_moods,
        avg_anxiety_level=avg_anxiety,
        active_events=active_events
    )
    
    print(f"✓ Community snapshot created for {today}")


def cleanup_old_deleted_entries():
    """
    Daily task to permanently delete old soft-deleted entries.
    Run daily via Celery beat.
    """
    from .models import DeletedMoodEntry
    
    cutoff = timezone.now()
    old_entries = DeletedMoodEntry.objects.filter(
        permanent_delete_at__lt=cutoff,
        restored=False
    )
    
    count = old_entries.count()
    old_entries.delete()
    
    print(f"✓ Permanently deleted {count} old entries")

# ==================== STRESS ASSESSMENT API ====================
 
class StressAssessmentViewSet(viewsets.ViewSet):
    """
    Teen stress assessment quiz system.

    Endpoints:
    - GET  /api/stress/              - List past assessments      (Fix COMPAT-06)
    - GET  /api/stress/categories/   - Get all stress categories
    - GET  /api/stress/questions/    - Get quiz questions
    - POST /api/stress/submit/       - Submit quiz responses
    - GET  /api/stress/history/      - User's past assessments
    - GET  /api/stress/insights/     - Personalized insights
    """
    permission_classes = [IsAuthenticated]

    def list(self, request):
        """GET /api/stress/ — list the user's past stress assessments. Fix COMPAT-06."""
        assessments = StressAssessmentResponse.objects.filter(
            user=request.user
        ).order_by('-session_date')[:20]
        serializer = StressAssessmentResponseSerializer(assessments, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def categories(self, request):
        """Get all stress categories with descriptions."""
        categories = StressCategory.objects.filter(is_active=True)
        serializer = StressCategorySerializer(categories, many=True)
        return Response({
            'categories': serializer.data,
            'message': 'These are different types of stress teens experience'
        })
    
    @action(detail=False, methods=['get'])
    def quiz(self, request):
        """
        Get stress assessment quiz questions.
        Returns all active questions grouped by category.
        """
        questions = StressAssessmentQuestion.objects.filter(
            is_active=True,
            category__is_active=True
        ).select_related('category').order_by('category', 'order')
        
        # Group by category
        quiz_data = {}
        for question in questions:
            cat_type = question.category.category_type
            if cat_type not in quiz_data:
                quiz_data[cat_type] = {
                    'category': {
                        'name': question.category.name,
                        'emoji': question.category.emoji,
                        'description': question.category.description
                    },
                    'questions': []
                }
            
            quiz_data[cat_type]['questions'].append({
                'id': question.id,
                'text': question.question_text,
                'weight': question.weight
            })
        
        return Response({
            'quiz': quiz_data,
            'response_scale': [
                {'value': 0, 'label': 'Never / Not at all'},
                {'value': 1, 'label': 'Rarely / A little'},
                {'value': 2, 'label': 'Sometimes / Moderately'},
                {'value': 3, 'label': 'Often / Quite a bit'},
                {'value': 4, 'label': 'All the time / Extremely'}
            ],
            'message': 'Answer honestly - this helps us understand how to support you'
        })
    
    @action(detail=False, methods=['post'])
    def submit(self, request):
        """
        Submit quiz responses and get personalized results.
        
        Expected body:
        {
            "responses": {
                "question_id": score,
                ...
            }
        }
        """
        responses = _normalize_stress_submit_responses(request.data.get('responses', {}))
        
        if not responses:
            return Response(
                {'error': 'No responses provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Calculate scores per category
        category_scores = {}
        category_questions = {}
        
        for question_id, score in responses.items():
            try:
                if score is None:
                    continue
                score = float(score)
            except (TypeError, ValueError):
                continue
            try:
                question = StressAssessmentQuestion.objects.select_related('category').get(
                    id=int(question_id)
                )
                cat_type = question.category.category_type
                
                if cat_type not in category_scores:
                    category_scores[cat_type] = 0
                    category_questions[cat_type] = []
                
                weighted_score = score * question.weight
                category_scores[cat_type] += weighted_score
                category_questions[cat_type].append({
                    'max': 4 * question.weight,
                    'actual': weighted_score
                })
            except StressAssessmentQuestion.DoesNotExist:
                continue
        
        # Convert to percentages
        category_percentages = {}
        for cat_type, questions_data in category_questions.items():
            total_max = sum(q['max'] for q in questions_data)
            total_actual = category_scores[cat_type]
            percentage = (total_actual / total_max * 100) if total_max > 0 else 0
            category_percentages[cat_type] = round(percentage, 1)
        
        # Calculate overall stress score
        overall_score = sum(category_percentages.values()) / len(category_percentages) if category_percentages else 0
        
        # Find primary and secondary stressors
        sorted_categories = sorted(
            category_percentages.items(),
            key=lambda x: x[1],
            reverse=True
        )
        primary_stressor = sorted_categories[0][0] if sorted_categories else ''
        secondary_stressor = sorted_categories[1][0] if len(sorted_categories) > 1 else ''
        
        # Save assessment
        assessment = StressAssessmentResponse.objects.create(
            user=request.user,
            responses=responses,
            category_scores=category_percentages,
            overall_stress_score=overall_score,
            primary_stressor=primary_stressor,
            secondary_stressor=secondary_stressor
        )
        
        # Generate personalized response
        response_data = self._generate_personalized_response(
            assessment,
            category_percentages,
            primary_stressor,
            secondary_stressor
        )
        
        return Response(response_data)
    
    def _generate_personalized_response(self, assessment, category_scores, primary, secondary):
        """Generate empathetic, personalized response to quiz results."""
        
        # Get category objects
        try:
            primary_cat = StressCategory.objects.get(category_type=primary)
            secondary_cat = StressCategory.objects.get(category_type=secondary) if secondary else None
        except StressCategory.DoesNotExist:
            primary_cat = None
            secondary_cat = None
        
        # Generate stress level message
        overall = assessment.overall_stress_score
        if overall < 20:
            stress_message = "You're handling things really well right now! 💚 That doesn't mean everything is perfect, but you're coping effectively."
        elif overall < 40:
            stress_message = "You're experiencing some stress, which is totally normal. 💙 You're managing, but let's make sure you have good support."
        elif overall < 60:
            stress_message = "You're dealing with a moderate amount of stress. 💛 This is when it's important to use coping strategies and reach out for support."
        elif overall < 80:
            stress_message = "You're under significant stress right now. 🧡 This must feel really hard. Please know you don't have to handle this alone."
        else:
            stress_message = "You're experiencing very high levels of stress. ❤️ I'm really glad you took this assessment. You deserve support - please talk to someone you trust."
        
        # Generate primary stressor message
        stressor_insights = []
        if primary_cat:
            stressor_insights.append({
                'category': primary_cat.name,
                'emoji': primary_cat.emoji,
                'score': category_scores.get(primary, 0),
                'why_it_happens': primary_cat.why_it_happens,
                'coping_strategies': primary_cat.coping_strategies[:3]  # Top 3
            })
        
        if secondary_cat and category_scores.get(secondary, 0) > 30:
            stressor_insights.append({
                'category': secondary_cat.name,
                'emoji': secondary_cat.emoji,
                'score': category_scores.get(secondary, 0),
                'why_it_happens': secondary_cat.why_it_happens,
                'coping_strategies': secondary_cat.coping_strategies[:3]
            })
        
        # Recommend mood boosters
        mood_boosters = self._recommend_mood_boosters(primary, overall)
        
        return {
            'assessment_id': assessment.id,
            'overall_stress_score': round(overall, 1),
            'stress_level': assessment.get_stress_level_label(),
            'message': stress_message,
            'category_scores': category_scores,
            'top_stressors': stressor_insights,
            'mood_boosters': mood_boosters,
            'next_steps': self._get_next_steps(overall),
            'reassurance': self._get_reassurance_message(overall)
        }
    
    def _recommend_mood_boosters(self, primary_stressor, stress_level):
        """Recommend appropriate mood boosters."""
        # Map stressors to mood targets
        stressor_to_mood = {
            'academic': 'stressed',
            'social': 'anxious',
            'romantic': 'sad',
            'family': 'overwhelmed',
            'identity': 'lonely',
            'bullying': 'anxious',
            'social_media': 'overwhelmed',
            'future': 'anxious',
            'body_image': 'sad',
            'loneliness': 'lonely'
        }
        
        mood_target = stressor_to_mood.get(primary_stressor, 'stressed')
        
        # Get boosters
        boosters = MoodBooster.objects.filter(
            mood_target=mood_target,
            is_active=True
        ).order_by('-average_rating')[:3]
        
        return [
            {
                'id': b.id,
                'title': b.title,
                'emoji': b.emoji,
                'type': b.get_booster_type_display(),
                'description': b.description
            }
            for b in boosters
        ]
    
    def _get_next_steps(self, stress_level):
        """Recommend next steps based on stress level."""
        if stress_level < 40:
            return [
                "Keep doing what you're doing - you're managing well",
                "Check in with yourself regularly",
                "Try a mood booster when needed"
            ]
        elif stress_level < 60:
            return [
                "Talk to someone you trust about what's going on",
                "Try the coping strategies we suggested",
                "Make time for activities that recharge you",
                "Consider talking to a school counselor"
            ]
        else:
            return [
                "Please talk to a trusted adult today (parent, counselor, teacher)",
                "Use our crisis resources if you need immediate support",
                "Try gentle mood boosters (even small things help)",
                "Remember: asking for help is brave and smart"
            ]
    
    def _get_reassurance_message(self, stress_level):
        """Provide reassurance based on stress level."""
        messages = [
            "What you're feeling is valid. Stress doesn't mean you're weak - it means you're human.",
            "You don't have to have it all figured out. It's okay to struggle and ask for help.",
            "Your worth isn't determined by your productivity or how well you're coping.",
            "Lots of teens feel this way. You're not alone, even though it might feel like it.",
            "Be gentle with yourself. You're doing the best you can with what you have right now."
        ]
        return random.choice(messages)
    
    @action(detail=False, methods=['get'])
    def history(self, request):
        """Get user's past stress assessments."""
        assessments = StressAssessmentResponse.objects.filter(
            user=request.user
        ).order_by('-session_date')[:10]
        
        serializer = StressAssessmentResponseSerializer(assessments, many=True)
        
        # Calculate trends
        if len(assessments) >= 2:
            latest = assessments[0].overall_stress_score
            previous = assessments[1].overall_stress_score
            change = latest - previous
            
            if change < -10:
                trend = "improving"
                trend_message = f"Your stress has decreased by {abs(change):.1f}% - great progress! 📉"
            elif change > 10:
                trend = "increasing"
                trend_message = f"Your stress has increased by {change:.1f}% - let's work on this together 📈"
            else:
                trend = "stable"
                trend_message = "Your stress levels are relatively stable 📊"
        else:
            trend = "unknown"
            trend_message = "Take more assessments to see trends over time"
        
        return Response({
            'assessments': serializer.data,
            'trend': trend,
            'trend_message': trend_message
        })
 
 
# ==================== DAS EDUCATION API ====================
 
@api_view(['GET'])
@permission_classes([AllowAny])
def get_das_education(request, das_type):
    """
    Get educational content about Depression, Anxiety, or Stress.
    
    GET /api/education/das/{depression|anxiety|stress}/
    """
    try:
        education = DASEducation.objects.get(das_type=das_type)
        serializer = DASEducationSerializer(education)
        
        return Response({
            'content': serializer.data,
            'message': f'Learning about {education.get_das_type_display().lower()} helps you understand yourself better'
        })
    except DASEducation.DoesNotExist:
        return Response(
            {'error': 'Education content not found'},
            status=status.HTTP_404_NOT_FOUND
        )
 
 
@api_view(['GET'])
@permission_classes([AllowAny])
def get_all_das_education(request):
    """
    Get all DAS education content.
    
    GET /api/education/das/
    """
    education = DASEducation.objects.all()
    serializer = DASEducationSerializer(education, many=True)
    
    return Response({
        'topics': serializer.data,
        'message': 'Understanding what you\'re experiencing is the first step to feeling better'
    })
 
 
# ==================== MOOD BOOSTERS API ====================
 
class MoodBoosterViewSet(viewsets.ModelViewSet):
    """
    Mood elevation activities for teens.
    
    Endpoints:
    - GET /api/mood-boosters/ - Get all boosters
    - GET /api/mood-boosters/?mood=anxious - Filter by mood
    - GET /api/mood-boosters/?type=instant - Filter by type
    - POST /api/mood-boosters/{id}/try/ - Mark as tried
    - POST /api/mood-boosters/{id}/rate/ - Rate effectiveness
    """
    permission_classes = [IsAuthenticated]
    queryset = MoodBooster.objects.filter(is_active=True)
    serializer_class = MoodBoosterSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by mood
        mood = self.request.query_params.get('mood')
        if mood:
            queryset = queryset.filter(mood_target=mood)
        
        # Filter by type
        booster_type = self.request.query_params.get('type')
        if booster_type:
            queryset = queryset.filter(booster_type=booster_type)
        
        return queryset.order_by('-average_rating', 'title')
    
    @action(detail=True, methods=['post'])
    def try_booster(self, request, pk=None):
        """
        Mark booster as tried with before/after mood.
        
        POST /api/mood-boosters/{id}/try/
        Body: {"mood_before": 3, "mood_after": 6}
        """
        booster = self.get_object()
        
        mood_before = _parse_mood_scale_1_10(request.data.get('mood_before'), default=5)
        mood_after = _parse_mood_scale_1_10(request.data.get('mood_after'), default=None)
        
        # Create usage record
        usage = MoodBoosterUsage.objects.create(
            user=request.user,
            booster=booster,
            mood_before=mood_before,
            mood_after=mood_after
        )
        
        # Update booster stats
        booster.times_tried += 1
        if mood_after is not None and mood_before is not None and mood_after > mood_before:
            booster.times_helped += 1
        booster.save()
        
        # Generate encouragement
        improvement = usage.mood_improvement
        if improvement is not None and improvement > 0:
            message = f"That's awesome! Your mood improved by {improvement} points! 🌟"
        elif mood_after is not None:
            message = "Thanks for trying! Sometimes it takes a few attempts to find what works for you. 💙"
        else:
            message = "Thanks for giving it a shot! Let us know how you feel after. 💚"
        
        return Response({
            'success': True,
            'mood_improvement': usage.mood_improvement,
            'message': message
        })
    
    @action(detail=True, methods=['post'])
    def rate(self, request, pk=None):
        """
        Rate a booster's effectiveness.
        
        POST /api/mood-boosters/{id}/rate/
        Body: {"rating": 4, "did_it_help": true}
        """
        booster = self.get_object()
        rating = request.data.get('rating') or request.data.get('effectiveness_rating')
        did_it_help = request.data.get('did_it_help')
        if did_it_help is None and 'would_recommend' in request.data:
            did_it_help = request.data.get('would_recommend')
        
        # Find most recent usage
        usage = MoodBoosterUsage.objects.filter(
            user=request.user,
            booster=booster
        ).order_by('-tried_at').first()
        
        if usage:
            if rating is not None and rating != '':
                try:
                    usage.rating = int(rating)
                except (TypeError, ValueError):
                    pass
            if did_it_help is not None:
                usage.did_it_help = bool(did_it_help)
            usage.save()
            
            # Update booster average rating
            avg_rating = MoodBoosterUsage.objects.filter(
                booster=booster,
                rating__isnull=False
            ).aggregate(Avg('rating'))['rating__avg']
            
            booster.average_rating = float(avg_rating) if avg_rating is not None else 0.0
            booster.save()
            
            return Response({
                'success': True,
                'message': 'Thanks for the feedback! This helps us recommend better activities. ✨'
            })
        
        return Response(
            {'error': 'No usage record found'},
            status=status.HTTP_404_NOT_FOUND
        )
 
 
# ==================== AFFIRMATIONS API ====================
 
@api_view(['GET'])
@permission_classes([AllowAny])
def get_daily_affirmation(request):
    """
    Get a daily affirmation.
    Personalized based on current mood if provided.
    
    GET /api/affirmations/daily/?mood=anxious
    """
    mood = request.query_params.get('mood')
    
    # Get affirmations
    affirmations = list(DailyAffirmation.objects.filter(is_active=True))
    if not affirmations:
        return Response({
            'id': None,
            'emoji': '💙',
            'message': 'You are doing your best. Affirmations will appear here once content is added.',
            'follow_up': '',
            'category': '',
        })
    
    if mood:
        # Prefer mood-specific affirmations
        mood_specific = [a for a in affirmations if a.for_mood == mood]
        affirmation = random.choice(mood_specific) if mood_specific else random.choice(affirmations)
    else:
        affirmation = random.choice(affirmations)
    
    # Update stats
    affirmation.times_shown += 1
    affirmation.save()
    
    return Response({
        'id': affirmation.id,
        'emoji': affirmation.emoji,
        'message': affirmation.message,
        'follow_up': affirmation.follow_up,
        'category': affirmation.get_category_display()
    })
 
 
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_affirmation(request, affirmation_id):
    """
    Save an affirmation that resonated.
    
    POST /api/affirmations/{id}/save/
    Body: {"why_it_resonated": "This reminds me I'm enough"}
    """
    try:
        affirmation = DailyAffirmation.objects.get(id=affirmation_id)
        
        saved, created = SavedAffirmation.objects.get_or_create(
            user=request.user,
            affirmation=affirmation,
            defaults={'why_it_resonated': request.data.get('why_it_resonated', '')}
        )
        
        if created:
            affirmation.times_saved += 1
            affirmation.save()
            
            return Response({
                'success': True,
                'message': 'Saved! You can revisit this anytime in your collection. 💖'
            })
        else:
            return Response({
                'success': True,
                'message': 'You already saved this one! ✨'
            })
    except DailyAffirmation.DoesNotExist:
        return Response(
            {'error': 'Affirmation not found'},
            status=status.HTTP_404_NOT_FOUND
        )
# ==================== CRISIS RESOURCES API ====================
 
@api_view(['GET'])
@permission_classes([AllowAny])
def get_crisis_resources(request):
    """
    Get appropriate crisis resources for user.
    
    GET /api/crisis/resources/?severity=high
    """
    severity = request.query_params.get('severity', 'general')
    is_lgbtq = request.query_params.get('lgbtq', 'false').lower() == 'true'
    
    # Get resources
    resources = CrisisResource.objects.filter(is_active=True)
    
    # Filter by severity
    if severity == 'immediate':
        resources = resources.filter(severity_level='immediate')
    elif severity == 'urgent':
        resources = resources.filter(severity_level__in=['immediate', 'urgent'])
    
    # Include LGBTQ-focused if requested
    if is_lgbtq:
        lgbtq_resources = resources.filter(is_lgbtq_focused=True)
        general_resources = resources.filter(is_lgbtq_focused=False)[:2]
        resources = list(lgbtq_resources) + list(general_resources)
    else:
        resources = resources[:6]
    
    # Update shown count
    for resource in resources:
        resource.times_shown += 1
        resource.save()
    
    # Format response
    resources_data = []
    for r in resources:
        resources_data.append({
            'id': r.id,
            'name': r.name,
            'type': r.get_resource_type_display(),
            'phone': r.phone_number,
            'sms': r.sms_number,
            'website': r.website_url,
            'description': r.short_description,
            'hours': r.hours_available,
            'languages': r.languages_supported,
            'is_campus': r.is_campus_resource,
            'campus_location': r.campus_location if r.is_campus_resource else None
        })
    
    return Response({
        'resources': resources_data,
        'message': get_crisis_message(severity),
        'severity': severity
    })
 
 
def get_crisis_message(severity):
    """Get appropriate message for crisis level."""
    messages = {
        'immediate': "You're going through something really difficult right now. Please reach out to one of these resources - they're here to help you right now, 24/7.",
        'urgent': "It sounds like you're struggling. These resources can provide support. You don't have to go through this alone.",
        'general': "Here are some resources that might help. It's always okay to reach out for support."
    }
    return messages.get(severity, messages['general'])
 
 
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def track_resource_click(request, resource_id):
    """
    Track when user clicks on a crisis resource.
    
    POST /api/crisis/resources/{id}/click/
    """
    try:
        resource = CrisisResource.objects.get(id=resource_id)
        resource.times_clicked += 1
        resource.save()
        
        # If there's an active crisis event, track it
        crisis_event_id = request.data.get('crisis_event_id')
        if crisis_event_id:
            try:
                crisis_event = CrisisEvent.objects.get(
                    id=crisis_event_id,
                    user=request.user
                )
                crisis_event.mark_resource_clicked(resource_id)
                crisis_event.user_viewed_resources = True
                crisis_event.save()
            except CrisisEvent.DoesNotExist:
                pass
        
        return Response({
            'success': True,
            'message': 'Resource click tracked'
        })
    except CrisisResource.DoesNotExist:
        return Response(
            {'error': 'Resource not found'},
            status=status.HTTP_404_NOT_FOUND
        )
 
 
# ==================== SOS BUTTON API ====================
 
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def press_sos_button(request):
    """
    User pressed SOS/Help button - immediate crisis intervention.
    
    POST /api/crisis/sos/
    Body: {
        "note": "I need help",
        "mood": 2,
        "location": "Dorm room"
    }
    """
    user = request.user
    
    user_note = request.data.get('note')
    if user_note is None:
        user_note = request.data.get('notes', '')
    loc = request.data.get('location')
    if loc is None:
        loc = ''
    
    # Create SOS record
    sos = SOSButton.objects.create(
        user=user,
        user_note=user_note or '',
        current_mood=request.data.get('mood'),
        current_location=str(loc)[:200]
    )
    
    # Create crisis event
    crisis_event = CrisisEvent.objects.create(
        user=user,
        trigger_type='manual_sos',
        severity='critical',
        detection_data={
            'source': 'sos_button',
            'user_note': sos.user_note,
            'mood': sos.current_mood,
            'location': sos.current_location
        }
    )
    
    sos.crisis_event = crisis_event
    sos.save()
    
    # Get immediate crisis resources
    resources = CrisisResource.objects.filter(
        is_active=True,
        severity_level='immediate'
    ).order_by('-priority')[:5]
    
    crisis_event.resources_displayed.set(resources)
    
    notifications_sent = {}
    try:
        push_result = NotificationService.send_push_notification(
            user=user,
            title="We're here for you",
            message="You pressed SOS. Please reach out to a crisis resource now.",
            data={'type': 'sos', 'crisis_event_id': crisis_event.id}
        )
        notifications_sent['push'] = push_result
        
        if getattr(user, 'email', None) and hasattr(user, 'userprofile') and getattr(
            user.userprofile, 'crisis_email_enabled', False
        ):
            email_result = NotificationService.send_email_notification(
                to_email=user.email,
                subject="Crisis Support Resources - We're Here",
                message=(
                    "You indicated you need help. Please call or text one of these crisis resources: "
                    "Crisis Text Line: Text 741741, Suicide & Crisis Lifeline: 988"
                ),
            )
            notifications_sent['email'] = email_result
        
        trusted_contacts = TrustedContact.objects.filter(
            user=user,
            is_active=True,
            notify_on_severity__in=['critical', 'high', 'medium']
        )
        
        contacts_notified = []
        for contact in trusted_contacts:
            if contact.notify_via_email and contact.email:
                NotificationService.send_email_notification(
                    to_email=contact.email,
                    subject=f"Support Needed: {user.username}",
                    message=(
                        f"{user.username} has indicated they need help through our wellness app. "
                        "Please check in with them when you can."
                    ),
                )
                contact.times_notified += 1
                contact.last_notified = timezone.now()
                contact.save()
                contacts_notified.append(contact.name)
        
        notifications_sent['trusted_contacts'] = contacts_notified
        
        admin_result = NotificationService.notify_admin_dashboard(crisis_event)
        notifications_sent['admin'] = admin_result
    except Exception as exc:
        notifications_sent['notification_error'] = type(exc).__name__
    
    crisis_event.notifications_sent = notifications_sent
    crisis_event.save()
    
    # Return resources and confirmation
    return Response({
        'success': True,
        'crisis_event_id': crisis_event.id,
        'resources': [
            {
                'id': r.id,
                'name': r.name,
                'type': r.get_resource_type_display(),
                'phone': r.phone_number,
                'sms': r.sms_number,
                'website': r.website_url,
                'description': r.short_description,
                'hours': r.hours_available
            }
            for r in resources
        ],
        'message': "We're here for you. Please reach out to one of these resources right now. You don't have to go through this alone.",
        'notifications_sent': sum(
            1 for v in notifications_sent.values()
            if isinstance(v, dict) and v.get('success')
        ),
    })
 
 
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def confirm_got_help(request, sos_id):
    """
    User confirms they got help after SOS.
    
    POST /api/crisis/sos/{id}/confirm-help/
    Body: {"note": "Talked to counselor, feeling better"}
    """
    try:
        sos = SOSButton.objects.get(id=sos_id, user=request.user)
        sos.user_got_help = True
        note = request.data.get('note')
        if note is None:
            note = request.data.get('notes', '')
        src = request.data.get('help_source')
        if src:
            note = (f"{note} (source: {src})" if note else f"(source: {src})").strip()
        sos.resolution_note = note or ''
        sos.resolved_at = timezone.now()
        sos.save()
        
        if sos.crisis_event:
            sos.crisis_event.user_contacted_resource = True
            sos.crisis_event.save()
        
        return Response({
            'success': True,
            'message': "We're so glad you got help. You did the right thing by reaching out. 💙"
        })
    except SOSButton.DoesNotExist:
        return Response(
            {'error': 'SOS record not found'},
            status=status.HTTP_404_NOT_FOUND
        )
 
 
# ==================== TRUSTED CONTACTS API ====================
 
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def manage_trusted_contacts(request, contact_id=None):
    """
    Get, add, or remove trusted emergency contacts.

    GET    /api/crisis/contacts/
    POST   /api/crisis/contacts/
    DELETE /api/crisis/contacts/{id}/   (Fix COMPAT-04)
    """
    # Fix COMPAT-04: handle DELETE for removing a specific contact
    if request.method == 'DELETE':
        if contact_id is None:
            return Response({'error': 'contact_id required'}, status=status.HTTP_400_BAD_REQUEST)
        TrustedContact.objects.filter(id=contact_id, user=request.user).update(is_active=False)
        return Response({'success': True})

    if request.method == 'GET':
        contacts = TrustedContact.objects.filter(
            user=request.user,
            is_active=True
        )
        
        return Response({
            'contacts': [
                {
                    'id': c.id,
                    'name': c.name,
                    'relationship': c.relationship,
                    'email': c.email if c.notify_via_email else None,
                    'phone': c.phone if c.notify_via_sms else None,
                    'notify_on': c.get_notify_on_severity_display(),
                    'times_notified': c.times_notified
                }
                for c in contacts
            ]
        })
    
    else:  # POST
        # Limit to 3 trusted contacts
        if TrustedContact.objects.filter(user=request.user, is_active=True).count() >= 5:
            return Response(
                {'error': 'Maximum 5 trusted contacts allowed'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        phone = request.data.get('phone') or request.data.get('phone_number', '')
        contact = TrustedContact.objects.create(
            user=request.user,
            name=request.data.get('name'),
            relationship=request.data.get('relationship'),
            email=request.data.get('email', ''),
            phone=phone,
            notify_via_email=request.data.get('notify_via_email', False),
            notify_via_sms=request.data.get('notify_via_sms', False),
            notify_on_severity=request.data.get('notify_on_severity', 'critical'),
            user_confirmed_consent=request.data.get('user_confirmed_consent', False)
        )
        
        return Response({
            'success': True,
            'contact_id': contact.id,
            'message': f'{contact.name} added as trusted contact'
        }, status=status.HTTP_201_CREATED)
 
 
# ==================== AUTOMATIC CRISIS DETECTION ====================
 
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def run_crisis_check(request):
    """
    Manually trigger crisis detection check.
    Usually this runs automatically after mood entries.
    
    POST /api/crisis/check/
    """
    user = request.user
    
    # Run detection
    crisis = CrisisDetector.check_all(user)
    
    if not crisis:
        return Response({
            'crisis_detected': False,
            'message': 'No crisis indicators detected. Keep taking care of yourself! 💚'
        })
    
    # Crisis detected - create event and show resources
    crisis_event = CrisisEvent.objects.create(
        user=user,
        trigger_type=crisis['trigger'],
        severity=crisis['severity'],
        detection_data=crisis['data']
    )
    
    # Get appropriate resources
    if crisis['severity'] in ['critical', 'high']:
        resource_severity = 'immediate'
    elif crisis['severity'] == 'medium':
        resource_severity = 'urgent'
    else:
        resource_severity = 'general'
    
    resources = CrisisResource.objects.filter(
        is_active=True,
        severity_level=resource_severity
    ).order_by('-priority')[:5]
    
    crisis_event.resources_displayed.set(resources)
    
    return Response({
        'crisis_detected': True,
        'severity': crisis['severity'],
        'message': crisis['message'],
        'crisis_event_id': crisis_event.id,
        'resources': [
            {
                'id': r.id,
                'name': r.name,
                'type': r.get_resource_type_display(),
                'phone': r.phone_number,
                'sms': r.sms_number,
                'website': r.website_url,
                'description': r.short_description,
                'hours': r.hours_available
            }
            for r in resources
        ],
        'support_message': get_crisis_message(resource_severity)
    })
@api_view(['GET'])
@permission_classes([AllowAny])
def get_privacy_statement(request):
    '''Get privacy information for user.'''
    
    user_privacy_settings = None  # Fix BE-10: renamed to avoid shadowing django.conf.settings
    if request.user.is_authenticated:
        user_privacy_settings, _ = UserPrivacySettings.objects.get_or_create(
            user=request.user
        )
        user_privacy_settings.review_privacy_statement()
    
    # Get privacy education
    education = PrivacyEducation.objects.filter(is_active=True).order_by('-priority')
    
    return Response({
        'privacy_promise': {
            'title': 'Your Privacy Promise',
            'points': [
                'Only YOU can see your mood entries and check-ins',
                'NOT shared with parents, school, or administrators',
                'Crisis alerts go to YOU first (you choose who else)',
                'You control all privacy settings',
                'Delete your data anytime in Settings',
                'No one can access your data without your permission'
            ]
        },
        'current_settings': (
            {
                'counselors_can_see': user_privacy_settings.data_visible_to_counselors,
                'research_allowed': user_privacy_settings.data_visible_to_researchers,
                'trusted_contacts_enabled': user_privacy_settings.can_notify_trusted_contacts,
                'reminders_enabled': user_privacy_settings.reminder_notifications
            }
            if user_privacy_settings is not None
            else {
                'message': 'Sign in to load your saved privacy preferences.',
            }
        ),
        'faq': [
            {
                'question': edu.question,
                'answer': edu.short_answer,
                'detailed': edu.detailed_answer
            }
            for edu in education[:5]
        ],
        'data_access_link': '/api/privacy/access-log/',
        'settings_link': '/api/privacy/settings/'
    })
 
 
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_data_access_log(request):
    '''Show user who accessed their data.'''
    
    # 1. Create the base queryset (Do NOT slice here)
    base_logs = DataAccessLog.objects.filter(user=request.user)
    
    # 2. Get the specific sliced list for the 'logs' display
    # Order first, then slice at the very end
    display_logs = base_logs.order_by('-accessed_at')[:50]
    
    return Response({
        'message': 'Complete log of who accessed your data',
        'logs': [
            {
                'when': log.accessed_at,
                'who': log.accessed_by.username if log.accessed_by else 'You',
                'what': log.get_access_type_display(),
                'details': log.data_accessed,
                'reason': log.reason
            }
            for log in display_logs
        ],
        # 3. Use the unsliced base_logs for these calculations
        'total_accesses': base_logs.count(),
        'your_accesses': base_logs.filter(access_type='user_view').count(),
        'other_accesses': base_logs.exclude(access_type='user_view').count()
    })
@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def manage_privacy_settings(request):
    '''Get or update privacy settings.'''
    
    settings, _ = UserPrivacySettings.objects.get_or_create(user=request.user)
    
    if request.method == 'GET':
        return Response({
            'settings': {
                'counselors_can_see': settings.data_visible_to_counselors,
                'research_allowed': settings.data_visible_to_researchers,
                'crisis_alerts': settings.crisis_alerts_enabled,
                'trusted_contacts': settings.can_notify_trusted_contacts,
                'reminders': settings.reminder_notifications,
                'encouragement': settings.encouragement_notifications,
                'auto_delete_old': settings.auto_delete_old_entries,
                'share_with_counselors': settings.data_visible_to_counselors,
                'share_progress_with_buddies': settings.encouragement_notifications,
            },
            'explanations': {
                'counselors_can_see': 'Campus counselors can see your check-ins to provide better support',
                'research_allowed': 'Anonymized data helps improve mental health services',
                'trusted_contacts': 'Your emergency contacts will be notified in crisis'
            }
        })
    
    else:  # PUT / PATCH
        if 'share_with_counselors' in request.data:
            settings.data_visible_to_counselors = request.data.get('share_with_counselors')
        elif 'counselors_can_see' in request.data:
            settings.data_visible_to_counselors = request.data.get('counselors_can_see')
        if 'research_allowed' in request.data:
            settings.data_visible_to_researchers = request.data.get('research_allowed')
        if 'trusted_contacts' in request.data:
            settings.can_notify_trusted_contacts = request.data.get('trusted_contacts')
        if 'reminders' in request.data:
            settings.reminder_notifications = request.data.get('reminders')
        if 'share_progress_with_buddies' in request.data:
            settings.encouragement_notifications = request.data.get('share_progress_with_buddies')
        settings.save()
        
        return Response({
            'success': True,
            'message': 'Privacy settings updated'
        })
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def start_adaptive_quiz(request):
    '''
    Start a new adaptive quiz session.
    
    POST /api/stress-assessment/adaptive/start/
    Body: {
        "mode": "quick|standard|comprehensive",
        "selected_categories": ["social", "academic"]  // optional
    }
    '''
    mode = request.data.get('mode', 'quick')
    selected_categories = request.data.get('selected_categories', [])
    
    # Create quiz session
    session = QuizSession.objects.create(
        user=request.user,
        quiz_mode=mode,
        selected_categories=selected_categories
    )
    
    # Determine quiz type
    if selected_categories:
        # Category-selection mode
        questions_per_cat = 3 if mode == 'quick' else 5
        questions = CategorySelectionQuiz.get_questions_for_categories(
            selected_categories,
            questions_per_cat
        )
        session.questions_asked = [q.id for q in questions]
        session.total_questions = len(questions)
        session.save()
        first_question = questions[0] if questions else None
    else:
        # Adaptive mode
        first_question = AdaptiveQuestionSelector.get_next_question(session)
    
    if not first_question:
        return Response(
            {
                'session_id': session.id,
                'message': 'No questions available yet — add StressAssessmentQuestion rows in admin.',
                'total_questions': 0,
            },
            status=status.HTTP_200_OK,
        )
    
    return Response({
        'session_id': session.id,
        'mode': session.get_quiz_mode_display(),
        'total_questions': session.total_questions,
        'current_question': 1,
        'progress': session.progress_percentage,
        'question': {
            'id': first_question.id,
            'text': first_question.question_text,
            'category': {
                'name': first_question.category.name,
                'emoji': first_question.category.emoji
            }
        },
        'response_scale': [
            {'value': 0, 'label': 'Never'},
            {'value': 1, 'label': 'Rarely'},
            {'value': 2, 'label': 'Sometimes'},
            {'value': 3, 'label': 'Often'},
            {'value': 4, 'label': 'All the time'}
        ]
    })
 
 
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def answer_adaptive_question(request, session_id):
    '''
    Answer a question and get the next one.
    
    POST /api/stress-assessment/adaptive/{session_id}/answer/
    Body: {
        "question_id": 123,
        "score": 3
    }
    '''
    try:
        session = QuizSession.objects.get(
            id=session_id,
            user=request.user,
            is_complete=False
        )
    except QuizSession.DoesNotExist:
        return Response(
            {'error': 'Quiz session not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    question_id = str(request.data.get('question_id', ''))
    score = request.data.get('score')
    if score is None:
        score = request.data.get('answer_value')
    
    # Save response
    session.responses[question_id] = score
    session.current_question_index += 1
    session.save()
    
    # Check if quiz is complete
    if session.current_question_index >= session.total_questions:
        # Generate final results
        from .views import StressAssessmentViewSet
        
        # Calculate scores (reuse existing logic)
        assessment = StressAssessmentResponse.objects.create(
            user=request.user,
            responses=session.responses,
            category_scores={},  # Will be calculated
            overall_stress_score=0  # Will be calculated
        )
        
        # Link to session
        session.assessment_response = assessment
        session.mark_complete()
        
        # Calculate and return results
        # (Reuse your existing calculation logic)
        
        return Response({
            'complete': True,
            'session_id': session.id,
            'completion_time': f"{session.completion_time_seconds // 60} minutes",
            'results': {
                'assessment_id': assessment.id,
                'overall_stress': assessment.overall_stress_score,
                'message': 'Quiz complete! Here are your results...'
            }
        })
    
    # Get next question
    next_question = AdaptiveQuestionSelector.get_next_question(session)
    
    if not next_question:
        # Shouldn't happen, but handle gracefully
        session.mark_complete()
        return Response({
            'complete': True,
            'message': 'No more questions needed'
        })
    
    return Response({
        'complete': False,
        'session_id': session.id,
        'current_question': session.current_question_index + 1,
        'total_questions': session.total_questions,
        'progress': session.progress_percentage,
        'questions_remaining': session.questions_remaining,
        'question': {
            'id': next_question.id,
            'text': next_question.question_text,
            'category': {
                'name': next_question.category.name,
                'emoji': next_question.category.emoji
            }
        }
    })
 
 
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_category_selection_options(request):
    '''
    Get categories for user to select (alternative quiz mode).
    
    GET /api/stress-assessment/categories/select/
    '''
    from .models import StressCategory
    
    categories = StressCategory.objects.filter(is_active=True)
    
    return Response({
        'message': 'Select the areas affecting you most (choose 2-5):',
        'categories': [
            {
                'id': cat.category_type,
                'name': cat.name,
                'emoji': cat.emoji,
                'description': cat.description,
                'questions_count': 3  # Will ask 3 questions per selected category
            }
            for cat in categories
        ],
        'recommendation': 'Most students select 2-3 categories for a focused assessment'
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_tiered_support(request):
    '''
    Get appropriate support based on user's current stress level.
    
    GET /api/support/tiered/?stress_score=65
    '''
    # Get stress score from latest assessment
    latest_assessment = StressAssessmentResponse.objects.filter(
        user=request.user
    ).order_by('-session_date').first()
    
    if not latest_assessment:
        return Response({
            'message': 'Take a stress assessment first to get personalized support'
        })
    
    stress_score = latest_assessment.overall_stress_score
    
    # Get tiered support
    support = TieredSupportGenerator.get_support_for_level(stress_score)
    
    return Response(support)
 
 
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_progress_dashboard(request):
    '''
    Get user's progress dashboard with achievements and trends.
    
    GET /api/progress/dashboard/
    '''
    # Calculate weekly progress
    weekly_report = ProgressCalculator.calculate_weekly_progress(request.user)
    
    # Check for new milestones
    new_milestones = ProgressCalculator.check_for_milestones(request.user)
    
    # Get all milestones
    all_milestones = ProgressMilestone.objects.filter(
        user=request.user
    ).order_by('-achieved_at')[:10]
    
    # Get user stats
    stats, _ = UserStats.objects.get_or_create(user=request.user)
    
    return Response({
        'summary': weekly_report.progress_summary,
        'this_week': {
            'check_ins': weekly_report.check_ins_this_week,
            'mood_boosters': weekly_report.mood_boosters_tried,
            'stress_change': weekly_report.stress_change,
            'biggest_win': weekly_report.biggest_improvement
        },
        'current_streak': {
            'days': stats.current_streak,
            'longest_ever': stats.longest_streak,
            'emoji': '🔥' if stats.current_streak > 0 else '💙'
        },
        'achievements': [
            {
                'emoji': m.emoji,
                'title': m.title,
                'description': m.description,
                'achieved_at': m.achieved_at
            }
            for m in all_milestones
        ],
        'new_achievements': len(new_milestones),
        'encouragement': ProgressCalculator._get_encouragement(weekly_report)
    })

# ==================== COMMUNITY FEED API ====================
 
class CommunityFeedViewSet(viewsets.ModelViewSet):
    """
    Anonymous community feed.
    """
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get approved, non-flagged posts."""
        return CommunityPost.objects.filter(
            is_approved=True,
            is_flagged=False
        ).annotate(
            relates_count=Count('communityrelate')
        ).order_by('-last_activity')
    
    @action(detail=False, methods=['get'])
    def feed(self, request):
        """
        Get community feed with filters.
        
        GET /api/community/feed/?category=social&limit=20
        """
        category = request.query_params.get('category')
        limit = int(request.query_params.get('limit', 20))
        
        posts = self.get_queryset()
        
        if category:
            posts = posts.filter(category=category)
        
        posts = posts[:limit]
        
        # Build response
        feed_data = []
        for post in posts:
            # Check if user has related
            user_related = CommunityRelate.objects.filter(
                post=post,
                user=request.user
            ).exists()
            
            feed_data.append({
                'id': post.id,
                'anonymous_id': post.anonymous_id,
                'category': post.get_category_display(),
                'category_emoji': self._get_category_emoji(post.category),
                'content': post.content,
                'time_ago': post.time_since_posted,
                'relate_count': post.relate_count,
                'reply_count': post.reply_count,
                'user_related': user_related,
                'can_reply': post.can_user_reply(request.user)
            })
        
        # Campus stats
        today = timezone.now().date()
        checkin_count = MoodEntry.objects.filter(
            timestamp__date=today
        ).values('user').distinct().count()
        
        return Response({
            'campus_stats': {
                'students_checked_in_today': checkin_count,
                'message': f"📍 {checkin_count} students on campus checked in today"
            },
            'posts': feed_data,
            'can_post_today': CommunityPostingLimit.can_post_today(request.user)
        })
    
    @action(detail=False, methods=['post'])
    def create_post(self, request):
        """
        Create anonymous community post.
        
        POST /api/community/create_post/
        Body: {
            "category": "social",
            "content": "Does anyone else..."
        }
        """
        # Check posting limit
        if not CommunityPostingLimit.can_post_today(request.user):
            return Response({
                'error': 'You can only post once per day. Try again tomorrow!'
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)
        
        category = request.data.get('category')
        if category:
            category = COMMUNITY_CATEGORY_ALIASES.get(category, category)
        valid_cats = {c[0] for c in CommunityPost.POST_CATEGORIES}
        if not category or category not in valid_cats:
            category = 'general'
        content = request.data.get('content', '').strip()
        
        # Validate
        if not content:
            return Response({
                'error': 'Content cannot be empty'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if len(content) > 500:
            return Response({
                'error': 'Content must be 500 characters or less'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # AI moderation
        moderation_result = AIContentModeration.moderate_content(content)
        
        # Create post
        post = CommunityPost.objects.create(
            author=request.user,
            category=category,
            content=content,
            is_ai_approved=moderation_result['ai_approved']
        )
        
        # Create moderation record
        AIContentModeration.objects.create(
            post=post,
            **moderation_result
        )
        
        # Update posting limit
        today = timezone.now().date()
        limit, created = CommunityPostingLimit.objects.get_or_create(
            user=request.user,
            last_post_date=today,
            defaults={'posts_today': 0}
        )
        limit.posts_today += 1
        limit.save()
        
        # Response
        if moderation_result['flagged_for_review']:
            return Response({
                'status': 'pending_review',
                'message': 'Your post is under review. It will appear once approved.',
                'reason': 'Flagged for manual review'
            })
        elif moderation_result['ai_approved']:
            # Auto-approve
            post.is_approved = True
            post.save()
            
            return Response({
                'status': 'posted',
                'message': 'Your post is live! 💬',
                'post_id': post.id,
                'anonymous_id': post.anonymous_id
            })
        else:
            return Response({
                'error': 'Your post could not be approved. Please check our community guidelines.',
                'details': 'Content may contain identifying information or harmful language'
            }, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def relate(self, request, pk=None):
        """
        User clicks "I relate" on a post.
        
        POST /api/community/{post_id}/relate/
        """
        post = self.get_object()
        
        # Check if already related
        if not post.can_user_relate(request.user):
            return Response({
                'error': 'You already related to this post'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Create relate
        CommunityRelate.objects.create(
            user=request.user,
            post=post
        )
        
        # Update count
        post.relate_count += 1
        post.last_activity = timezone.now()
        post.save()
        
        return Response({
            'message': 'Sent support 💙',
            'new_count': post.relate_count
        })
    
    @action(detail=True, methods=['get'])
    def replies(self, request, pk=None):
        """
        Get replies to a post.
        
        GET /api/community/{post_id}/replies/
        """
        post = self.get_object()
        
        replies = CommunityReply.objects.filter(
            post=post,
            is_approved=True,
            is_flagged=False
        ).order_by('replied_at')
        
        replies_data = []
        for reply in replies:
            replies_data.append({
                'id': reply.id,
                'anonymous_id': reply.anonymous_id,
                'content': reply.content,
                'time_ago': (timezone.now() - reply.replied_at).seconds // 60,
                'helpful_count': reply.helpful_count
            })
        
        return Response({
            'post_id': post.id,
            'replies': replies_data
        })
    
    @action(detail=True, methods=['post'])
    def reply(self, request, pk=None):
        """
        Reply to a post.
        
        POST /api/community/{post_id}/reply/
        Body: {
            "content": "I feel the same way..."
        }
        """
        post = self.get_object()
        content = request.data.get('content', '').strip()
        
        # Validate
        if not content:
            return Response({
                'error': 'Reply cannot be empty'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if len(content) > 300:
            return Response({
                'error': 'Reply must be 300 characters or less'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # AI moderation
        moderation_result = AIContentModeration.moderate_content(content)
        
        # Create reply
        reply = CommunityReply.objects.create(
            post=post,
            author=request.user,
            content=content,
            is_approved=moderation_result['ai_approved']
        )
        
        # Create moderation record
        AIContentModeration.objects.create(
            reply=reply,
            **moderation_result
        )
        
        # Update post
        if moderation_result['ai_approved']:
            post.reply_count += 1
            post.last_activity = timezone.now()
            post.save()
            
            return Response({
                'message': 'Reply posted! 💬',
                'reply_id': reply.id
            })
        else:
            return Response({
                'status': 'pending_review',
                'message': 'Your reply is under review'
            })
    
    @action(detail=True, methods=['post'])
    def flag(self, request, pk=None):
        """
        Flag inappropriate content.
        
        POST /api/community/{post_id}/flag/
        Body: {
            "reason": "harmful",
            "details": "Contains self-harm language"
        }
        """
        post = self.get_object()
        
        reason = request.data.get('reason')
        details = request.data.get('details', '')
        
        # Create flag
        PostFlag.objects.create(
            post=post,
            flagged_by=request.user,
            reason=reason,
            details=details
        )
        
        # Update post
        post.flag_count += 1
        if post.flag_count >= 3:
            post.is_flagged = True
        post.save()
        
        return Response({
            'message': 'Thank you for helping keep our community safe 💙'
        })
    
    def _get_category_emoji(self, category):
        """Get emoji for category."""
        emoji_map = {
            'academic': '📚',
            'social': '👥',
            'relationships': '💕',
            'family': '🏠',
            'identity': '🔍',
            'loneliness': '😔',
            'body_image': '💭',
            'general': '💬',
        }
        return emoji_map.get(category, '💬')
 
 
# ==================== JOURNALING API ====================
 
class JournalingViewSet(viewsets.ViewSet):
    """
    Personal journaling system.
    """
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['get'])
    def daily_prompt(self, request):
        """
        Get today's journal prompt.
        
        GET /api/journal/daily_prompt/
        """
        prompt = JournalPrompt.get_daily_prompt()
        
        if not prompt:
            return Response({
                'prompt': 'What\'s on your mind today?',
                'category': 'free_write'
            })
        
        return Response({
            'id': prompt.id,
            'prompt': prompt.prompt_text,
            'category': prompt.get_category_display(),
            'difficulty': prompt.get_difficulty_display(),
            'alternates': [
                prompt.alternate_text_1,
                prompt.alternate_text_2
            ] if prompt.alternate_text_1 else []
        })
    
    @action(detail=False, methods=['post'])
    def write(self, request):
        """
        Create journal entry.
        
        POST /api/journal/write/
        Body: {
            "entry_type": "prompted",
            "prompt_id": 1,
            "title": "My thoughts...",
            "content": "Today I...",
            "mood_tag": "grateful"
        }
        """
        entry_type = request.data.get('entry_type', 'free_write')
        prompt_id = request.data.get('prompt_id')
        title = request.data.get('title', '')
        content = request.data.get('content', '').strip()
        mood_tag = request.data.get('mood_tag', '')
        
        if not content:
            return Response({
                'error': 'Content cannot be empty'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get prompt if provided
        prompt = None
        if prompt_id:
            try:
                prompt = JournalPrompt.objects.get(id=prompt_id)
            except JournalPrompt.DoesNotExist:
                pass
        
        # Create entry
        entry = JournalEntry.objects.create(
            user=request.user,
            entry_type=entry_type,
            prompt=prompt,
            title=title,
            content=content,
            mood_tag=mood_tag
        )
        
        # Update streak
        streak, created = JournalStreak.objects.get_or_create(user=request.user)
        streak.update_streak()
        
        return Response({
            'message': 'Entry saved 💙',
            'entry_id': entry.id,
            'word_count': entry.word_count,
            'streak': {
                'current': streak.current_streak,
                'longest': streak.longest_streak,
                'total_entries': streak.total_entries
            }
        })
    
    @action(detail=False, methods=['get'])
    def entries(self, request):
        """
        Get user's journal entries.
        
        GET /api/journal/entries/?limit=20&mood=grateful
        """
        limit = int(request.query_params.get('limit', 20))
        mood_filter = request.query_params.get('mood')
        
        entries = JournalEntry.objects.filter(user=request.user)
        
        if mood_filter:
            entries = entries.filter(mood_tag=mood_filter)
        
        entries = entries.order_by('-written_at')[:limit]
        
        entries_data = []
        for entry in entries:
            entries_data.append({
                'id': entry.id,
                'title': entry.title or f"Entry from {entry.written_at.strftime('%B %d')}",
                'preview': entry.preview,
                'mood_tag': entry.get_mood_tag_display() if entry.mood_tag else None,
                'word_count': entry.word_count,
                'written_at': entry.written_at,
                'is_favorite': entry.is_favorite
            })
        
        # Get streak info
        streak, _ = JournalStreak.objects.get_or_create(user=request.user)
        
        return Response({
            'entries': entries_data,
            'streak': {
                'current': streak.current_streak,
                'longest': streak.longest_streak,
                'total': streak.total_entries
            }
        })
    
    @action(detail=True, methods=['get'])
    def entry_detail(self, request, pk=None):
        """
        Get full journal entry.
        
        GET /api/journal/{entry_id}/entry_detail/
        """
        try:
            entry = JournalEntry.objects.get(
                id=pk,
                user=request.user
            )
        except JournalEntry.DoesNotExist:
            return Response({
                'error': 'Entry not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        return Response({
            'id': entry.id,
            'title': entry.title,
            'content': entry.content,
            'mood_tag': entry.get_mood_tag_display() if entry.mood_tag else None,
            'word_count': entry.word_count,
            'written_at': entry.written_at,
            'updated_at': entry.updated_at,
            'is_favorite': entry.is_favorite,
            'prompt': entry.prompt.prompt_text if entry.prompt else None
        })
    
    @action(detail=True, methods=['post'])
    def toggle_favorite(self, request, pk=None):
        """
        Toggle favorite status.
        
        POST /api/journal/{entry_id}/toggle_favorite/
        """
        try:
            entry = JournalEntry.objects.get(
                id=pk,
                user=request.user
            )
        except JournalEntry.DoesNotExist:
            return Response({
                'error': 'Entry not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        entry.is_favorite = not entry.is_favorite
        entry.save()
        
        return Response({
            'is_favorite': entry.is_favorite
        })

    def list(self, request):
        """GET /api/journal/ — list entries."""
        return self.entries(request)

    def create(self, request):
        """POST /api/journal/ — create entry."""
        return self.write(request)

    def retrieve(self, request, pk=None):
        """GET /api/journal/{id}/"""
        return self.entry_detail(request, pk=pk)

    def partial_update(self, request, pk=None):
        """PATCH /api/journal/{id}/"""
        try:
            entry = JournalEntry.objects.get(id=pk, user=request.user)
        except JournalEntry.DoesNotExist:
            return Response({'error': 'Entry not found'}, status=status.HTTP_404_NOT_FOUND)
        for field in ['title', 'content', 'mood_tag', 'is_favorite']:
            if field in request.data:
                val = request.data[field]
                if field == 'is_favorite':
                    val = bool(val)
                setattr(entry, field, val)
        entry.save()
        return Response(JournalEntrySerializer(entry).data)

    def destroy(self, request, pk=None):
        """DELETE /api/journal/{id}/"""
        try:
            JournalEntry.objects.get(id=pk, user=request.user).delete()
        except JournalEntry.DoesNotExist:
            return Response({'error': 'Entry not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ==================== AFFIRMATION SAVE/UNSAVE (Fix FE-08, FE-09) ====================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_saved_affirmations(request):
    """
    Get all affirmations saved by the user.
    GET /api/affirmations/saved/
    Fix FE-08: was missing entirely.
    """
    try:
        saved = SavedAffirmation.objects.filter(
            user=request.user
        ).select_related('affirmation').order_by('-saved_at')
        return Response([{
            'id': s.affirmation.id,
            'message': s.affirmation.message,
            'emoji': s.affirmation.emoji,
            'category': s.affirmation.category,
            'saved_at': s.saved_at,
        } for s in saved])
    except Exception:
        # SavedAffirmation model may not exist yet — return empty list gracefully
        return Response([])


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def unsave_affirmation(request, affirmation_id):
    """
    Remove an affirmation from the user's saved list.
    DELETE /api/affirmations/{id}/unsave/
    Fix FE-09: was missing entirely.
    """
    try:
        SavedAffirmation.objects.filter(
            user=request.user,
            affirmation_id=affirmation_id
        ).delete()
    except Exception:
        pass
    return Response({'success': True})


# ==================== PRIVACY EXPORT & DELETE ACCOUNT (Fix FE-11) ====================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_user_data(request):
    """
    Queue a data export for the user.
    GET /api/privacy/export/
    Fix FE-11: endpoint was missing.
    TODO: implement actual export (email ZIP of all data).
    """
    return Response({
        'message': 'Your data export has been queued. You will receive an email within 24 hours.',
        'username': request.user.username,
        'email': request.user.email,
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_account(request):
    """
    Permanently delete the user's account and all associated data.
    DELETE /api/privacy/account/
    Fix FE-11: endpoint was missing.
    """
    user = request.user
    user.delete()
    return Response({'message': 'Account deleted.'}, status=status.HTTP_204_NO_CONTENT)


# ==================== WELLNESS BUDDY API ====================
 
class WellnessBuddyViewSet(viewsets.ViewSet):
    """
    Friend accountability system.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    @action(detail=False, methods=['get'])
    def my_buddies(self, request):
        """
        Get user's wellness buddies.
        
        GET /api/buddies/my_buddies/
        """
        buddies = WellnessBuddy.objects.filter(
            user=request.user,
            status='accepted'
        )
        
        buddies_data = []
        for buddy_connection in buddies:
            buddy_status = buddy_connection.get_buddy_status()
            
            buddies_data.append({
                'id': buddy_connection.id,
                'buddy': {
                    'id': buddy_connection.buddy.id,
                    'name': buddy_connection.buddy.get_full_name() or buddy_connection.buddy.username
                },
                'streak': buddy_status.get('current_streak'),
                'last_checkin': buddy_status.get('last_checkin'),
                'trend': buddy_status.get('trend'),
                'trend_emoji': buddy_status.get('trend_emoji'),
                'connected_since': buddy_connection.connected_at
            })
        
        return Response({
            'buddies': buddies_data,
            'total_count': len(buddies_data)
        })
    
    @action(detail=False, methods=['post'])
    def send_request(self, request):
        """
        Send buddy request.
        
        POST /api/buddies/send_request/
        Body: {
            "buddy_id": 123,
            "message": "Let's stay accountable together!"
        }
        """
        buddy_id = request.data.get('buddy_id')
        message = request.data.get('message', '')
        
        if buddy_id is None or buddy_id == '':
            return Response(
                {'error': 'buddy_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            buddy_id = int(buddy_id)
        except (TypeError, ValueError):
            return Response(
                {'error': 'buddy_id must be a valid user id'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            buddy_user = User.objects.get(id=buddy_id)
        except User.DoesNotExist:
            return Response({
                'error': 'User not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Check if request already exists
        existing = WellnessBuddy.objects.filter(
            Q(user=request.user, buddy=buddy_user) |
            Q(user=buddy_user, buddy=request.user)
        ).first()
        
        if existing:
            return Response({
                'error': 'Buddy connection already exists'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Create request
        buddy_request = WellnessBuddy.objects.create(
            user=request.user,
            buddy=buddy_user,
            status='pending'
        )
        
        # TODO: Send notification to buddy_user
        
        return Response({
            'message': f'Request sent to {buddy_user.get_full_name()}!',
            'request_id': buddy_request.id
        })
    
    @action(detail=True, methods=['post'])
    def accept_request(self, request, pk=None):
        """
        Accept buddy request.
        
        POST /api/buddies/{request_id}/accept_request/
        """
        try:
            buddy_request = WellnessBuddy.objects.get(
                id=pk,
                buddy=request.user,
                status='pending'
            )
        except WellnessBuddy.DoesNotExist:
            return Response({
                'error': 'Request not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        buddy_request.accept()
        
        return Response({
            'message': f'You\'re now wellness buddies with {buddy_request.user.get_full_name()}! 💙'
        })
    
    @action(detail=True, methods=['post'])
    def send_encouragement(self, request, pk=None):
        """
        Send encouragement to buddy.
        
        POST /api/buddies/{buddy_id}/send_encouragement/
        Body: {
            "message": "You got this! 💪"
        }
        """
        try:
            buddy_connection = WellnessBuddy.objects.get(
                id=pk,
                user=request.user,
                status='accepted'
            )
        except WellnessBuddy.DoesNotExist:
            return Response({
                'error': 'Buddy not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        message = request.data.get('message', '').strip()
        
        if not message:
            # Use pre-written message
            message = "Thinking of you! Keep up the great work 💙"
        
        # Create encouragement
        BuddyEncouragement.objects.create(
            sender=request.user,
            recipient=buddy_connection.buddy,
            message=message
        )
        
        # TODO: Send push notification
        
        return Response({
            'message': 'Encouragement sent! 💙'
        })

    @action(detail=False, methods=['get'])
    def list_requests(self, request):
        """GET /api/buddies/requests/ — pending requests sent to me."""
        pending = WellnessBuddy.objects.filter(buddy=request.user, status='pending')
        return Response({'requests': [
            {'id': r.id, 'from_user': {'id': r.user.id, 'username': r.user.username}, 'requested_at': r.connected_at}
            for r in pending
        ], 'total': pending.count()})

    @action(detail=True, methods=['post'])
    def decline_request(self, request, pk=None):
        """POST /api/buddies/requests/{id}/decline/"""
        try:
            req = WellnessBuddy.objects.get(id=pk, buddy=request.user, status='pending')
        except WellnessBuddy.DoesNotExist:
            return Response({'error': 'Request not found'}, status=status.HTTP_404_NOT_FOUND)
        req.status = 'declined'
        req.save()
        return Response({'message': 'Request declined.'})

    @action(detail=True, methods=['delete'])
    def remove_buddy(self, request, pk=None):
        """DELETE /api/buddies/{id}/"""
        try:
            conn = WellnessBuddy.objects.get(id=pk, status='accepted')
            if conn.user != request.user and conn.buddy != request.user:
                return Response({'error': 'Not your connection'}, status=status.HTTP_403_FORBIDDEN)
        except WellnessBuddy.DoesNotExist:
            return Response({'error': 'Buddy not found'}, status=status.HTTP_404_NOT_FOUND)
        conn.delete()
        return Response({'message': 'Buddy removed.'}, status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get'])
    def search(self, request):
        """GET /api/buddies/search/?q=username"""
        query = request.query_params.get('q', '').strip()
        if len(query) < 2:
            return Response({'error': 'Query must be at least 2 characters.'}, status=status.HTTP_400_BAD_REQUEST)
        users = User.objects.filter(username__icontains=query).exclude(id=request.user.id)[:10]
        existing_ids = set()
        for uid, bid in WellnessBuddy.objects.filter(
            Q(user=request.user) | Q(buddy=request.user)
        ).values_list('user_id', 'buddy_id'):
            existing_ids.update([uid, bid])
        return Response({'results': [
            {'id': u.id, 'username': u.username, 'name': u.get_full_name() or u.username, 'already_connected': u.id in existing_ids}
            for u in users
        ]})
# ==================== MISSING ENDPOINTS (FE-08, FE-09, FE-11, COMPAT-04) ====================
 
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_saved_affirmations(request):
    """
    FE-08: GET /api/affirmations/saved/
    Returns all affirmations saved/favourited by the authenticated user.
    """
    from .models import SavedAffirmation
    saved = SavedAffirmation.objects.filter(user=request.user).select_related('affirmation').order_by('-saved_at')
 
    results = []
    for sa in saved:
        aff = sa.affirmation
        results.append({
            'saved_id': sa.id,
            'affirmation_id': aff.id,
            'message': aff.message,
            'follow_up': aff.follow_up,
            'emoji': aff.emoji,
            'category': aff.category,
            'for_mood': aff.for_mood,
            'why_it_resonated': sa.why_it_resonated,
            'saved_at': sa.saved_at,
            'times_revisited': sa.times_revisited,
        })
 
    return Response({
        'count': len(results),
        'saved_affirmations': results
    })
 
 
@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def unsave_affirmation(request, affirmation_id):
    """
    FE-09: DELETE /api/affirmations/{id}/unsave/
    Removes an affirmation from the user's saved collection.
    """
    from .models import SavedAffirmation
    try:
        sa = SavedAffirmation.objects.get(affirmation_id=affirmation_id, user=request.user)
        sa.delete()
 
        # Decrement times_saved counter on the affirmation
        from .models import DailyAffirmation
        try:
            aff = DailyAffirmation.objects.get(id=affirmation_id)
            if aff.times_saved and aff.times_saved > 0:
                aff.times_saved -= 1
                aff.save(update_fields=['times_saved'])
        except DailyAffirmation.DoesNotExist:
            pass
 
        return Response({'message': 'Affirmation removed from saved.'}, status=status.HTTP_200_OK)
    except SavedAffirmation.DoesNotExist:
        return Response({'error': 'Affirmation not found in your saved list.'}, status=status.HTTP_404_NOT_FOUND)
 
 
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_user_data(request):
    """
    FE-11 (GET): GET /api/privacy/export/
    Exports all personal data for the authenticated user as a JSON payload
    (GDPR-style data portability).
    """
    from .models import MoodEntry, SleepLog, StudySession, JournalEntry, StressAssessmentResponse
 
    mood_data = list(
        MoodEntry.objects.filter(user=request.user).values(
            'id', 'timestamp', 'user_selected_mood', 'note',
            'sentiment_score', 'depression_level', 'anxiety_level', 'stress_level'
        )
    )
    sleep_data = list(
        SleepLog.objects.filter(user=request.user).values(
            'id', 'date', 'sleep_from', 'sleep_to', 'hours_slept', 'quality_tag', 'interruption_count'
        )
    )
    study_data = list(
        StudySession.objects.filter(user=request.user).values(
            'id', 'subject', 'start_time', 'end_time', 'duration_minutes'
        )
    )
    journal_data = list(
        JournalEntry.objects.filter(user=request.user).values(
            'id', 'title', 'content', 'mood_tag', 'written_at', 'word_count', 'is_favorite'
        )
    )
    assessment_data = list(
        StressAssessmentResponse.objects.filter(user=request.user).values(
            'id', 'session_date', 'overall_stress_score', 'primary_stressor', 'secondary_stressor'
        )
    )
 
    # Log the export action
    from .models import DataAccessLog
    DataAccessLog.objects.create(
        user=request.user,
        accessed_by=request.user,
        access_type='export',
        data_accessed='Full personal data export (mood, sleep, study, journal, assessments)',
        reason='User-initiated data export',
        ip_address=request.META.get('REMOTE_ADDR'),
    )
 
    return Response({
        'export_generated_at': timezone.now(),
        'username': request.user.username,
        'email': request.user.email,
        'mood_entries': mood_data,
        'sleep_logs': sleep_data,
        'study_sessions': study_data,
        'journal_entries': journal_data,
        'stress_assessments': assessment_data,
    })
 
 
@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_account(request):
    """
    FE-11 (DELETE): DELETE /api/privacy/account/
    Permanently deletes the authenticated user's account and all associated data.
    Requires confirmation body: {"confirm": "DELETE MY ACCOUNT"}
    """
    confirm = request.data.get('confirm', '')
    if confirm != 'DELETE MY ACCOUNT':
        return Response(
            {'error': 'Send {"confirm": "DELETE MY ACCOUNT"} to permanently delete your account.'},
            status=status.HTTP_400_BAD_REQUEST
        )
 
    user = request.user
    username = user.username
 
    # Log before deletion
    from .models import DataAccessLog
    DataAccessLog.objects.create(
        user=user,
        accessed_by=user,
        access_type='delete',
        data_accessed='Full account deletion',
        reason='User requested account deletion',
        ip_address=request.META.get('REMOTE_ADDR'),
    )
 
    # Delete the user (cascade deletes all related data via on_delete=CASCADE)
    user.delete()
 
    return Response({
        'message': f'Account for {username} has been permanently deleted. We are sorry to see you go.'
    }, status=status.HTTP_200_OK)
 
 
@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_trusted_contact(request, contact_id):
    """
    COMPAT-04: DELETE /api/crisis/contacts/{id}/
    Removes a trusted contact from the user's crisis contact list.
    """
    from .models import TrustedContact
    try:
        contact = TrustedContact.objects.get(id=contact_id, user=request.user)
        contact_name = contact.name
        contact.delete()
        return Response(
            {'message': f'Trusted contact "{contact_name}" has been removed.'},
            status=status.HTTP_200_OK
        )
    except TrustedContact.DoesNotExist:
        return Response(
            {'error': 'Trusted contact not found.'},
            status=status.HTTP_404_NOT_FOUND
        )
 