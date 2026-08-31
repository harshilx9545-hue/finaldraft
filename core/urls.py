"""The Phase 1 API surface, and nothing else.

Workout tracking, body metrics, form checks, diet plans, attendance, equipment and
notifications have models but deliberately no routes. `check_api_surface` fails the
build if a route matching any of those categories appears, so the omission is
enforced rather than merely intended (24.5, 24.6).

Note there is no gym id anywhere in a path. The tenant is always resolved from the
caller's own profile, which removes the entire class of "wrong id in the URL" bugs.
"""
from django.urls import path

from core.views import auth, billing, catalogue, profiles, webhooks

app_name = "core"

auth_patterns = [
    path("auth/register/owner", auth.OwnerRegistrationView.as_view(), name="register-owner"),
    path("auth/login", auth.LoginView.as_view(), name="login"),
    path("auth/refresh", auth.TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/logout", auth.LogoutView.as_view(), name="logout"),
    path("auth/verify-email", auth.EmailVerificationView.as_view(), name="verify-email"),
    path(
        "auth/password-reset",
        auth.PasswordResetRequestView.as_view(),
        name="password-reset",
    ),
    path(
        "auth/password-reset/confirm",
        auth.PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
]

catalogue_patterns = [
    path("saas-plans", catalogue.SaasPlanListView.as_view(), name="saas-plan-list"),
    path(
        "membership-plans",
        catalogue.MembershipPlanListCreateView.as_view(),
        name="membership-plan-list",
    ),
    path(
        "membership-plans/<int:pk>",
        catalogue.MembershipPlanDetailView.as_view(),
        name="membership-plan-detail",
    ),
]

profile_patterns = [
    path("me", profiles.MeView.as_view(), name="me"),
    path("gym", profiles.GymDetailView.as_view(), name="gym-detail"),
    path("trainers", profiles.TrainerListCreateView.as_view(), name="trainer-list"),
    path("members", profiles.MemberListCreateView.as_view(), name="member-list"),
    path("members/<int:pk>", profiles.MemberDetailView.as_view(), name="member-detail"),
]

billing_patterns = [
    path("invoices", billing.InvoiceListView.as_view(), name="invoice-list"),
    path("invoices/<int:pk>", billing.InvoiceDetailView.as_view(), name="invoice-detail"),
    path("invoices/<int:pk>/pay", billing.InvoicePayView.as_view(), name="invoice-pay"),
    path("payments/<int:pk>/receipt", billing.ReceiptView.as_view(), name="payment-receipt"),
]

webhook_patterns = [
    path(
        "webhooks/razorpay",
        webhooks.RazorpayWebhookView.as_view(),
        name="razorpay-webhook",
    ),
]

urlpatterns = (
    auth_patterns
    + catalogue_patterns
    + profile_patterns
    + billing_patterns
    + webhook_patterns
)
