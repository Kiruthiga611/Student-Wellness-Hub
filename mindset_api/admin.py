from django.contrib import admin
from .models import MoodEntry, SleepLog, StudySession, AcademicEvent, WellnessResource
from .models import (
    UserStats, UserPreferences, EnhancedMoodEntry,
    MicroCommitment, DetectedPattern, PersonalInsight,
    CrisisCheckpoint, CarePackage, CommunitySnapshot,
    DeletedMoodEntry
)
from django.utils.html import format_html
from django.utils import timezone

from .models import (
    StressCategory, StressAssessmentQuestion, StressAssessmentResponse,
    DASEducation, MoodBooster, MoodBoosterUsage,
    DailyAffirmation, SavedAffirmation, TeenMoodContext,
    MoodPlaylist,
    UserPlaylistHistory,
    JournalPrompt,
    JournalEntry,
    JournalStreak,
    CampusEvent,
    EventSurvivalPlan,
    NotificationPersonality,
    CrisisContactPriority,
    WellnessBuddy,
)

@admin.register(AcademicEvent)
class AcademicEventAdmin(admin.ModelAdmin):
    """Admin interface for Academic Events."""
    list_display = ['event_name', 'start_date', 'end_date', 'is_currently_active', 'created_at']
    list_filter = ['start_date', 'end_date']
    search_fields = ['event_name', 'description']
    ordering = ['-start_date']
    date_hierarchy = 'start_date'
    
    fieldsets = (
        ('Event Details', {
            'fields': ('event_name', 'description')
        }),
        ('Date Range', {
            'fields': ('start_date', 'end_date')
        }),
    )
    
    def is_currently_active(self, obj):
        return obj.is_active_on()
    is_currently_active.boolean = True
    is_currently_active.short_description = 'Active Now'


@admin.register(MoodEntry)
class MoodEntryAdmin(admin.ModelAdmin):
    """Admin interface for Mood Entries."""
    list_display = [
        'user',
        'timestamp',
        'sentiment_score',
        'depression_level',
        'anxiety_level',
        'stress_level'
    ]
    list_filter = [
        'depression_level',
        'anxiety_level',
        'stress_level',
        'timestamp'
    ]
    search_fields = ['user__username', 'note']
    ordering = ['-timestamp']
    date_hierarchy = 'timestamp'
    
    readonly_fields = [
        'sentiment_score',
        'depression_level',
        'anxiety_level',
        'stress_level',
        'timestamp'
    ]
    
    fieldsets = (
    ('User & Time', {
        'fields': ('user', 'timestamp')
    }),
    ('Student Input', {
        'fields': ('user_selected_mood', 'note'),
        'description': 'user_selected_mood: SAD, ANX, STR, HAP, or NEU'
    }),
    ('AI Analysis (Auto-Calculated)', {
        'fields': (
            'sentiment_score',
            'depression_level',
            'anxiety_level',
            'stress_level'
        ),
        'description': 'These fields are automatically calculated by the Data Fusion Engine'
    }),
)
    
    def has_add_permission(self, request):
        return True  # Entries should be created via API


@admin.register(SleepLog)
class SleepLogAdmin(admin.ModelAdmin):
    """Admin interface for Sleep Logs."""
    list_display = ['user', 'date', 'hours_slept', 'created_at' , 'quality_tag', 'interruption_count']
    list_filter = ['date', 'created_at']
    search_fields = ['user__username']
    ordering = ['-date']
    date_hierarchy = 'date'
    
    fieldsets = (
        ('User & Date', {
            'fields': ('user', 'date')
        }),
        ('Sleep Interval', {
            'fields': ('sleep_from', 'sleep_to', 'interruption_count'),
            'description': 'Enter the time you went to bed and woke up'
        }),
        ('Auto-Calculated Results', {
            'fields': ('hours_slept', 'quality_tag'),
            'description': 'These fields are automatically calculated based on sleep interval and interruptions'
        }),
    )
    
    # Make calculated fields read-only (grayed out)
    readonly_fields = ['hours_slept', 'quality_tag']
    def readable_duration(self, obj):
        return obj.get_duration_display()
    readable_duration.short_description = 'Duration'


@admin.register(StudySession)
class StudySessionAdmin(admin.ModelAdmin):
    """Admin interface for Study Sessions."""
    list_display = [
        'user',
        'subject',
        'start_time',
        'duration_minutes',
        'created_at'
    ]
    list_filter = ['subject', 'start_time']
    search_fields = ['user__username', 'subject']
    ordering = ['-start_time']
    date_hierarchy = 'start_time'
    
    readonly_fields = ['duration_minutes']
    
    fieldsets = (
        ('User & Subject', {
            'fields': ('user', 'subject')
        }),
        ('Time Range', {
            'fields': ('start_time', 'end_time', 'duration_minutes'),
            'description': 'duration_minutes is auto-calculated'
        }),
    )


