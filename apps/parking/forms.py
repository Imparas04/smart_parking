from django import forms

from .models import ParkingLocation, ParkingSlot


class LocationForm(forms.ModelForm):
    opening_time = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'))
    closing_time = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'))

    class Meta:
        model = ParkingLocation
        fields = ['name', 'address', 'city', 'description', 'opening_time', 'closing_time', 'hourly_rate', 'is_active']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def clean(self):
        data = super().clean()
        name, city = data.get('name'), data.get('city')
        if name and city:
            qs = ParkingLocation.objects.filter(name__iexact=name.strip(), city__iexact=city.strip())
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('A location with this name already exists in this city.')
        return data


class SlotForm(forms.ModelForm):
    class Meta:
        model = ParkingSlot
        fields = ['slot_number', 'slot_type', 'status', 'notes']

    def __init__(self, *args, location=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.location = location or self.instance.location

    def clean_slot_number(self):
        number = self.cleaned_data['slot_number'].strip().upper()
        qs = ParkingSlot.objects.filter(location=self.location, slot_number=number)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('This slot number already exists at this location.')
        return number


class BulkSlotForm(forms.Form):
    prefix = forms.CharField(max_length=10, required=False, help_text='e.g. A- gives A-1, A-2, ...')
    start = forms.IntegerField(min_value=1, initial=1)
    count = forms.IntegerField(min_value=1, max_value=200)
    slot_type = forms.ChoiceField(choices=ParkingSlot.TYPE_CHOICES, initial='car')

    def __init__(self, *args, location, **kwargs):
        super().__init__(*args, **kwargs)
        self.location = location

    def numbers(self):
        d = self.cleaned_data
        prefix = d['prefix'].strip().upper()
        return [f"{prefix}{n}" for n in range(d['start'], d['start'] + d['count'])]

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        if any(len(n) > 20 for n in self.numbers()):
            raise forms.ValidationError('Generated slot numbers are too long; use a shorter prefix.')
        existing = set(ParkingSlot.objects.filter(location=self.location, slot_number__in=self.numbers())
                       .values_list('slot_number', flat=True))
        if existing:
            raise forms.ValidationError('These slot numbers already exist: ' + ', '.join(sorted(existing)[:10]))
        return data

    def save(self):
        slots = [ParkingSlot(location=self.location, slot_number=n, slot_type=self.cleaned_data['slot_type'])
                 for n in self.numbers()]
        return ParkingSlot.objects.bulk_create(slots)
