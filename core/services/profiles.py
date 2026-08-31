"""Role and profile consistency.

The invariant (Property 16): every non-staff User holds exactly one
non-soft-deleted profile, and that profile's type matches the stored role.

Five rules enforce it, and they are here rather than in `Model.clean()` because
two of them span two rows (role change plus profile creation) and must be applied
inside one transaction:

1. At most one non-soft-deleted profile per User.
2. The profile type must match the role.
3. Staff accounts hold no profile at all (D6).
4. A role change is blocked while a profile of the previous type still exists.
5. A role change plus profile creation is atomic when no such profile exists.
"""
from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import ValidationError

from core.models import MemberProfile, OwnerProfile, TrainerProfile

PROFILE_MODELS = {
    "owner": OwnerProfile,
    "trainer": TrainerProfile,
    "member": MemberProfile,
}

PROFILE_ATTRIBUTES = {
    "owner": "owner_profile",
    "trainer": "trainer_profile",
    "member": "member_profile",
}

ROLE_FOR_MODEL = {model: role for role, model in PROFILE_MODELS.items()}


def role_for_profile(profile):
    return ROLE_FOR_MODEL.get(type(profile))


def existing_profiles(user):
    """Every non-soft-deleted profile the user holds, as {role: profile}.

    More than one entry is the violation Property 16 forbids; the function returns
    them all rather than the first so an error can name the conflict.
    """
    found = {}
    for role, attribute in PROFILE_ATTRIBUTES.items():
        try:
            profile = getattr(user, attribute, None)
        except Exception:  # RelatedObjectDoesNotExist
            profile = None
        if profile is not None and profile.deleted_at is None:
            found[role] = profile
    return found


def assert_can_hold_profile(user, role):
    """Rule 1, 2 and 3: may this user gain a `role` profile right now?"""
    if user.is_staff or user.is_superuser:
        raise ValidationError(
            {
                "user": (
                    "Platform operator accounts hold no gym profile. Their only "
                    "surface is the admin."
                )
            }
        )

    if role not in PROFILE_MODELS:
        raise ValidationError({"role": f"{role!r} is not a profile-bearing role."})

    held = existing_profiles(user)
    if held:
        held_role = next(iter(held))
        raise ValidationError(
            {
                "profile": (
                    f"This user already holds a {held_role} profile. A user may hold "
                    "exactly one profile."
                ),
                "existing_role": held_role,
                "requested_role": role,
            }
        )

    if user.role != role:
        raise ValidationError(
            {
                "role": (
                    f"Cannot create a {role} profile for a user whose role is "
                    f"{user.role!r}. The profile type must match the stored role."
                ),
                "stored_role": user.role,
                "requested_role": role,
            }
        )


def create_profile(user, role, **fields):
    """Create the profile for `role` after checking every consistency rule."""
    assert_can_hold_profile(user, role)
    model = PROFILE_MODELS[role]

    # Profiles are soft-deleted to preserve their history, while `user` is a
    # OneToOneField.  A later legitimate return to the same role must therefore
    # reactivate that historical row instead of attempting a second row that the
    # database quite correctly rejects as a duplicate.
    archived = model.all_objects.filter(user=user, deleted_at__isnull=False).first()
    if archived is not None:
        for name, value in fields.items():
            setattr(archived, name, value)
        archived.restore(save=False)
        archived.save(update_fields=["deleted_at", *fields])
        return archived

    return model.objects.create(user=user, **fields)


def assert_role_change_allowed(user, new_role):
    """Rule 4: block a role change while a profile of the previous type exists."""
    if new_role == user.role:
        return

    if user.is_staff or user.is_superuser:
        raise ValidationError(
            {"role": "Role is not consulted for platform operator accounts."}
        )

    if new_role not in PROFILE_MODELS:
        raise ValidationError(
            {"role": f"{new_role!r} is not one of {sorted(PROFILE_MODELS)}."}
        )

    held = existing_profiles(user)
    if user.role in held:
        raise ValidationError(
            {
                "role": (
                    f"This user still holds a {user.role} profile. Soft-delete it "
                    f"before changing the role to {new_role}."
                ),
                "stored_role": user.role,
                "requested_role": new_role,
                "conflicting_profile": type(held[user.role]).__name__,
            }
        )


@transaction.atomic
def change_role_with_profile(user, new_role, **profile_fields):
    """Rule 5: change the role and create the matching profile, or neither.

    Both writes happen in one transaction, so a failure in the profile create
    rolls the role back and the pair can never disagree.
    """
    assert_role_change_allowed(user, new_role)

    previous = user.role
    user.role = new_role
    user.save(update_fields=["role"])

    try:
        profile = create_profile(user, new_role, **profile_fields)
    except Exception:
        # Explicit for readability; the atomic block would roll back regardless.
        user.role = previous
        raise

    return profile


def assert_consistent(user):
    """Assert the whole invariant for one user. Used by the stateful property test."""
    if user.is_staff or user.is_superuser:
        held = existing_profiles(user)
        if held:
            raise ValidationError(
                {"profile": f"Staff account holds a {next(iter(held))} profile."}
            )
        return True

    held = existing_profiles(user)
    if len(held) != 1:
        raise ValidationError(
            {
                "profile": (
                    f"Expected exactly one profile, found {len(held)}: "
                    f"{sorted(held)}."
                )
            }
        )
    (held_role,) = held
    if held_role != user.role:
        raise ValidationError(
            {
                "role": (
                    f"Stored role {user.role!r} disagrees with held profile "
                    f"{held_role!r}."
                )
            }
        )
    return True
