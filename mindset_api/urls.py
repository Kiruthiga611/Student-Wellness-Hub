from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from django.conf import settings
from django.conf.urls.static import static

from .views import (
    # Auth & Profile
    RegisterView,
    LoginView,

    # ViewSets
    CommunityFeedViewSet,
    JournalingViewSet,
    MoodEntryViewSet,
    SleepLogViewSet,
    StudySessionViewSet,
    WellnessBuddyViewSet,
    MicroCommitmentViewSet,
    PatternViewSet,
    InsightsViewSet,
    StressAssessmentViewSet,
    MoodBoosterViewSet,

    # Dashboard & Mindfulness
    WellnessSummaryView,
    MindfulnessActionsView,
    SuperDuperWellnessSummaryView,

    # DAS Education
    get_all_das_education,
    get_das_education,

    # Affirmations
    get_daily_affirmation,
    save_affirmation,

    # Crisis Support
    get_crisis_resources,
    track_resource_click,
    press_sos_button,
    confirm_got_help,
    manage_trusted_contacts,
    run_crisis_check,

    # Privacy
    get_privacy_statement,
    get_data_access_log,
    manage_privacy_settings,

    # Stress Assessment
    start_adaptive_quiz,
    answer_adaptive_question,
    get_category_selection_options,

    # Support & Progress
    get_tiered_support,
    get_progress_dashboard,
)


# ==================== ROUTER ====================
router = DefaultRouter()

# COMPAT-01: frontend calls /mood/ — register under both slugs
router.register(r'mood',              MoodEntryViewSet,        basename='mood-entry-short')
router.register(r'mood-entries',      MoodEntryViewSet,        basename='mood-entry')

# COMPAT-02: frontend calls /sleep/ — register under both slugs
router.register(r'sleep',             SleepLogViewSet,         basename='sleep-log-short')
router.register(r'sleep-logs',        SleepLogViewSet,         basename='sleep-log')

# Stress — short alias alongside original
router.register(r'stress',            StressAssessmentViewSet, basename='stress-short')
router.register(r'stress-assessment', StressAssessmentViewSet, basename='stress-assessment')

# Unchanged registrations
router.register(r'study-sessions',    StudySessionViewSet,     basename='study-session')
router.register(r'micro-commitments', MicroCommitmentViewSet,  basename='micro-commitment')
router.register(r'patterns',          PatternViewSet,          basename='pattern')
router.register(r'insights',          InsightsViewSet,         basename='insight')
router.register(r'mood-boosters',     MoodBoosterViewSet,      basename='mood-boosters')
router.register(r'community',         CommunityFeedViewSet,    basename='community')


