from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminRole

from . import stats


class SummaryAPIView(APIView):
    """Admin-only dashboard numbers. Money values are strings; `charts` arrays are numeric."""
    permission_classes = [IsAdminRole]

    def get(self, request):
        return Response(stats.jsonable(stats.overview(stats.parse_days(request.query_params.get('days')))))
