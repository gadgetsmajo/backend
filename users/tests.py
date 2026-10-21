from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from .models import User
from .serializers import LoginSerializer


class LoginSerializerPhoneTests(TestCase):
    def test_phone_login_accepts_common_phone_formats(self):
        user = User.objects.create_user(
            email=None,
            phone_number='+256786023858',
            password='12345678',
            full_name='Test User',
        )

        serializer = LoginSerializer(data={
            'phone_number': '0786023858',
            'password': '12345678',
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['user'], user)


class CreateAdminCommandTests(TestCase):
    def test_rerunning_command_synchronizes_password_and_permissions(self):
        email = 'railway-admin@example.com'
        output = StringIO()

        call_command('create_admin', email, 'first-password', name='EducFarm', stdout=output)
        call_command('create_admin', email, 'current-password', name='EducFarm', stdout=output)

        user = User.objects.get(email=email)
        self.assertTrue(user.check_password('current-password'))
        self.assertFalse(user.check_password('first-password'))
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.admin_level, 'superadmin')
        self.assertTrue(user.can_manage_users)
        self.assertTrue(user.can_manage_devices)
        self.assertTrue(user.can_manage_weather)
        self.assertTrue(user.can_manage_system)
