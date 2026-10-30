"""The user record and the congregation it can belong to."""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel, UUIDModel

from .levels import level_for_xp


class Congregation(BaseModel):
    """A church or family group -- the `congregation` leaderboard scope."""

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("display_name", email.split("@")[0])
        if not extra["is_staff"] or not extra["is_superuser"]:
            raise ValueError("Superusers must have is_staff and is_superuser set.")
        return self._create_user(email, password, **extra)


class User(UUIDModel, AbstractBaseUser, PermissionsMixin):
    """
    Serialised to the client's `User` type.

    `level` is derived from `xp` rather than stored, so the two can never
    disagree; `points` is the lifetime score the leaderboards rank on and is
    deliberately separate from `xp` (which only ever goes up with play time).
    """

    ROLE_HOST = "host"
    ROLE_PLAYER = "player"
    ROLE_CHOICES = ((ROLE_HOST, "Host"), (ROLE_PLAYER, "Player"))

    email = models.EmailField(unique=True, db_index=True)
    display_name = models.CharField(max_length=40)
    # Holds `asset://<key>` for bundled art or an absolute https URL; a plain
    # CharField because `asset://` is not a URL any validator would accept.
    avatar_url = models.CharField(max_length=500, blank=True, default="")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_PLAYER)

    xp = models.PositiveIntegerField(default=0)
    points = models.PositiveIntegerField(default=0, db_index=True)
    # Headline badge shown beside a leaderboard row, e.g. "Scripture Scholar".
    title = models.CharField(max_length=60, blank=True, default="")

    congregation = models.ForeignKey(
        Congregation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="members",
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["display_name"]

    class Meta:
        ordering = ("-points",)
        indexes = [
            # Backs the leaderboard's ORDER BY points DESC, id for stable paging.
            models.Index(fields=("-points", "id"), name="user_points_rank_idx"),
            models.Index(fields=("congregation", "-points"), name="user_cong_rank_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.display_name} <{self.email}>"

    @property
    def level(self) -> str:
        return level_for_xp(self.xp)

    def get_full_name(self) -> str:
        return self.display_name

    def get_short_name(self) -> str:
        return self.display_name
