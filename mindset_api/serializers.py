from rest_framework import serializers
from .models import MoodEntry, SleepLog, StudySession, AcademicEvent, WellnessResource, StressCategory, StressAssessmentQuestion, StressAssessmentResponse, DASEducation, MoodBooster, DailyAffirmation
from django.contrib.auth.models import User
from .models import MicroCommitment
from .models import (
    CommunityPost, JournalEntry, WellnessBuddy, MoodPlaylist,
    DetectedPattern, PersonalInsight,
)


class UserRegistrationSerializer(serializers.ModelSerializer):
    """User registration serializer."""
    password = serializers.CharField(write_only=True, min_length=8)
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password']
    
    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password']
        )
        return user


class MoodEntrySerializer(serializers.ModelSerializer):
    """
    Mood Entry Serializer — Data Fusion.

    Frontend MUST send:
      user_selected_mood  — one of: SAD, ANX, STR, HAP, NEU
      note                — free-text description (optional but improves accuracy)

    Frontend must NOT send:
      sentiment_score, depression_level, anxiety_level, stress_level
      — all are calculated by the backend Data Fusion Engine.
    """
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = MoodEntry
        fields = [
            'id',
            'username',
            'timestamp',
            'user_selected_mood',   # writable — explicit student choice
            'note',
            'sentiment_score',
            'depression_level',
            'anxiety_level',
            'stress_level',
        ]
        read_only_fields = [
            'id',
            'username',
            'timestamp',
            'sentiment_score',
            'depression_level',
            'anxiety_level',
            'stress_level',
        ]


class SleepLogSerializer(serializers.ModelSerializer):
    """
    Sleep Log Serializer with Quality Tagging.
    
    Frontend should send:
    - date: "YYYY-MM-DD"
    - sleep_from: "HH:MM:SS" (e.g., "23:00:00" for 11 PM)
    - sleep_to: "HH:MM:SS" (e.g., "07:00:00" for 7 AM)
    - interruption_count: Integer (default 0)
    
    Backend auto-calculates:
    - hours_slept
    - quality_tag
    """
    username = serializers.CharField(source='user.username', read_only=True)
    duration_display = serializers.SerializerMethodField()
    
    class Meta:
        model = SleepLog
        fields = '__all__'
        extra_kwargs = {'user': {'required': False}}
        validators = [
            serializers.UniqueTogetherValidator(
                queryset=SleepLog.objects.all(),
                fields=['user', 'date'],
                message="A sleep log for this date already exists."
            )
        ]
        read_only_fields = ['id', 'username', 'hours_slept', 'quality_tag', 'created_at', 'updated_at']
    
    def get_duration_display(self, obj):
        """Return '6h 40m' format."""
        return obj.get_duration_display()
    
    def validate(self, data):
        """Validate sleep times if provided."""
        if data.get('sleep_from') and data.get('sleep_to'):
            # Both times must be present together
            pass
        elif data.get('sleep_from') or data.get('sleep_to'):
            raise serializers.ValidationError(
                "Both sleep_from and sleep_to must be provided together"
            )
        return data


class StudySessionSerializer(serializers.ModelSerializer):
    """
    Study Session Serializer.
    
    Frontend should send:
    - subject: String (e.g., "Mathematics")
    - start_time: ISO datetime (e.g., "2026-02-15T14:00:00Z")
    - end_time: ISO datetime (e.g., "2026-02-15T16:30:00Z")
    
    duration_minutes is auto-calculated.
    """
    username = serializers.CharField(source='user.username', read_only=True)
    
    class Meta:
        model = StudySession
        fields = [
            'id',
            'username',
            'subject',
            'start_time',
            'end_time',
            'duration_minutes',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'username', 'duration_minutes', 'created_at', 'updated_at']
    
    def validate(self, data):
        """Validate that end_time is after start_time."""
        if data.get('end_time') and data.get('start_time'):
            if data['end_time'] <= data['start_time']:
                raise serializers.ValidationError(
                    "End time must be after start time."
                )
        return data


class AcademicEventSerializer(serializers.ModelSerializer):
    """Academic Event Serializer."""
    is_active = serializers.SerializerMethodField()
    
    class Meta:
        model = AcademicEvent
        fields = [
            'id',
            'event_name',
            'start_date',
            'end_date',
            'description',
            'is_active',
            'created_at'
        ]
        read_only_fields = ['created_at']
    
    def get_is_active(self, obj):
        return obj.is_active_on()


class WellnessResourceSerializer(serializers.ModelSerializer):
    """
    Serializer for WellnessResource — the Samsung Health-style carousel card.

    The `tag_list` computed field exposes tags as a proper list so the
    frontend never needs to split a raw comma-separated string.

    Read-only for all API consumers; resources are managed via Django admin.
    """
    tag_list = serializers.SerializerMethodField()

    class Meta:
        model  = WellnessResource
        fields = [
            'id',
            'title',
            'category',
            'color',
            'action',
            'image_url',
            'content_link',
            'tag_list',
            'priority',
        ]
        read_only_fields = fields   # entire model is admin-managed

    def get_tag_list(self, obj):
        return obj.tag_list()
    
