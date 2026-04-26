from django.urls import path, include
from django.contrib import admin
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView          # Fix #2
from django.conf import settings
from django.conf.urls.static import static
from .views import (
    CommunityFeedViewSet,
    JournalingViewSet,
    RegisterView,
    LoginView,
    UserProfileView,                                                   # Fix #3
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


# ─── Router ───────────────────────────────────────────────────────────────────
router = DefaultRouter()
# Fix #4  — register as 'mood'         so /mood/ and /mood/{id}/ work
router.register(r'mood',              MoodEntryViewSet,       basename='mood-entry')
# Fix #5  — register as 'sleep'        so /sleep/ and /sleep/{id}/ work
router.register(r'sleep',             SleepLogViewSet,        basename='sleep-log')
# Fix #8  — register as 'stress'       so /stress/ and /stress/{id}/ work
router.register(r'stress',            StressAssessmentViewSet, basename='stress')
# Keep original kebab-case aliases so existing integrations keep working
router.register(r'mood-entries',      MoodEntryViewSet,       basename='mood-entry-compat')
router.register(r'sleep-logs',        SleepLogViewSet,        basename='sleep-log-compat')
router.register(r'stress-assessment', StressAssessmentViewSet, basename='stress-assessment-compat')
# Unchanged registrations
router.register(r'study-sessions',    StudySessionViewSet,    basename='study-session')
router.register(r'micro-commitments', MicroCommitmentViewSet, basename='micro-commitment')
router.register(r'patterns',          PatternViewSet,         basename='pattern')
router.register(r'insights',          InsightsViewSet,        basename='insight')
router.register(r'mood-boosters',     MoodBoosterViewSet,     basename='mood-boosters')
router.register(r'community',         CommunityFeedViewSet,   basename='community')


urlpatterns = [

    # ── Authentication ────────────────────────────────────────────────────────
    path('register/',             RegisterView.as_view(),   name='register'),
    path('token/',                LoginView.as_view(),      name='token'),
    path('auth/token/',           LoginView.as_view(),      name='auth-token'),          # alias
    path('auth/token/refresh/',   TokenRefreshView.as_view(), name='token-refresh'),     # Fix #2
    path('auth/profile/',         UserProfileView.as_view(), name='auth-profile'),       # Fix #3

    # ── Wellness Dashboard ────────────────────────────────────────────────────
    path('wellness-summary/',       WellnessSummaryView.as_view(),          name='wellness-summary'),
    path('wellness-summary-super/', SuperDuperWellnessSummaryView.as_view(), name='wellness-summary-super'),

    # ── Mindfulness ───────────────────────────────────────────────────────────
    path('mindfulness-actions/', MindfulnessActionsView.as_view(), name='mindfulness-actions'),

    # ── Router URLs (mood, sleep, study-sessions, stress, etc.) ──────────────
    path('', include(router.urls)),

    # ── DAS Education ─────────────────────────────────────────────────────────
    path('education/das/',                  get_all_das_education),
    path('education/das/<str:das_type>/',   get_das_education),

    # ── Affirmations ──────────────────────────────────────────────────────────
    path('affirmations/daily/',                         get_daily_affirmation),
    path('affirmations/<int:affirmation_id>/save/',     save_affirmation),

    # ── Crisis Support ────────────────────────────────────────────────────────
    path('crisis/resources/',                           get_crisis_resources),
    path('crisis/resources/<int:resource_id>/click/',   track_resource_click),
    # Fix #11 — /crisis/trigger/ and /crisis/contacts/ aliases
    path('crisis/trigger/',                             press_sos_button),             # Fix #11
    path('crisis/sos/',                                 press_sos_button),             # original kept
    path('crisis/sos/<int:sos_id>/confirm-help/',       confirm_got_help),
    path('crisis/contacts/',                            manage_trusted_contacts),      # Fix #11
    path('crisis/trusted-contacts/',                    manage_trusted_contacts),      # original kept
    path('crisis/check/',                               run_crisis_check),

    # ── Privacy ───────────────────────────────────────────────────────────────
    path('privacy/statement/',  get_privacy_statement),
    path('privacy/access-log/', get_data_access_log),
    path('privacy/settings/',   manage_privacy_settings),

    # ── Stress Assessment (adaptive quiz) ─────────────────────────────────────
    path('stress-assessment/adaptive/start/',                       start_adaptive_quiz),
    path('stress-assessment/adaptive/<int:session_id>/answer/',     answer_adaptive_question),
    path('stress-assessment/categories/select/',                    get_category_selection_options),
    # Fix #8 — short alias
    path('stress/adaptive/start/',                                  start_adaptive_quiz),
    path('stress/adaptive/<int:session_id>/answer/',                answer_adaptive_question),
    path('stress/questions/',                                       get_category_selection_options),

    # ── Support & Progress ────────────────────────────────────────────────────
    path('support/tiered/',      get_tiered_support),
    path('progress/dashboard/',  get_progress_dashboard),
    # Fix #10 — /progress/summary/ and chart aliases all point to the same dashboard view
    path('progress/summary/',    get_progress_dashboard),
    path('progress/mood-chart/', get_progress_dashboard),
    path('progress/sleep-chart/',get_progress_dashboard),
    path('progress/stress-chart/',get_progress_dashboard),
    path('progress/milestones/', get_progress_dashboard),

    # ── Journaling  (Fix #7) ──────────────────────────────────────────────────
    # REST-style: GET/POST /journal/ and GET/PATCH/DELETE /journal/{id}/
    path('journal/', JournalingViewSet.as_view({
        'get':  'list',
        'post': 'create',
    }), name='journal-list'),
    path('journal/daily-prompt/', JournalingViewSet.as_view({
        'get': 'daily_prompt',
    }), name='journal-daily-prompt'),
    # daily_prompt must be BEFORE <int:pk> so it is matched first
    path('journal/<int:pk>/', JournalingViewSet.as_view({
        'get':    'retrieve',
        'patch':  'partial_update',
        'delete': 'destroy',
    }), name='journal-detail'),
    # Legacy paths kept for backward compatibility
    path('journal/write/',              JournalingViewSet.as_view({'post': 'write'})),
    path('journal/entries/',            JournalingViewSet.as_view({'get': 'entries'})),
    path('journal/entries/<int:pk>/',   JournalingViewSet.as_view({'get': 'entry_detail'})),

    # ── Wellness Buddies  (Fix #9) ────────────────────────────────────────────
    path('buddies/', WellnessBuddyViewSet.as_view({
        'get': 'my_buddies',
    }), name='buddies-list'),
    path('buddies/search/', WellnessBuddyViewSet.as_view({
        'get': 'search',
    }), name='buddies-search'),
    path('buddies/requests/', WellnessBuddyViewSet.as_view({
        'get':  'list_requests',
        'post': 'send_request',
    }), name='buddies-requests'),
    path('buddies/requests/<int:pk>/accept/', WellnessBuddyViewSet.as_view({
        'post': 'accept_request',
    }), name='buddies-accept'),
    path('buddies/requests/<int:pk>/decline/', WellnessBuddyViewSet.as_view({
        'post': 'decline_request',
    }), name='buddies-decline'),
    path('buddies/<int:pk>/', WellnessBuddyViewSet.as_view({
        'delete': 'remove_buddy',
    }), name='buddies-remove'),
    # Legacy paths kept
    path('buddies/send_request/',       WellnessBuddyViewSet.as_view({'post': 'send_request'})),
    path('buddies/<int:pk>/encourage/', WellnessBuddyViewSet.as_view({'post': 'send_encouragement'})),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


# ==================== AVAILABLE ENDPOINTS ====================
#
# Authentication:
# POST   /api/register/                          - Register new user
# POST   /api/token/                             - Login (get JWT tokens)
# POST   /api/auth/token/                        - Login alias
# POST   /api/auth/token/refresh/                - Refresh access token     [Fix #2]
# GET    /api/auth/profile/                      - Get user profile         [Fix #3]
# PATCH  /api/auth/profile/                      - Update user profile      [Fix #3]
#
# Mood Entries:
# GET    /api/mood/                              - List  [Fix #4]
# POST   /api/mood/                              - Create
# GET    /api/mood/{id}/                         - Retrieve
# PATCH  /api/mood/{id}/                         - Update
# DELETE /api/mood/{id}/                         - Delete
# (original /api/mood-entries/ kept as alias)
#
# Sleep Logs:
# GET    /api/sleep/                             - List  [Fix #5]
# POST   /api/sleep/                             - Create
# GET    /api/sleep/{id}/                        - Retrieve
# PATCH  /api/sleep/{id}/                        - Update
# DELETE /api/sleep/{id}/                        - Delete
# (original /api/sleep-logs/ kept as alias)
#
# Study Sessions:
# GET    /api/study-sessions/                    - List
# POST   /api/study-sessions/                    - Create
# POST   /api/study-sessions/{id}/start/         - Start session  [Fix #6]
# POST   /api/study-sessions/{id}/end/           - End session    [Fix #6]
#
# Stress Assessment:
# GET    /api/stress/                            - List responses [Fix #8]
# POST   /api/stress/                            - Submit response
# GET    /api/stress/questions/                  - Get questions  [Fix #8]
# (original /api/stress-assessment/ kept as alias)
#
# Journaling:
# GET    /api/journal/                           - List entries   [Fix #7]
# POST   /api/journal/                           - Create entry   [Fix #7]
# GET    /api/journal/daily-prompt/              - Daily prompt
# GET    /api/journal/{id}/                      - Get entry      [Fix #7]
# PATCH  /api/journal/{id}/                      - Update entry   [Fix #7]
# DELETE /api/journal/{id}/                      - Delete entry   [Fix #7]
#
# Wellness Buddies:
# GET    /api/buddies/                           - List buddies
# GET    /api/buddies/search/?q=                 - Search users   [Fix #9]
# GET    /api/buddies/requests/                  - List requests  [Fix #9]
# POST   /api/buddies/requests/                  - Send request   [Fix #9]
# POST   /api/buddies/requests/{id}/accept/      - Accept         [Fix #9]
# POST   /api/buddies/requests/{id}/decline/     - Decline        [Fix #9]
# DELETE /api/buddies/{id}/                      - Remove buddy   [Fix #9]
#
# Crisis:
# POST   /api/crisis/trigger/                    - SOS trigger    [Fix #11]
# POST   /api/crisis/sos/                        - SOS (alias)
# GET    /api/crisis/contacts/                   - Trusted contacts [Fix #11]
# POST   /api/crisis/contacts/                   - Add contact    [Fix #11]
# GET    /api/crisis/trusted-contacts/           - (alias kept)
#
# Progress:
# GET    /api/progress/summary/                  - Summary        [Fix #10]
# GET    /api/progress/mood-chart/               - Mood chart     [Fix #10]
# GET    /api/progress/sleep-chart/              - Sleep chart    [Fix #10]
# GET    /api/progress/stress-chart/             - Stress chart   [Fix #10]
# GET    /api/progress/milestones/               - Milestones     [Fix #10]
# GET    /api/progress/dashboard/                - (original kept)