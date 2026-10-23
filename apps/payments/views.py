from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from apps.bookings.models import Booking

from . import services
from .forms import PayForm


@login_required
def pay(request, reference):
    booking = get_object_or_404(Booking.objects.select_related('payment', 'slot__location'),
                                reference=reference, user=request.user)
    payment = getattr(booking, 'payment', None)
    if payment is None:
        messages.error(request, 'No payment record exists for this booking.')
        return redirect(booking)
    if not payment.can_pay or booking.status in ('cancelled', 'no_show'):
        messages.info(request, 'There is nothing to pay for this booking.')
        return redirect(booking)
    form = PayForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            result = services.pay(payment, form.cleaned_data['method'], form.cleaned_data['outcome'])
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
            return redirect(booking)
        if result.status == 'paid':
            messages.success(request, f'Simulated payment received. Transaction {result.transaction_id}.')
            return redirect(booking)
        messages.error(request, 'The simulated payment failed. You can try again.')
        return redirect('payments:pay', reference=booking.reference)
    return render(request, 'payments/pay.html', {'booking': booking, 'payment': payment, 'form': form})
