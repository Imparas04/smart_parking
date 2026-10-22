from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import phone_validator

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    role = serializers.CharField(source='profile.role', read_only=True)
    phone = serializers.CharField(source='profile.phone', read_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'first_name', 'last_name', 'email', 'phone', 'role')
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    phone = serializers.CharField(max_length=16, required=False, allow_blank=True, validators=[phone_validator])
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)

    class Meta:
        model = User
        fields = ('username', 'password', 'first_name', 'last_name', 'email', 'phone')

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def validate(self, attrs):
        probe = User(username=attrs.get('username'), email=attrs.get('email'))
        validate_password(attrs['password'], probe)
        return attrs

    def create(self, validated_data):
        phone = validated_data.pop('phone', '')
        user = User.objects.create_user(**validated_data)
        user.profile.phone = phone
        user.profile.save(update_fields=['phone', 'updated_at'])
        return user


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate(self, attrs):
        user = authenticate(username=attrs['username'], password=attrs['password'])
        if not user or not user.is_active:
            raise serializers.ValidationError('Invalid username or password.')
        attrs['user'] = user
        return attrs


class ProfileUpdateSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(max_length=16, required=False, allow_blank=True, validators=[phone_validator])

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'phone')

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def update(self, instance, validated_data):
        phone = validated_data.pop('phone', None)
        instance = super().update(instance, validated_data)
        if phone is not None:
            instance.profile.phone = phone
            instance.profile.save(update_fields=['phone', 'updated_at'])
        return instance
