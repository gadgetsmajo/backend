from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient


class CookieConsentAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_post_cookie_consent_creates_record(self):
        response = self.client.post(
            reverse('cookie-consent'),
            {'necessary': True, 'analytics': True, 'marketing': False},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['necessary'])
        self.assertTrue(response.data['analytics'])
        self.assertFalse(response.data['marketing'])

    def test_get_cookie_consent_returns_saved_state(self):
        self.client.post(
            reverse('cookie-consent'),
            {'necessary': True, 'analytics': False, 'marketing': True},
            format='json',
        )

        response = self.client.get(reverse('cookie-consent'))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['necessary'])
        self.assertFalse(response.data['analytics'])
        self.assertTrue(response.data['marketing'])
