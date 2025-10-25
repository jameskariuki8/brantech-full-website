from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

def check_api_call(view_func):
    @csrf_exempt
    @require_http_methods(["POST"])
    def wrapper(request: HttpRequest, *args, **kwargs):
        if not request.get_host().endswith("bigaddict.shop"):
            return JsonResponse({"error": "Unauthorized"}, status=401)
        return view_func(request, *args, **kwargs)
    return wrapper