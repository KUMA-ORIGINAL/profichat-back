from account.models import ROLE_DOCTOR, ROLE_ACCOUNTANT


def permission_callback(request):
    if request.user.is_superuser:
        return True
    return False

def permission_callback_for_doctor_and_accountant(request):
    if request.user.is_superuser:
        return True
    if request.user.role in (ROLE_DOCTOR, ROLE_ACCOUNTANT):
        return False
    return True

def permission_callback_for_accountant(request):
    if request.user.role == ROLE_ACCOUNTANT:
        return False
    return True
