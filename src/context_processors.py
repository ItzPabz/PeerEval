from django.conf import settings

def institution_settings(request):
    """
    Adds institution settings to the template context.
    """
    return {
        'INST_NAME': settings.INST_NAME,
        'INST_SHORT_NAME': settings.INST_SHORT_NAME,
        'INST_COLOR': settings.INST_COLOR,
    } 