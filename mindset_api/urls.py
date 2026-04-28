from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from django.conf import settings
from django.conf.urls.static import static

from .views import (
    # Auth & Profile
    RegisterView,
    LoginView,
    UserProfileView,

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
    get_saved_affirmations,       # FE-08
    unsave_affirmation,           # FE-09

    # Crisis Support
    get_crisis_resources,
    track_resource_click,
    press_sos_button,
    confirm_got_help,
    manage_trusted_contacts,
    run_crisis_check,
    delete_trusted_contact,       # COMPAT-04

    # Privacy
    get_privacy_statement,
    get_data_access_log,
    manage_privacy_settings,
    export_user_data,             # FE-11 GET
    delete_account,               # FE-11 DELETE

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
router.register(r'mood-entries',      MoodEntryViewSet,        basename='mood-entry')
router.register(r'sleep-logs',        SleepLogViewSet,         basename='sleep-log')
router.register(r'study-sessions',    StudySessionViewSet,     basename='study-session')
router.register(r'micro-commitments', MicroCommitmentViewSet,  basename='micro-commitment')
router.register(r'patterns',          PatternViewSet,          basename='pattern')
router.register(r'insights',          InsightsViewSet,         basename='insight')
router.register(r'stress-assessment', StressAssessmentViewSet, basename='stress-assessment')
router.register(r'mood-boosters',     MoodBoosterViewSet,      basename='mood-boosters')
router.register(r'community',         CommunityFeedViewSet,    basename='community')


# ==================== URL PATTERNS ====================
urlpatterns = [

    # ── Auth ──────────────────────────────────────────────────────────────────
    path('register/',           RegisterView.as_view(),       name='register'),
    path('auth/register/',      RegisterView.as_view(),       name='auth-register'),
    path('token/',              LoginView.as_view(),          name='token'),
    path('auth/token/',         LoginView.as_view(),          name='auth-token'),
    path('auth/token/refresh/', TokenRefreshView.as_view(),   name='token-refresh'),
    path('auth/profile/',       UserProfileView.as_view(),    name='auth-profile'),

    # ── Router (all CRUD ViewSets) ────────────────────────────────────────────
    path('', include(router.urls)),

    # ── Dashboard & Mindfulness ───────────────────────────────────────────────
    path('wellness-summary/',       WellnessSummaryView.as_view(),           name='wellness-summary'),
    path('wellness-summary-super/', SuperDuperWellnessSummaryView.as_view(), name='wellness-summary-super'),
    path('mindfulness-actions/',    MindfulnessActionsView.as_view(),        name='mindfulness-actions'),

    # ── DAS Education (public) ────────────────────────────────────────────────
    path('education/das/',                get_all_das_education),
    path('education/das/<str:das_type>/', get_das_education),

    # ── Affirmations ──────────────────────────────────────────────────────────
    path('affirmations/daily/',                        get_daily_affirmation),   # public
    path('affirmations/saved/',                        get_saved_affirmations),  # FE-08  GET
    path('affirmations/<int:affirmation_id>/save/',    save_affirmation),        #        POST
    path('affirmations/<int:affirmation_id>/unsave/',  unsave_affirmation),      # FE-09  DELETE

    # ── Crisis Support ────────────────────────────────────────────────────────
    path('crisis/resources/',                         get_crisis_resources),    # public  GET
    path('crisis/resources/<int:resource_id>/click/', track_resource_click),    #         POST
    path('crisis/sos/',                               press_sos_button),        #         POST
    path('crisis/sos/<int:sos_id>/confirm-help/',     confirm_got_help),        #         POST
    path('crisis/trusted-contacts/',                  manage_trusted_contacts), # GET / POST
    path('crisis/contacts/<int:contact_id>/',         delete_trusted_contact),  # COMPAT-04 DELETE
    path('crisis/check/',                             run_crisis_check),        #         POST

    # ── Privacy ───────────────────────────────────────────────────────────────
    path('privacy/statement/',  get_privacy_statement),   # public  GET
    path('privacy/access-log/', get_data_access_log),     #         GET
    path('privacy/settings/',   manage_privacy_settings), # GET / PUT
    path('privacy/export/',     export_user_data),        # FE-11   GET
    path('privacy/account/',    delete_account),          # FE-11   DELETE

    # ── Stress Assessment ─────────────────────────────────────────────────────
    path('stress-assessment/adaptive/start/',                    start_adaptive_quiz),
    path('stress-assessment/adaptive/<int:session_id>/answer/',  answer_adaptive_question),
    path('stress-assessment/categories/select/',                 get_category_selection_options),

    # ── Support & Progress ────────────────────────────────────────────────────
    path('support/tiered/',     get_tiered_support),
    path('progress/dashboard/', get_progress_dashboard),

    # ── Journal ───────────────────────────────────────────────────────────────
    path('journal/', include([
        path('daily_prompt/',       JournalingViewSet.as_view({'get':  'daily_prompt'})),
        path('write/',              JournalingViewSet.as_view({'post': 'write'})),
        path('entries/',            JournalingViewSet.as_view({'get':  'entries'})),
        path('entries/<int:pk>/',   JournalingViewSet.as_view({'get':  'entry_detail'})),
    ])),

    # ── Wellness Buddies ──────────────────────────────────────────────────────
    path('buddies/', include([
        path('my_buddies/',           WellnessBuddyViewSet.as_view({'get':  'my_buddies'})),
        path('send_request/',         WellnessBuddyViewSet.as_view({'post': 'send_request'})),
        path('<int:pk>/accept/',      WellnessBuddyViewSet.as_view({'post': 'accept_request'})),
        path('<int:pk>/encourage/',   WellnessBuddyViewSet.as_view({'post': 'send_encouragement'})),
    ])),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)