@admin.register(WellnessResource)
class WellnessResourceAdmin(admin.ModelAdmin):
    """
    Admin interface for the Wellness Resource catalogue.

    This is the main content-management screen for the carousel.
    Admins add/edit cards here; the API automatically ranks and returns
    them based on each student's current wellness state.

    Tag guide (comma-separate multiple tags in one field):
      Stress/anxiety cards  →  tags: "breathing,stress"  or  "meditation,anxiety"
      Sleep hygiene cards   →  tags: "sleep,recovery"
      Focus/study cards     →  tags: "focus,study"
      Mood/journal cards    →  tags: "journal,mood"
    """
    list_display  = ['title', 'category', 'action', 'priority', 'is_active', 'updated_at']
    list_filter   = ['category', 'is_active']
    search_fields = ['title', 'tags', 'action']
    ordering      = ['priority', 'category']
    list_editable = ['priority', 'is_active']   # quick edits without opening each row

    fieldsets = (
        ('Card Content', {
            'fields': ('title', 'category', 'image_url', 'content_link'),
        }),
        ('Frontend Rendering', {
            'fields': ('color', 'action'),
            'description': (
                'color: hex string, e.g. #4A3728. '
                'action: token the app routes on, e.g. breathe, journal, sleep_tips, meditate, focus.'
            ),
        }),
        ('Recommendation Engine', {
            'fields': ('tags', 'priority', 'is_active'),
            'description': (
                'tags: comma-separated, e.g. "breathing,stress". '
                'priority: lower number = shown first. '
                'is_active: uncheck to hide from all API responses immediately.'
            ),
        }),
    )

# ==================== USER STATS ====================

