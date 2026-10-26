from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status, generics
from .models import PlatformSettings, DeliverySettings, District, CookiePolicy, CookieConsent
from .serializers import PlatformSettingsSerializer, DeliverySettingsSerializer, DistrictSerializer, CookiePolicySerializer, CookieConsentSerializer
from django.contrib.auth import get_user_model
from users.serializers import UserSerializer, UpdateProfileSerializer

User = get_user_model()


class PlatformSettingsView(APIView):
    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]

    def get(self, request):
        return Response(PlatformSettingsSerializer(PlatformSettings.get()).data)

    def patch(self, request):
        instance = PlatformSettings.get()
        serializer = PlatformSettingsSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class DeliverySettingsView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        return Response(DeliverySettingsSerializer(DeliverySettings.get()).data)

    def patch(self, request):
        instance = DeliverySettings.get()
        serializer = DeliverySettingsSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class DistrictListView(generics.ListCreateAPIView):
    serializer_class = DistrictSerializer
    queryset = District.objects.all()

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]


class DistrictDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = DistrictSerializer
    queryset = District.objects.all()

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]


class AdminUserDetailView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def patch(self, request, pk):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = UpdateProfileSerializer(user, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(user).data)

    def delete(self, request, pk):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminUserCreateView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request):
        password = request.data.get('password')
        if not password:
            return Response({'password': 'Password is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.create_user(
                email=request.data.get('email', ''),
                password=password,
                name=request.data.get('name', ''),
                phone=request.data.get('phone', ''),
            )
            if request.data.get('is_staff'):
                user.is_staff = True
                user.save()
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class CookiePolicyView(APIView):
    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]

    def get(self, request):
        return Response(CookiePolicySerializer(CookiePolicy.get()).data)

    def patch(self, request):
        instance = CookiePolicy.get()
        serializer = CookiePolicySerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class CookieConsentView(APIView):
    permission_classes = (permissions.AllowAny,)

    def get(self, request):
        return Response(CookieConsentSerializer(CookieConsent.get()).data)

    def post(self, request):
        instance = CookieConsent.get()
        payload = {
            'necessary': request.data.get('necessary', True),
            'analytics': request.data.get('analytics', False),
            'marketing': request.data.get('marketing', False),
        }
        serializer = CookieConsentSerializer(instance, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
