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