@admin.register(UserStats)
class UserStatsAdmin(admin.ModelAdmin):
    """Track user engagement, streaks, and usage patterns."""
    
    list_display = [
        'user',
        'current_streak_display',
        'longest_streak',
        'total_checkins',
        'best_health_score',
        'last_checkin_date',
    ]
    list_filter = ['last_checkin_date', 'current_streak']
    search_fields = ['user__username', 'user__email']
    readonly_fields = [
        'current_streak',
        'longest_streak',
        'last_checkin_date',
        'total_checkins',
        'features_used_display',
        'created_at',
        'updated_at',
    ]
    
    fieldsets = (
        ('User', {
            'fields': ('user',)
        }),
        ('Streaks & Engagement', {
            'fields': (
                'current_streak',
                'longest_streak',
                'last_checkin_date',
                'total_checkins',
            )
        }),
        ('Feature Usage', {
            'fields': ('features_used_display',),
            'description': 'Which features this user engages with most'
        }),
        ('Personal Bests', {
            'fields': (
                'best_health_score',
                'best_health_score_date',
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def current_streak_display(self, obj):
        """Display streak with fire emoji."""
        if obj.current_streak >= 7:
            return format_html('🔥 <strong>{} days</strong>', obj.current_streak)
        return f"{obj.current_streak} days"
    current_streak_display.short_description = 'Current Streak'
    
    def features_used_display(self, obj):
        """Format features_used JSON nicely."""
        if not obj.features_used:
            return "No feature usage yet"
        
        items = []
        for feature, count in sorted(obj.features_used.items(), key=lambda x: x[1], reverse=True):
            items.append(f"{feature}: {count}")
        return ", ".join(items[:5])  # Top 5
    features_used_display.short_description = 'Feature Usage'


# ==================== USER PREFERENCES ====================

@admin.register(UserPreferences)
class UserPreferencesAdmin(admin.ModelAdmin):
    """Manage user notification settings and personalization."""
    
    list_display = [
        'user',
        'morning_checkin_enabled',
        'evening_checkin_enabled',
        'theme_preference',
        'crisis_resources_shown',
    ]
    list_filter = [
        'morning_checkin_enabled',
        'evening_checkin_enabled',
        'theme_preference',
        'crisis_resources_shown',
    ]
    search_fields = ['user__username']
    
    fieldsets = (
        ('User', {
            'fields': ('user',)
        }),
        ('Notification Preferences', {
            'fields': (
                'morning_checkin_enabled',
                'morning_checkin_time',
                'evening_checkin_enabled',
                'evening_checkin_time',
                'post_study_prompt',
            )
        }),
        ('Interface Customization', {
            'fields': (
                'theme_preference',
                'hidden_features',
                'favorite_resources',
            )
        }),
        ('Crisis Support', {
            'fields': (
                'crisis_resources_shown',
                'crisis_resources_last_shown',
            )
        }),
    )


# ==================== ENHANCED MOOD ENTRY ====================

@admin.register(EnhancedMoodEntry)
class EnhancedMoodEntryAdmin(admin.ModelAdmin):
    """Extended mood data with context-aware features."""
    
    list_display = [
        'user',
        'timestamp',
        'time_of_day',
        'mood_intensity',
        'energy_level',
        'day_rating',
    ]
    list_filter = ['time_of_day', 'day_rating', 'timestamp']
    search_fields = ['user__username', 'wins_today']
    readonly_fields = ['timestamp']
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('user', 'mood_entry', 'timestamp', 'time_of_day')
        }),
        ('Intensity Tracking', {
            'fields': ('mood_intensity', 'energy_level', 'day_rating')
        }),
        ('Daily Reflection', {
            'fields': ('wins_today', 'energy_drains', 'worries_today')
        }),
    )


# ==================== MICRO COMMITMENTS ====================

@admin.register(MicroCommitment)
class MicroCommitmentAdmin(admin.ModelAdmin):
    """Track tiny behavioral interventions."""
    
    list_display = [
        'user',
        'commitment_type_display',
        'committed_at',
        'completion_status',
        'time_to_complete_display',
        'quick_complete',
    ]
    list_filter = [
        'commitment_type',
        'completed_at',
        'committed_at',
    ]
    search_fields = ['user__username']
    readonly_fields = ['committed_at', 'time_to_complete_display', 'reminder_sent_at']
    actions = ['mark_as_completed']
    
    fieldsets = (
        ('Commitment Details', {
            'fields': (
                'user',
                'mood_entry',
                'commitment_type',
                'committed_at',
            )
        }),
        ('Completion', {
            'fields': (
                'completed_at',
                'time_to_complete_display',
            )
        }),
        ('Reminders', {
            'fields': (
                'reminder_sent',
                'reminder_sent_at',
            ),
            'classes': ('collapse',)
        }),
    )
    
    def commitment_type_display(self, obj):
        icons = {
            'breathing': '🫁',
            'water': '💧',
            'walk': '🚶',
            'friend': '👋',
            'stretch': '🤸',
            'gratitude': '🙏',
        }
        icon = icons.get(obj.commitment_type, '✓')
        return f"{icon} {obj.get_commitment_type_display()}"
    commitment_type_display.short_description = 'Commitment'
    
    def completion_status(self, obj):
        """Visual completion status."""
        if obj.is_completed:
            # FIXED: Added the string as the second argument to satisfy format_html
            return format_html('✅ <strong>{}</strong>', "Completed")
        return format_html('⏳ {}', "Pending")
    completion_status.short_description = 'Status'
    
    def time_to_complete_display(self, obj):
        if obj.time_to_complete:
            return f"{obj.time_to_complete} minutes"
        return "-"
    time_to_complete_display.short_description = 'Time Taken'

    def quick_complete(self, obj):
        """Quick complete button in list view."""
        if obj.is_completed:
            return "✅ Done"
        
        # FIXED: Structured the JS template to properly receive the ID via format_html
        return format_html(
            '<a class="button" href="#" onclick="'
            'if(confirm(\'Mark as completed?\')) {{'
            '  fetch(\'/api/micro-commitments/{}/complete/\', {{'
            '    method: \'POST\','
            '    headers: {{'
            '        \'X-CSRFToken\': document.querySelector(\'[name=csrfmiddlewaretoken]\').value,'
            '        \'Content-Type\': \'application/json\''
            '    }}'
            '  }}).then(res => {{ if(res.ok) location.reload(); else alert(\'Error completing\'); }});'
            '}} return false;">Complete</a>',
            obj.id
        )
    quick_complete.short_description = 'Quick Action'
    
    def mark_as_completed(self, request, queryset):
        from django.utils import timezone
        count = queryset.filter(completed_at__isnull=True).update(completed_at=timezone.now())
        self.message_user(request, f'{count} commitment(s) marked as completed! 🎉')
    mark_as_completed.short_description = 'Mark selected as completed'


# ==================== BUDDY REQUESTS (WellnessBuddy) ====================

class PendingBuddyRequestFilter(admin.SimpleListFilter):
    """Sidebar shortcut to list only requests awaiting a response."""

    title = 'pending requests'
    parameter_name = 'pending_buddy_requests'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Pending only'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(status='pending')
        return queryset


@admin.register(WellnessBuddy)
class WellnessBuddyAdmin(admin.ModelAdmin):
    """
    Buddy connection requests: sender (`user`) → receiver (`buddy`).
    """

    list_display = [
        'sender_display',
        'receiver_display',
        'status',
        'requested_at',
    ]
    list_filter = [
        PendingBuddyRequestFilter,
        'status',
    ]
    search_fields = [
        'user__username',
        'buddy__username',
        'user__email',
        'buddy__email',
        'user__first_name',
        'user__last_name',
        'buddy__first_name',
        'buddy__last_name',
    ]
    ordering = ['-requested_at']
    readonly_fields = ['requested_at', 'connected_at']
    raw_id_fields = ['user', 'buddy']

    fieldsets = (
        ('Request', {
            'fields': ('user', 'buddy', 'status', 'requested_at', 'connected_at'),
        }),
        ('Sharing preferences', {
            'fields': (
                'share_streak',
                'share_mood_trend',
                'share_last_checkin',
            ),
        }),
        ('Notifications', {
            'fields': ('notify_on_checkin', 'notify_if_missed'),
        }),
    )

    @admin.display(description='Sender', ordering='user__username')
    def sender_display(self, obj):
        u = obj.user
        name = (u.get_full_name() or '').strip()
        if name:
            return f'{name} ({u.get_username()})'
        return u.get_username()

    @admin.display(description='Receiver', ordering='buddy__username')
    def receiver_display(self, obj):
        u = obj.buddy
        name = (u.get_full_name() or '').strip()
        if name:
            return f'{name} ({u.get_username()})'
        return u.get_username()


# ==================== DETECTED PATTERNS ====================

@admin.register(DetectedPattern)
class DetectedPatternAdmin(admin.ModelAdmin):
    """ML-detected behavioral patterns."""
    
    list_display = [
        'user',
        'pattern_type',
        'confidence_display',
        'detected_at',
        'acknowledged',
        'helpful_display',
        'is_active',
    ]
    list_filter = [
        'pattern_type',
        'is_active',
        'acknowledged',
        'helpful',
        'detected_at',
    ]
    search_fields = ['user__username', 'metadata']
    readonly_fields = ['detected_at', 'acknowledged_at']
    
    fieldsets = (
        ('Pattern Details', {
            'fields': (
                'user',
                'pattern_type',
                'confidence',
                'detected_at',
            )
        }),
        ('Pattern Data', {
            'fields': ('metadata',),
            'description': 'JSON data describing the pattern (day, time, triggers, etc.)'
        }),
        ('User Interaction', {
            'fields': (
                'acknowledged',
                'acknowledged_at',
                'helpful',
                'is_active',
            )
        }),
    )
    
    def confidence_display(self, obj):
        """Show confidence as percentage."""
        percentage = int(obj.confidence * 100)
        if percentage >= 80:
            color = 'green'
        elif percentage >= 60:
            color = 'orange'
        else:
            color = 'red'
        return format_html(
            '<span style="color: {};">{}%</span>',
            color, percentage
        )
    confidence_display.short_description = 'Confidence'
    
    def helpful_display(self, obj):
        """Visual helpful indicator."""
        if obj.helpful is None:
            return "-"
        return "👍" if obj.helpful else "👎"
    helpful_display.short_description = 'Helpful?'


# ==================== PERSONAL INSIGHTS ====================

@admin.register(PersonalInsight)
class PersonalInsightAdmin(admin.ModelAdmin):
    """Weekly personalized insights."""
    
    list_display = [
        'user',
        'title',
        'insight_type',
        'priority_display',
        'generated_at',
        'viewed',
        'helpful_rating',
    ]
    list_filter = [
        'insight_type',
        'priority',
        'viewed',
        'helpful_rating',
        'generated_at',
    ]
    search_fields = ['user__username', 'title', 'message']
    readonly_fields = ['generated_at', 'viewed_at']
    
    fieldsets = (
        ('Insight Details', {
            'fields': (
                'user',
                'insight_type',
                'title',
                'message',
                'priority',
            )
        }),
        ('Supporting Data', {
            'fields': ('data_points', 'for_week_starting'),
            'description': 'Data that backs up this insight'
        }),
        ('User Engagement', {
            'fields': (
                'viewed',
                'viewed_at',
                'helpful_rating',
            )
        }),
        ('Metadata', {
            'fields': ('generated_at',),
            'classes': ('collapse',)
        }),
    )
    
    def priority_display(self, obj):
        """Visual priority indicator."""
        stars = '⭐' * (6 - obj.priority)  # 1=highest gets 5 stars
        return stars
    priority_display.short_description = 'Priority'


# ==================== CRISIS CHECKPOINTS ====================

@admin.register(CrisisCheckpoint)
class CrisisCheckpointAdmin(admin.ModelAdmin):
    """⚠️ Critical: Crisis detection logs for safety."""
    
    list_display = [
        'user',
        'severity_display',
        'detected_at',
        'resources_viewed',
        'user_contacted_resource',
    ]
    list_filter = [
        'severity',
        'resources_viewed',
        'user_contacted_resource',
        'detected_at',
    ]
    search_fields = ['user__username', 'indicators']
    readonly_fields = [
        'detected_at',
        'resources_viewed_at',
        'indicators_display',
        'resources_shown_display',
    ]
    
    fieldsets = (
        ('⚠️ Crisis Details', {
            'fields': (
                'user',
                'severity',
                'detected_at',
            ),
            'classes': ('wide',)
        }),
        ('Detection Indicators', {
            'fields': ('indicators_display',),
            'description': '⚠️ What triggered the crisis detection'
        }),
        ('Resources Provided', {
            'fields': ('resources_shown_display',)
        }),
        ('User Response', {
            'fields': (
                'resources_viewed',
                'resources_viewed_at',
                'user_dismissed',
                'user_contacted_resource',
            )
        }),
        ('Follow-Up', {
            'fields': (
                'follow_up_scheduled',
                'follow_up_at',
            )
        }),
    )
    
    def severity_display(self, obj):
        """Color-coded severity."""
        colors = {
            'low': 'blue',
            'medium': 'orange',
            'high': 'red',
            'critical': 'darkred',
        }
        return format_html(
            '<strong style="color: {};">{}</strong>',
            colors.get(obj.severity, 'black'),
            obj.severity.upper()
        )
    severity_display.short_description = 'Severity'
    
    def indicators_display(self, obj):
        """Format indicators nicely."""
        if not obj.indicators:
            return "No indicators"
        return ", ".join(obj.indicators)
    indicators_display.short_description = 'Indicators'
    
    def resources_shown_display(self, obj):
        """Format resources list."""
        if not obj.resources_shown:
            return "No resources shown"
        
        items = []
        for resource in obj.resources_shown:
            if isinstance(resource, dict):
                items.append(resource.get('name', 'Unknown'))
            else:
                items.append(str(resource))
        return ", ".join(items)
    resources_shown_display.short_description = 'Resources Shown'


# ==================== CARE PACKAGES ====================

@admin.register(CarePackage)
class CarePackageAdmin(admin.ModelAdmin):
    """Pre-exam support bundles."""
    
    list_display = [
        'user',
        'academic_event',
        'event_starts_at',
        'activated_at',
        'viewed',
        'helpful_display',
    ]
    list_filter = [
        'viewed',
        'helpful',
        'activated_at',
        'event_starts_at',
    ]
    search_fields = ['user__username', 'academic_event__event_name']
    readonly_fields = ['activated_at', 'viewed_at']
    
    fieldsets = (
        ('Package Info', {
            'fields': (
                'user',
                'academic_event',
                'event_starts_at',
                'activated_at',
            )
        }),
        ('Package Contents', {
            'fields': (
                'resources_included',
                'tips',
            )
        }),
        ('Adjustments Made', {
            'fields': (
                'sleep_goal_adjusted',
                'new_sleep_goal',
            )
        }),
        ('User Engagement', {
            'fields': (
                'viewed',
                'viewed_at',
                'helpful',
            )
        }),
    )
    
    def helpful_display(self, obj):
        """Visual helpful indicator."""
        if obj.helpful is None:
            return "-"
        return "👍" if obj.helpful else "👎"
    helpful_display.short_description = 'Helpful?'


# ==================== COMMUNITY SNAPSHOTS ====================

@admin.register(CommunitySnapshot)
class CommunitySnapshotAdmin(admin.ModelAdmin):
    """Daily anonymous community statistics."""
    
    list_display = [
        'snapshot_date',
        'active_users_count',
        'total_mood_entries',
        'avg_health_score',
        'avg_anxiety_level_display',
        'breathing_exercises_count',
    ]
    list_filter = ['snapshot_date', 'generated_at']
    readonly_fields = ['generated_at']
    date_hierarchy = 'snapshot_date'
    
    fieldsets = (
        ('Snapshot Info', {
            'fields': ('snapshot_date', 'generated_at')
        }),
        ('Activity Stats', {
            'fields': (
                'active_users_count',
                'total_mood_entries',
                'breathing_exercises_count',
            )
        }),
        ('Aggregate Wellness', {
            'fields': (
                'avg_health_score',
                'avg_anxiety_level',
                'avg_stress_level',
                'avg_sleep_hours',
            )
        }),
        ('Context', {
            'fields': (
                'active_events',
                'most_used_resource_id',
            )
        }),
    )
    
    def avg_anxiety_level_display(self, obj):
        """Visual anxiety level."""
        if not obj.avg_anxiety_level:
            return "-"
        
        level = obj.avg_anxiety_level
        if level < 1.5:
            color = 'green'
            emoji = '😌'
        elif level < 2.5:
            color = 'orange'
            emoji = '😐'
        else:
            color = 'red'
            emoji = '😰'
        
        return format_html(
            '{} <span style="color: {};">{}</span>',
            emoji, color, round(level, 2)
        )
    avg_anxiety_level_display.short_description = 'Avg Anxiety'


# ==================== DELETED MOOD ENTRIES ====================

@admin.register(DeletedMoodEntry)
class DeletedMoodEntryAdmin(admin.ModelAdmin):
    """Soft-deleted entries with 30-day undo window."""
    
    list_display = [
        'original_id',
        'user',
        'deleted_at',
        'deleted_by_user',
        'restored',
        'days_until_permanent',
    ]
    list_filter = [
        'deleted_by_user',
        'restored',
        'deleted_at',
    ]
    search_fields = ['user__username', 'original_id']
    readonly_fields = [
        'original_id',
        'original_data',
        'deleted_at',
        'restored_at',
        'permanent_delete_at',
    ]
    
    fieldsets = (
        ('Entry Info', {
            'fields': (
                'original_id',
                'user',
            )
        }),
        ('Original Data', {
            'fields': ('original_data',),
            'description': 'JSON snapshot of the deleted entry'
        }),
        ('Deletion Info', {
            'fields': (
                'deleted_at',
                'deleted_by_user',
                'permanent_delete_at',
            )
        }),
        ('Restoration', {
            'fields': (
                'restored',
                'restored_at',
            )
        }),
    )
    
    def days_until_permanent(self, obj):
        """Show days remaining before permanent deletion."""
        if obj.restored:
            return "Restored ✅"
        
        from django.utils import timezone
        days_left = (obj.permanent_delete_at - timezone.now()).days
        
        if days_left <= 0:
            return format_html('<span style="color: red;">Expired</span>')
        elif days_left <= 7:
            return format_html(
                '<span style="color: orange;">{} days left</span>',
                days_left
            )
        else:
            return f"{days_left} days left"
    days_until_permanent.short_description = 'Time Remaining'

@admin.register(StressCategory)
class StressCategoryAdmin(admin.ModelAdmin):
    """Manage teen stress categories."""
    
    list_display = [
        'emoji_display',
        'name',
        'category_type',
        'question_count',
        'is_active'
    ]
    list_filter = ['is_active', 'category_type']
    search_fields = ['name', 'description']
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('name', 'category_type', 'description', 'emoji', 'color')
        }),
        ('Educational Content', {
            'fields': ('why_it_happens', 'common_signs', 'coping_strategies')
        }),
        ('Settings', {
            'fields': ('is_active',)
        })
    )
    
    def emoji_display(self, obj):
        return f"{obj.emoji} {obj.name}"
    emoji_display.short_description = 'Category'
    
    def question_count(self, obj):
        count = obj.questions.count()
        return f"{count} questions"
    question_count.short_description = 'Questions'
 
 
