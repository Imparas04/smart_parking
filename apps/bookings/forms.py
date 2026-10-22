from django import forms

from .models import Vehicle, normalize_plate, plate_validator

DT_FORMATS = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M']


def _dt_field():
    return forms.DateTimeField(
        input_formats=DT_FORMATS,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'))


class BookingForm(forms.Form):
    start_time = _dt_field()
    end_time = _dt_field()
    vehicle = forms.ModelChoiceField(queryset=Vehicle.objects.none(), required=False,
                                     empty_label='New vehicle (fill in below)', label='Saved vehicle')
    plate_number = forms.CharField(max_length=20, required=False, label='New vehicle plate number')
    vehicle_type = forms.ChoiceField(choices=Vehicle.TYPE_CHOICES, required=False, initial='car',
                                     label='New vehicle type')

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vehicle'].queryset = Vehicle.objects.filter(user=user)

    def clean_plate_number(self):
        plate = normalize_plate(self.cleaned_data.get('plate_number'))
        if plate:
            plate_validator(plate)
        return plate

    def clean(self):
        data = super().clean()
        if not data.get('vehicle') and not data.get('plate_number') and 'plate_number' not in self.errors:
            raise forms.ValidationError('Select a saved vehicle or enter a plate number.')
        return data