class MicroCommitmentSerializer(serializers.ModelSerializer):
    """Serializer for micro-commitments."""
    
    commitment_label = serializers.CharField(
        source='get_commitment_type_display',
        read_only=True
    )
    category_label = serializers.CharField(
        source='get_category_display',
        read_only=True
    )
    is_completed = serializers.BooleanField(read_only=True)
    time_to_complete = serializers.IntegerField(read_only=True, allow_null=True)
    display_text = serializers.CharField(read_only=True)
    
    class Meta:
        model = MicroCommitment
        fields = [
            'id',
            'user',
            'mood_entry',
            'commitment_type',
            'commitment_label',
            'commitment_text',
            'category',
            'category_label',
            'target_date',
            'display_text',
            'committed_at',
            'completed_at',
            'is_completed',
            'time_to_complete',
            'reminder_sent',
        ]
        read_only_fields = ['user', 'committed_at', 'completed_at', 'reminder_sent']
        extra_kwargs = {
            'mood_entry': {'required': False, 'allow_null': True},
            'commitment_type': {'required': False, 'allow_null': True},
            'commitment_text': {'required': False, 'allow_null': True},
            'category': {'required': False, 'allow_null': True},
            'target_date': {'required': False, 'allow_null': True},
        }


class StressCategorySerializer(serializers.ModelSerializer):
    """Serializer for StressCategory."""
    
    class Meta:
        model = StressCategory
        fields = [
            'id',
            'name',
            'category_type',
            'description',
            'emoji',
            'color',
            'why_it_happens',
            'common_signs',
            'coping_strategies',
            'is_active',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {
            'why_it_happens': {'required': False, 'allow_blank': True},
        }


class StressAssessmentQuestionSerializer(serializers.ModelSerializer):
    """Serializer for StressAssessmentQuestion."""
    
    class Meta:
        model = StressAssessmentQuestion
        fields = [
            'id',
            'category',
            'question_text',
            'order',
            'is_required',
            'weight',
            'is_active',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class StressAssessmentResponseSerializer(serializers.ModelSerializer):
    """Serializer for StressAssessmentResponse."""
    
    class Meta:
        model = StressAssessmentResponse
        fields = [
            'id',
            'user',
            'session_date',
            'responses',
            'category_scores',
            'overall_stress_score',
            'primary_stressor',
            'secondary_stressor',
            'found_helpful',
            'feedback_text'
        ]
        read_only_fields = ['id', 'user', 'session_date']
        extra_kwargs = {
            'responses': {'required': False, 'allow_null': True},
            'category_scores': {'required': False, 'allow_null': True},
            'overall_stress_score': {'required': False, 'allow_null': True},
            'primary_stressor': {'required': False, 'allow_null': True, 'allow_blank': True},
            'secondary_stressor': {'required': False, 'allow_null': True, 'allow_blank': True},
            'found_helpful': {'required': False, 'allow_null': True},
            'feedback_text': {'required': False, 'allow_null': True, 'allow_blank': True},
        }


class DASEducationSerializer(serializers.ModelSerializer):
    """Serializer for DASEducation."""
    
    class Meta:
        model = DASEducation
        fields = [
            'id',
            'das_type',
            'simple_explanation',
            'why_it_happens',
            'common_experiences',
            'physical_signs',
            'emotional_signs',
            'behavioral_signs',
            'validation_message',
            'helpful_strategies',
            'when_to_get_help',
            'common_myths',
            'emoji',
            'color',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class MoodBoosterSerializer(serializers.ModelSerializer):
    """Serializer for MoodBooster."""
    
    class Meta:
        model = MoodBooster
        fields = [
            'id',
            'title',
            'emoji',
            'booster_type',
            'mood_target',
            'description',
            'instructions',
            'why_it_works',
            'difficulty_level',
            'requires_privacy',
            'requires_materials',
            'materials_needed',
            'times_tried',
            'times_helped',
            'average_rating',
            'is_active',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {
            'why_it_works': {'required': False, 'allow_null': True, 'allow_blank': True},
            'materials_needed': {'required': False, 'allow_null': True, 'allow_blank': True},
        }


class DailyAffirmationSerializer(serializers.ModelSerializer):
    """Serializer for DailyAffirmation."""
    
    class Meta:
        model = DailyAffirmation
        fields = [
            'id',
            'category',
            'message',
            'follow_up',
            'emoji',
            'for_mood',
            'times_shown',
            'times_saved',
            'times_shared',
            'is_active',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {
            'follow_up': {'required': False, 'allow_null': True, 'allow_blank': True},
            'for_mood': {'required': False, 'allow_null': True, 'allow_blank': True},
            'times_shown': {'required': False, 'allow_null': True},
            'times_saved': {'required': False, 'allow_null': True},
            'times_shared': {'required': False, 'allow_null': True},
        }


class DetectedPatternSerializer(serializers.ModelSerializer):
    """Serializer for ML-detected patterns (read-only API)."""

    class Meta:
        model = DetectedPattern
        fields = [
            'id',
            'user',
            'pattern_type',
            'detected_at',
            'confidence',
            'metadata',
            'acknowledged',
            'acknowledged_at',
            'helpful',
            'is_active',
        ]
        read_only_fields = fields


class PersonalInsightSerializer(serializers.ModelSerializer):
    """Serializer for personalized insights (read-only API)."""

    class Meta:
        model = PersonalInsight
        fields = [
            'id',
            'user',
            'insight_type',
            'title',
            'message',
            'data_points',
            'generated_at',
            'for_week_starting',
            'viewed',
            'viewed_at',
            'helpful_rating',
            'priority',
        ]
        read_only_fields = fields


class CommunityPostSerializer(serializers.ModelSerializer):
    time_ago = serializers.ReadOnlyField(source='time_since_posted')
    category_display = serializers.ReadOnlyField(source='get_category_display')
    
    class Meta:
        model = CommunityPost
        fields = ['id', 'anonymous_id', 'category', 'category_display', 
                  'content', 'relate_count', 'reply_count', 'time_ago']

class JournalEntrySerializer(serializers.ModelSerializer):
    mood_display = serializers.ReadOnlyField(source='get_mood_tag_display')
    
    class Meta:
        model = JournalEntry
        fields = ['id', 'title', 'content', 'mood_tag', 'mood_display',
                  'word_count', 'written_at', 'is_favorite']