@admin.register(StressAssessmentQuestion)
class StressAssessmentQuestionAdmin(admin.ModelAdmin):
    """Manage quiz questions."""
    
    list_display = [
        'category',
        'question_preview',
        'order',
        'weight',
        'is_required',
        'is_active'
    ]
    list_filter = ['category', 'is_required', 'is_active']
    search_fields = ['question_text']
    list_editable = ['order', 'weight', 'is_required']
    
    fieldsets = (
        ('Question', {
            'fields': ('category', 'question_text')
        }),
        ('Settings', {
            'fields': ('order', 'weight', 'is_required', 'is_active')
        })
    )
    
    def question_preview(self, obj):
        return obj.question_text[:60] + "..." if len(obj.question_text) > 60 else obj.question_text
    question_preview.short_description = 'Question'
 
 
@admin.register(StressAssessmentResponse)
class StressAssessmentResponseAdmin(admin.ModelAdmin):
    """View stress assessment results."""
    
    list_display = [
        'user',
        'session_date',
        'overall_stress_display',
        'stress_level_label',
        'primary_stressor_display',
        'found_helpful'
    ]
    
    # Removed category_scores as it can crash the sidebar filters
    list_filter = ['session_date', 'primary_stressor', 'found_helpful']
    search_fields = ['user__username']
    readonly_fields = ['session_date' , 'responses']

    def overall_stress_display(self, obj):
        # 1. Safe score retrieval
        try:
            score = float(obj.overall_stress_score) if obj.overall_stress_score is not None else 0.0
        except (ValueError, TypeError):
            score = 0.0
        
        # 2. Logic for color
        if score < 20:
            color = 'green'
        elif score < 40:
            color = 'blue'
        elif score < 60:
            color = 'orange'
        else:
            color = 'red'
            
        # 3. SAFE FORMATTING: We removed the {:.1f} which was causing the 'f' error
        # Instead, we round it in Python first.
        rounded_score = round(score, 1)
        return format_html(
            '<strong style="color: {};">{}%</strong>',
            color,
            rounded_score
        )
    overall_stress_display.short_description = 'Overall Stress'
    
    def stress_level_label(self, obj):
        # Added a fallback to prevent crashes if the model method fails
        try:
            return obj.get_stress_level_label()
        except:
            return "N/A"
    stress_level_label.short_description = 'Level'
    
    def primary_stressor_display(self, obj):
        if not obj.primary_stressor:
            return "None"
        try:
            # Using simple string concatenation to avoid format_html issues here
            from .models import StressCategory
            cat = StressCategory.objects.get(category_type=obj.primary_stressor)
            return f"{cat.emoji} {cat.name}"
        except:
            return str(obj.primary_stressor)
    primary_stressor_display.short_description = 'Top Stressor'