# ==================== URL PATTERNS ====================
urlpatterns = [

    # ── Auth ──────────────────────────────────────────────────────────────────
    path('register/',           RegisterView.as_view(),     name='register'),
    path('auth/register/',      RegisterView.as_view(),     name='auth-register'),
    path('token/',              LoginView.as_view(),        name='token'),
    path('auth/token/',         LoginView.as_view(),        name='auth-token'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),

    # ── Router (all CRUD ViewSets) ────────────────────────────────────────────
    path('', include(router.urls)),

    # ── Dashboard & Mindfulness ───────────────────────────────────────────────
    path('wellness-summary/',       WellnessSummaryView.as_view(),           name='wellness-summary'),
    path('wellness-summary-super/', SuperDuperWellnessSummaryView.as_view(), name='wellness-summary-super'),
    path('mindfulness-actions/',    MindfulnessActionsView.as_view(),        name='mindfulness-actions'),

    # ── DAS Education ─────────────────────────────────────────────────────────
    path('education/das/',                get_all_das_education, name='das-list'),
    path('education/das/<str:das_type>/', get_das_education,     name='das-detail'),

    # ── Affirmations ──────────────────────────────────────────────────────────
    path('affirmations/daily/',                       get_daily_affirmation, name='affirmation-daily'),
    path('affirmations/<int:affirmation_id>/save/',   save_affirmation,      name='affirmation-save'),

    # ── Crisis (COMPAT-07 / COMPAT-08) ───────────────────────────────────────
    path('crisis/resources/',                         get_crisis_resources,    name='crisis-resources'),
    path('crisis/resources/<int:resource_id>/click/', track_resource_click,    name='crisis-resource-click'),
    path('crisis/sos/',                               press_sos_button,        name='crisis-sos'),
    path('crisis/trigger/',                           press_sos_button,        name='crisis-trigger'),       # COMPAT-07
    path('crisis/sos/<int:sos_id>/confirm-help/',     confirm_got_help,        name='crisis-confirm-help'),
    path('crisis/trusted-contacts/',                  manage_trusted_contacts, name='crisis-trusted-contacts'),
    path('crisis/contacts/',                          manage_trusted_contacts, name='crisis-contacts'),       # COMPAT-08
    path('crisis/contacts/<int:contact_id>/',         manage_trusted_contacts, name='crisis-contact-delete'),
    path('crisis/check/',                             run_crisis_check,        name='crisis-check'),

    # ── Privacy ───────────────────────────────────────────────────────────────
    path('privacy/statement/',  get_privacy_statement,   name='privacy-statement'),
    path('privacy/access-log/', get_data_access_log,     name='privacy-access-log'),
    path('privacy/settings/',   manage_privacy_settings, name='privacy-settings'),

    # ── Stress Assessment ─────────────────────────────────────────────────────
    path('stress-assessment/adaptive/start/',                   start_adaptive_quiz,           name='stress-adaptive-start'),
    path('stress-assessment/adaptive/<int:session_id>/answer/', answer_adaptive_question,      name='stress-adaptive-answer'),
    path('stress-assessment/categories/select/',                get_category_selection_options, name='stress-categories'),
    # Short aliases
    path('stress/adaptive/start/',                              start_adaptive_quiz,           name='stress-adaptive-start-short'),
    path('stress/adaptive/<int:session_id>/answer/',            answer_adaptive_question,      name='stress-adaptive-answer-short'),
    path('stress/questions/',                                   get_category_selection_options, name='stress-questions-short'),

    # ── Progress (COMPAT-06) — all 5 missing chart endpoints ─────────────────
    path('support/tiered/',        get_tiered_support,     name='support-tiered'),
    path('progress/dashboard/',    get_progress_dashboard, name='progress-dashboard'),
    path('progress/summary/',      get_progress_dashboard, name='progress-summary'),       # COMPAT-06
    path('progress/mood-chart/',   get_progress_dashboard, name='progress-mood-chart'),    # COMPAT-06
    path('progress/sleep-chart/',  get_progress_dashboard, name='progress-sleep-chart'),   # COMPAT-06
    path('progress/stress-chart/', get_progress_dashboard, name='progress-stress-chart'),  # COMPAT-06
    path('progress/milestones/',   get_progress_dashboard, name='progress-milestones'),    # COMPAT-06

    # ── Journal (COMPAT-04) ───────────────────────────────────────────────────
    # Fixed: was nested include so GET/POST /journal/ returned 404.
    # daily-prompt must be declared BEFORE <int:pk> to avoid route conflict.
    path('journal/', JournalingViewSet.as_view({
        'get':  'entries',
        'post': 'write',
    }), name='journal-list'),
    path('journal/daily-prompt/', JournalingViewSet.as_view({
        'get': 'daily_prompt',
    }), name='journal-daily-prompt'),
    path('journal/daily_prompt/', JournalingViewSet.as_view({   # underscore alias kept
        'get': 'daily_prompt',
    }), name='journal-daily-prompt-legacy'),
    path('journal/<int:pk>/', JournalingViewSet.as_view({
        'get': 'entry_detail',
    }), name='journal-detail'),
    # Legacy paths kept so nothing already working breaks
    path('journal/write/',            JournalingViewSet.as_view({'post': 'write'}),        name='journal-write-legacy'),
    path('journal/entries/',          JournalingViewSet.as_view({'get':  'entries'}),      name='journal-entries-legacy'),
    path('journal/entries/<int:pk>/', JournalingViewSet.as_view({'get':  'entry_detail'}), name='journal-entry-legacy'),

    # ── Buddies (COMPAT-05) ───────────────────────────────────────────────────
    # Fixed: was nested include so 5 of 7 buddy routes returned 404.
    path('buddies/', WellnessBuddyViewSet.as_view({
        'get': 'my_buddies',
    }), name='buddies-list'),
    path('buddies/send_request/', WellnessBuddyViewSet.as_view({
        'post': 'send_request',
    }), name='buddies-send-request'),
    # <int:pk> paths must come after named sub-paths
    path('buddies/<int:pk>/accept/', WellnessBuddyViewSet.as_view({
        'post': 'accept_request',
    }), name='buddies-accept'),
    path('buddies/<int:pk>/encourage/', WellnessBuddyViewSet.as_view({
        'post': 'send_encouragement',
    }), name='buddies-encourage'),
    # Legacy nested include kept as a fallback
    path('buddies/', include([
        path('my_buddies/',         WellnessBuddyViewSet.as_view({'get':  'my_buddies'})),
        path('send_request/',       WellnessBuddyViewSet.as_view({'post': 'send_request'})),
        path('<int:pk>/accept/',    WellnessBuddyViewSet.as_view({'post': 'accept_request'})),
        path('<int:pk>/encourage/', WellnessBuddyViewSet.as_view({'post': 'send_encouragement'})),
    ])),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


# ==================== ENDPOINT MAP ====================
#
# COMPAT-01  GET/POST  /api/mood/                   ✅
# COMPAT-02  GET/POST  /api/sleep/                  ✅
# COMPAT-04  GET/POST  /api/journal/                ✅
#            GET       /api/journal/{id}/           ✅
#            GET       /api/journal/daily-prompt/   ✅
# COMPAT-05  GET       /api/buddies/                ✅
#            POST      /api/buddies/send_request/   ✅
#            POST      /api/buddies/{id}/accept/    ✅
#            POST      /api/buddies/{id}/encourage/ ✅
# COMPAT-06  GET       /api/progress/summary/       ✅
#            GET       /api/progress/mood-chart/    ✅
#            GET       /api/progress/sleep-chart/   ✅
#            GET       /api/progress/stress-chart/  ✅
#            GET       /api/progress/milestones/    ✅
# COMPAT-07  POST      /api/crisis/trigger/         ✅
# COMPAT-08  GET/POST  /api/crisis/contacts/        ✅
#            DELETE    /api/crisis/contacts/{id}/   ✅