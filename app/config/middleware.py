from django.utils import translation
from django.conf import settings


class LanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = request.META.get('HTTP_ACCEPT_LANGUAGE')

        if lang and lang in dict(settings.LANGUAGES):
            translation.activate(lang)
        else:
            translation.activate(settings.LANGUAGE_CODE)
        response = self.get_response(request)

        return response