@admin.register(DASEducation)
class DASEducationAdmin(admin.ModelAdmin):
    """Manage DAS educational content."""
    
    list_display = [
        'emoji_display',
        'das_type',
        'updated_at'
    ]
    list_filter = ['das_type']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('das_type', 'emoji', 'color')
        }),
        ('What Is It?', {
            'fields': ('simple_explanation', 'why_it_happens')
        }),
        ('Symptoms', {
            'fields': (
                'common_experiences',
                'physical_signs',
                'emotional_signs',
                'behavioral_signs'
            )
        }),
        ('Support', {
            'fields': (
                'validation_message',
                'helpful_strategies',
                'when_to_get_help'
            )
        }),
        ('Myth Busting', {
            'fields': ('common_myths',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def emoji_display(self, obj):
        return f"{obj.emoji} {obj.get_das_type_display()}"
    emoji_display.short_description = 'Topic'
 
 
@admin.register(MoodBooster)
class MoodBoosterAdmin(admin.ModelAdmin):
    """Manage mood boosting activities."""
    
    list_display = [
        'emoji_display',
        'title',
        'booster_type',
        'mood_target',
        'difficulty_level',
        'success_rate_display',
        'is_active'
    ]
    list_filter = ['booster_type', 'mood_target', 'difficulty_level', 'is_active']
    search_fields = ['title', 'description']
    list_editable = ['is_active']
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('title', 'emoji', 'booster_type', 'mood_target')
        }),
        ('Content', {
            'fields': ('description', 'instructions', 'why_it_works')
        }),
        ('Requirements', {
            'fields': (
                'difficulty_level',
                'requires_privacy',
                'requires_materials',
                'materials_needed'
            )
        }),
        ('Effectiveness', {
            'fields': ('times_tried', 'times_helped', 'average_rating'),
            'classes': ('collapse',)
        }),
        ('Settings', {
            'fields': ('is_active',)
        })
    )
    readonly_fields = ['times_tried', 'times_helped', 'average_rating']
    
    def emoji_display(self, obj):
        return f"{obj.emoji} {obj.title}"
    emoji_display.short_description = 'Activity'
    
    def success_rate_display(self, obj):
        rate = obj.success_rate
        if obj.times_tried == 0:
            return "No data yet"
        
        if rate >= 70:
            color = 'green'
        elif rate >= 50:
            color = 'orange'
        else:
            color = 'red'
        
        pct = round(float(rate), 1)
        return format_html(
            '<span style="color: {};">{}%</span> ({}/{})',
            color, pct, obj.times_helped, obj.times_tried
        )
    success_rate_display.short_description = 'Success Rate'
 
 
