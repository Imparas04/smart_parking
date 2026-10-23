from django import forms

from .models import Payment


class PayForm(forms.Form):
    method = forms.ChoiceField(choices=Payment.METHOD_CHOICES, label='Payment method (simulated)')
    outcome = forms.ChoiceField(
        choices=[('success', 'Payment succeeds'), ('fail', 'Payment fails (for testing)')],
        initial='success', label='Simulated result')
