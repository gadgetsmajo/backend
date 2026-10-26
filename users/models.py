from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
import uuid
import cloudinary.models


class Notification(models.Model):
    TYPE_CHOICES = [
        ('order', 'Order'),
        ('welcome', 'Welcome'),
        ('promo', 'Promo'),
        ('system', 'System'),
        ('service_rating', 'Service Rating'),
        ('product_rating', 'Product Rating'),
    ]
    user = models.ForeignKey('User', on_delete=models.CASCADE, related_name='notifications')
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='system')
    title = models.CharField(max_length=255)
    body = models.TextField()
    action_url = models.CharField(max_length=255, blank=True)
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.email} — {self.title}'


class SupportConversation(models.Model):
    user = models.OneToOneField('User', on_delete=models.CASCADE, related_name='support_conversation')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    customer_typing_at = models.DateTimeField(null=True, blank=True)
    staff_typing_at = models.DateTimeField(null=True, blank=True)
    is_closed = models.BooleanField(default=False)
    admin_new_message_alert_sent = models.BooleanField(default=False)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f'Support conversation with {self.user.email}'


class SupportConversationStaffPresence(models.Model):
    conversation = models.ForeignKey(SupportConversation, on_delete=models.CASCADE, related_name='staff_presence')
    staff = models.ForeignKey('User', on_delete=models.CASCADE, related_name='support_conversation_presence')
    first_joined_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['conversation', 'staff'], name='unique_support_staff_presence'),
        ]


class SupportEncryptionKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey('User', on_delete=models.CASCADE, related_name='support_encryption_keys')
    device_id = models.UUIDField()
    public_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'device_id'], name='unique_support_key_per_device'),
        ]


class SupportEncryptionBackup(models.Model):
    user = models.OneToOneField('User', on_delete=models.CASCADE, related_name='support_encryption_backup')
    payload = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)


class SupportMessage(models.Model):
    conversation = models.ForeignKey(SupportConversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey('User', on_delete=models.CASCADE, related_name='support_messages')
    body = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'Message in support conversation {self.conversation_id}'


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    avatar = cloudinary.models.CloudinaryField('avatar', folder='avatars/', blank=True, null=True)
    country = models.CharField(max_length=100, default='Uganda')
    region = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    village = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    assigned_pages = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

    def __str__(self):
        return self.email


class EmailMfaChallenge(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_mfa_challenges')
    challenge_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    code_hash = models.CharField(max_length=128)
    device_name = models.CharField(max_length=120, default='Unknown device')
    expires_at = models.DateTimeField()
    last_sent_at = models.DateTimeField()
    send_count = models.PositiveSmallIntegerField(default=1)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class EmailMfaTrustedDevice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_mfa_trusted_devices')
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)


class CartItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cart_items')
    product_id = models.IntegerField()
    product_name = models.CharField(max_length=255)
    product_price = models.DecimalField(max_digits=12, decimal_places=2)
    product_image = models.URLField(blank=True, null=True)
    product_slug = models.CharField(max_length=255, blank=True)
    product_category = models.CharField(max_length=100, blank=True)
    product_rating = models.DecimalField(max_digits=3, decimal_places=1, default=0)
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product_id')

    def __str__(self):
        return f'{self.user.email} — {self.product_name} x{self.quantity}'


class WishlistItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wishlist_items')
    product_id = models.IntegerField()
    product_name = models.CharField(max_length=255)
    product_price = models.DecimalField(max_digits=12, decimal_places=2)
    product_image = models.URLField(blank=True, null=True)
    product_slug = models.CharField(max_length=255, blank=True)
    product_category = models.CharField(max_length=100, blank=True)
    product_rating = models.DecimalField(max_digits=3, decimal_places=1, default=0)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product_id')

    def __str__(self):
        return f'{self.user.email} — {self.product_name}'


class UserBehaviour(models.Model):
    """Stores per-user category interest scores and recently seen product ids."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='behaviour')
    # JSON: { category_slug: score }
    category_scores = models.JSONField(default=dict)
    # JSON: [product_id, ...] most recent first, capped at 60
    recent_product_ids = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Behaviour({self.user.email})'

    @classmethod
    def get_for_user(cls, user):
        return cls.objects.get_or_create(user=user)[0]

    def track_category(self, category_slug, score=1, product_id=None):
        if not category_slug:
            return
        scores = dict(self.category_scores or {})
        scores[category_slug] = scores.get(category_slug, 0) + score
        self.category_scores = scores

        if product_id is not None:
            seen = [pid for pid in (self.recent_product_ids or []) if pid != product_id]
            seen.insert(0, int(product_id))
            self.recent_product_ids = seen[:60]

        self.save(update_fields=['category_scores', 'recent_product_ids', 'updated_at'])