@admin.register(MoodBoosterUsage)
class MoodBoosterUsageAdmin(admin.ModelAdmin):
    """Track mood booster usage."""
    
    list_display = [
        'user',
        'booster',
        'tried_at',
        'mood_improvement_display',
        'did_it_help',
        'rating_display'
    ]
    list_filter = ['tried_at', 'did_it_help', 'rating']
    search_fields = ['user__username', 'booster__title']
    readonly_fields = ['tried_at']
    
    def mood_improvement_display(self, obj):
        if obj.mood_improvement is None:
            return "-"
        
        improvement = obj.mood_improvement
        if improvement > 0:
            return format_html(
                '<span style="color: green;">+{} ⬆️</span>',
                improvement
            )
        elif improvement < 0:
            return format_html(
                '<span style="color: red;">{} ⬇️</span>',
                improvement
            )
        else:
            return format_html('<span style="color: gray;">0 →</span>')
    mood_improvement_display.short_description = 'Mood Change'
    
    def rating_display(self, obj):
        if obj.rating:
            stars = '⭐' * obj.rating
            return stars
        return "-"
    rating_display.short_description = 'Rating'
 
 
@admin.register(DailyAffirmation)
class DailyAffirmationAdmin(admin.ModelAdmin):
    """Manage daily affirmations."""
    
    list_display = [
        'emoji_display',
        'message_preview',
        'category',
        'for_mood',
        'engagement_display',
        'is_active'
    ]
    list_filter = ['category', 'for_mood', 'is_active']
    search_fields = ['message']
    list_editable = ['is_active']
    
    fieldsets = (
        ('Affirmation', {
            'fields': ('message', 'follow_up', 'emoji')
        }),
        ('Targeting', {
            'fields': ('category', 'for_mood')
        }),
        ('Stats', {
            'fields': ('times_shown', 'times_saved', 'times_shared'),
            'classes': ('collapse',)
        }),
        ('Settings', {
            'fields': ('is_active',)
        })
    )
    readonly_fields = ['times_shown', 'times_saved', 'times_shared']
    
    def emoji_display(self, obj):
        return obj.emoji
    emoji_display.short_description = ''
    
    def message_preview(self, obj):
        return obj.message[:60] + "..." if len(obj.message) > 60 else obj.message
    message_preview.short_description = 'Message'
    
    def engagement_display(self, obj):
        if obj.times_shown == 0:
            return "Not shown yet"
        
        save_rate = (obj.times_saved / obj.times_shown * 100) if obj.times_shown > 0 else 0
        save_pct = round(float(save_rate), 1)
        return format_html(
            'Shown: {} | Saved: {} ({}%)',
            obj.times_shown, obj.times_saved, save_pct
        )
    engagement_display.short_description = 'Engagement'
 
 
