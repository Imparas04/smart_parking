from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import phone_validator

User = get_user_model()


def _unique_email(email, exclude_pk=None):
    email = email.strip().lower()
    qs = User.objects.filter(email__iexact=email)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise forms.ValidationError('An account with this email already exists.')
    return email


class RegisterForm(UserCreationForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField()
    phone = forms.CharField(max_length=16, required=False, validators=[phone_validator])

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'phone')

    def clean_email(self):
        return _unique_email(self.cleaned_data['email'])

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            user.profile.phone = self.cleaned_data.get('phone', '')
            user.profile.save(update_fields=['phone', 'updated_at'])
        return user


class ProfileForm(forms.ModelForm):
    phone = forms.CharField(max_length=16, required=False, validators=[phone_validator])

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['email'].required = True
        if self.instance.pk:
            self.fields['phone'].initial = self.instance.profile.phone

    def clean_email(self):
        return _unique_email(self.cleaned_data['email'], self.instance.pk)

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            user.profile.phone = self.cleaned_data.get('phone', '')
            user.profile.save(update_fields=['phone', 'updated_at'])
        return user
