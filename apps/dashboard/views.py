from django.shortcuts import render

from apps.accounts.decorators import admin_required


@admin_required
def index(request):
    return render(request, 'dashboard/index.html')
