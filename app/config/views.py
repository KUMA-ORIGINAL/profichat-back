from django.http import HttpResponse


def health_check(request):
    return HttpResponse('OK', status=200)

def trigger_error(request):
    division_by_zero = 1 / 0