@admin.register(SavedAffirmation)
class SavedAffirmationAdmin(admin.ModelAdmin):
    """View saved affirmations."""
    
    list_display = [
        'user',
        'affirmation_preview',
        'saved_at',
        'times_revisited',
        'last_viewed'
    ]
    list_filter = ['saved_at']
    search_fields = ['user__username', 'affirmation__message']
    readonly_fields = ['saved_at', 'last_viewed']
    
    def affirmation_preview(self, obj):
        return f"{obj.affirmation.emoji} {obj.affirmation.message[:50]}..."
    affirmation_preview.short_description = 'Affirmation'
 
 
@admin.register(TeenMoodContext)
class TeenMoodContextAdmin(admin.ModelAdmin):
    """View teen mood context data."""
    
    list_display = [
        'mood_entry',
        'primary_trigger',
        'social_interaction_quality',
        'felt_supported',
        'felt_lonely'
    ]
    list_filter = [
        'felt_supported',
        'felt_lonely',
        'social_media_mood_impact',
        'tried_coping_strategy'
    ]
    search_fields = ['mood_entry__user__username', 'primary_trigger', 'mood_entry']
  
 
# ==================== MOOD PLAYLISTS ====================

@admin.register(MoodPlaylist)
class MoodPlaylistAdmin(admin.ModelAdmin):
    list_display = [
        'name', 
        'mood', 
        'genre', 
        'energy_level', 
        'play_count',
        'is_active'
    ]
    
    list_filter = ['mood', 'energy_level', 'is_active', 'genre']
    
    search_fields = ['name', 'description']
    
    readonly_fields = ['play_count', 'created_by']
    
    fieldsets = (
        ('Playlist Info', {
            'fields': ('name', 'description', 'mood')
        }),
        ('Links', {
            'fields': ('spotify_url', 'spotify_playlist_id', 'apple_music_url', 'youtube_music_url')
        }),
        ('Metadata', {
            'fields': ('genre', 'energy_level', 'play_count', 'is_active', 'created_by')
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('created_by')


@admin.register(UserPlaylistHistory)
class UserPlaylistHistoryAdmin(admin.ModelAdmin):
    list_display = ['user', 'playlist', 'mood_when_played', 'played_at', 'helped']
    list_filter = ['mood_when_played', 'helped', 'played_at']
    search_fields = ['user__username', 'playlist__name']
    readonly_fields = ['played_at']


# ==================== JOURNAL ====================

@admin.register(JournalPrompt)
class JournalPromptAdmin(admin.ModelAdmin):
    list_display = [
        'prompt_text_preview',
        'category',
        'difficulty',
        'is_active',
        'created_at'
    ]
    
    list_filter = ['category', 'difficulty', 'is_active']
    
    search_fields = ['prompt_text', 'alternate_text_1', 'alternate_text_2']
    
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Main Prompt', {
            'fields': ('category', 'prompt_text', 'difficulty')
        }),
        ('Alternates', {
            'fields': ('alternate_text_1', 'alternate_text_2'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_active', 'created_at')
        }),
    )
    
    def prompt_text_preview(self, obj):
        """Show first 60 characters of prompt"""
        return obj.prompt_text[:60] + '...' if len(obj.prompt_text) > 60 else obj.prompt_text
    
    prompt_text_preview.short_description = 'Prompt'


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = [
        'user',
        'title_or_date',
        'entry_type',
        'mood_tag',
        'word_count',
        'written_at',
        'is_favorite'
    ]
    
    list_filter = ['entry_type', 'mood_tag', 'is_favorite', 'written_at']
    
    search_fields = ['user__username', 'title', 'content']
    
    readonly_fields = ['written_at', 'updated_at', 'word_count']
    
    fieldsets = (
        ('Entry Info', {
            'fields': ('user', 'entry_type', 'prompt', 'title')
        }),
        ('Content', {
            'fields': ('content', 'mood_tag')
        }),
        
        ('Metadata', {
            'fields': ('word_count', 'is_favorite', 'written_at', 'updated_at')
        }),
    )
    
    def title_or_date(self, obj):
        """Show title or date if no title"""
        return obj.title if obj.title else f"Entry from {obj.written_at.strftime('%b %d, %Y')}"
    
    title_or_date.short_description = 'Title'
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('user', 'prompt')


@admin.register(JournalStreak)
class JournalStreakAdmin(admin.ModelAdmin):
    list_display = [
        'user',
        'current_streak',
        'longest_streak',
        'total_entries',
        'last_entry_date'
    ]
    
    readonly_fields = [
        'current_streak',
        'longest_streak',
        'total_entries',
        'last_entry_date'
    ]
    
    search_fields = ['user__username']


# ==================== CAMPUS EVENTS ====================

@admin.register(CampusEvent)
class CampusEventAdmin(admin.ModelAdmin):
    list_display = [
        'title',
        'event_type',
        'start_date',
        'end_date',
        'typical_stress_level',
        'is_campus_wide',
        'days_until_start'
    ]
    
    list_filter = [
        'event_type',
        'typical_stress_level',
        'is_campus_wide',
        'start_date'
    ]
    
    search_fields = ['title', 'description']
    
    fieldsets = (
        ('Event Details', {
            'fields': ('event_type', 'title', 'description')
        }),
        ('Dates', {
            'fields': ('start_date', 'end_date')
        }),
        ('Scope', {
            'fields': ('is_campus_wide', 'user', 'typical_stress_level')
        }),
        ('Support', {
            'fields': ('pre_event_support', 'during_event_support')
        }),
    )
    
    def days_until_start(self, obj):
        """Show days until event"""
        days = obj.days_until
        if days < 0:
            return f"{abs(days)} days ago"
        elif days == 0:
            return "Today!"
        else:
            return f"In {days} days"
    
    days_until_start.short_description = 'Timing'


@admin.register(EventSurvivalPlan)
class EventSurvivalPlanAdmin(admin.ModelAdmin):
    list_display = ['user', 'event', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'event__title']
    readonly_fields = ['created_at']


# ==================== NOTIFICATIONS ====================

@admin.register(NotificationPersonality)
class NotificationPersonalityAdmin(admin.ModelAdmin):
    list_display = ['user', 'personality_type']
    list_filter = ['personality_type']
    search_fields = ['user__username']


@admin.register(CrisisContactPriority)
class CrisisContactPriorityAdmin(admin.ModelAdmin):
    list_display = [
        'user',
        'contact_name',
        'contact_type',
        'priority',
        'is_active'
    ]
    
    list_filter = ['contact_type', 'is_active', 'priority']
    search_fields = ['user__username', 'contact_name']
    
    ordering = ['user', 'priority']





# ── Site branding ────────────────────────────────────────────────────────────
admin.site.site_header = "Student Wellness Hub Administration"
admin.site.site_title = "Wellness Hub Admin"
admin.site.index_title = "Wellness Management Dashboard"