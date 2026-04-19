from django.urls import path, include
from django.contrib import admin
from rest_framework.routers import DefaultRouter
from django.conf import settings
from django.conf.urls.static import static
from .views import (
    CommunityFeedViewSet,
    JournalingViewSet,
    RegisterView,
    LoginView,
    MoodEntryViewSet,
    SleepLogViewSet,
    StudySessionViewSet,
    WellnessBuddyViewSet,
    WellnessSummaryView,
    MindfulnessActionsView,
    SuperDuperWellnessSummaryView,
    StressAssessmentViewSet,
    MoodBoosterViewSet,
    get_all_das_education,
    get_das_education,  
    get_daily_affirmation,
    save_affirmation,
    get_crisis_resources,
    track_resource_click,
    press_sos_button,
    confirm_got_help,
    manage_trusted_contacts,
    run_crisis_check,
    get_privacy_statement,
    get_data_access_log,
    manage_privacy_settings,
    start_adaptive_quiz,
    answer_adaptive_question,
    get_category_selection_options,
    get_tiered_support,
    get_progress_dashboard,
)
from .views import MicroCommitmentViewSet, PatternViewSet, InsightsViewSet


# Create router for ViewSets
router = DefaultRouter()
router.register(r'mood-entries', MoodEntryViewSet, basename='mood-entry')
router.register(r'sleep-logs', SleepLogViewSet, basename='sleep-log')
router.register(r'study-sessions', StudySessionViewSet, basename='study-session')
router.register(r'micro-commitments', MicroCommitmentViewSet, basename='micro-commitment')
router.register(r'patterns', PatternViewSet, basename='pattern')
router.register(r'insights', InsightsViewSet, basename='insight')
router.register(r'stress-assessment', StressAssessmentViewSet, basename='stress-assessment')
router.register(r'mood-boosters', MoodBoosterViewSet, basename='mood-boosters')
router.register(r'community', CommunityFeedViewSet, basename='community')


urlpatterns = [
    # Authentication
    path('register/', RegisterView.as_view(), name='register'),
    path('token/', LoginView.as_view(), name='token'),
    
    # Wellness Dashboard
    path('wellness-summary/', WellnessSummaryView.as_view(), name='wellness-summary'),
    path('wellness-summary-super/', SuperDuperWellnessSummaryView.as_view()),
    
    # Mindfulness
    path('mindfulness-actions/', MindfulnessActionsView.as_view(), name='mindfulness-actions'),
    
    # Router URLs (mood-entries, sleep-logs, etc.)
    path('', include(router.urls)),

    # DAS Education (REMOVED api/ prefix)
    path('education/das/', get_all_das_education),
    path('education/das/<str:das_type>/', get_das_education),
    
    # Affirmations (REMOVED api/ prefix)
    path('affirmations/daily/', get_daily_affirmation),
    path('affirmations/<int:affirmation_id>/save/', save_affirmation),

    # Crisis Support (REMOVED api/ prefix)
    path('crisis/resources/', get_crisis_resources),
    path('crisis/resources/<int:resource_id>/click/', track_resource_click),
    path('crisis/sos/', press_sos_button),
    path('crisis/sos/<int:sos_id>/confirm-help/', confirm_got_help),
    path('crisis/trusted-contacts/', manage_trusted_contacts),
    path('crisis/check/', run_crisis_check),

    # Privacy (REMOVED api/ prefix)
    path('privacy/statement/', get_privacy_statement),
    path('privacy/access-log/', get_data_access_log),
    path('privacy/settings/', manage_privacy_settings),

    # Stress Assessment (REMOVED api/ prefix)
    path('stress-assessment/adaptive/start/', start_adaptive_quiz),
    path('stress-assessment/adaptive/<int:session_id>/answer/', answer_adaptive_question),
    path('stress-assessment/categories/select/', get_category_selection_options),

    # Support & Progress (REMOVED api/ prefix)
    path('support/tiered/', get_tiered_support),
    path('progress/dashboard/', get_progress_dashboard),

    # Journaling (REMOVED api/ prefix)
    path('journal/', include([
        path('daily_prompt/', JournalingViewSet.as_view({'get': 'daily_prompt'})),
        path('write/', JournalingViewSet.as_view({'post': 'write'})),
        path('entries/', JournalingViewSet.as_view({'get': 'entries'})),
        path('entries/<int:pk>/', JournalingViewSet.as_view({'get': 'entry_detail'})),
    ])),
    
    # Wellness Buddies (REMOVED api/ prefix)
    path('buddies/', include([
        path('my_buddies/', WellnessBuddyViewSet.as_view({'get': 'my_buddies'})),
        path('send_request/', WellnessBuddyViewSet.as_view({'post': 'send_request'})),
        path('<int:pk>/accept/', WellnessBuddyViewSet.as_view({'post': 'accept_request'})),
        path('<int:pk>/encourage/', WellnessBuddyViewSet.as_view({'post': 'send_encouragement'})),
    ])),
] 

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
# ==================== AVAILABLE ENDPOINTS ====================
# 
# Authentication:
# POST   /api/register/                  - Register new user
# POST   /api/token/                     - Login (get JWT tokens)
#
# Mood Entries:
# GET    /api/mood-entries/              - List all mood entries
# POST   /api/mood-entries/              - Create mood entry
# GET    /api/mood-entries/{id}/         - Get specific mood entry
# PUT    /api/mood-entries/{id}/         - Update mood entry
# PATCH  /api/mood-entries/{id}/         - Partial update
# DELETE /api/mood-entries/{id}/         - Delete mood entry
#
# Sleep Logs:
# GET    /api/sleep-logs/                - List all sleep logs
# POST   /api/sleep-logs/                - Create sleep log
# GET    /api/sleep-logs/{id}/           - Get specific sleep log
# PUT    /api/sleep-logs/{id}/           - Update sleep log
# PATCH  /api/sleep-logs/{id}/           - Partial update
# DELETE /api/sleep-logs/{id}/           - Delete sleep log
#
# Study Sessions:
# GET    /api/study-sessions/            - List all study sessions
# POST   /api/study-sessions/            - Create study session
# GET    /api/study-sessions/{id}/       - Get specific study session
# PUT    /api/study-sessions/{id}/       - Update study session
# PATCH  /api/study-sessions/{id}/       - Partial update
# DELETE /api/study-sessions/{id}/       - Delete study session
#
# Holistic Wellness Dashboard:
# GET    /api/wellness-summary/          - Get comprehensive 7-day wellness summary
#                                           (Main dashboard endpoint)
#
# Mindfulness Actions:
# GET    /api/mindfulness-actions/       - Ordered list of mindfulness activities
#                                           Order changes based on study load / exam schedule