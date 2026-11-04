import json

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .permissions import AP_ROLES


def _read_credentials(request, action):
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"detail": "Invalid JSON request."}, status=400)

    if not isinstance(payload, dict):
        return None, JsonResponse({"detail": f"Invalid {action} request."}, status=400)

    username = payload.get("username")
    password = payload.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return None, JsonResponse(
            {"detail": "Username and password are required."},
            status=400,
        )

    username = username.strip()
    if not username:
        return None, JsonResponse(
            {"detail": "Username and password are required."},
            status=400,
        )

    return (username, password), None


def _user_payload(user):
    roles = list(user.groups.values_list("name", flat=True))
    if user.is_superuser and "Administrator" not in roles:
        roles.append("Administrator")
    return {
        "authenticated": True,
        "username": user.get_username(),
        "is_superuser": user.is_superuser,
        "roles": roles,
    }


@csrf_protect
@require_http_methods(["POST"])
def auth_register(request):
    credentials, error_response = _read_credentials(request, "registration")
    if error_response:
        return error_response

    username, password = credentials
    User = get_user_model()
    username_field = User._meta.get_field(User.USERNAME_FIELD)
    try:
        username = username_field.clean(username, None)
    except ValidationError as error:
        return JsonResponse(
            {"detail": "Please enter a valid username.", "errors": {"username": error.messages}},
            status=400,
        )

    if User.objects.filter(**{User.USERNAME_FIELD: username}).exists():
        return JsonResponse(
            {"detail": "That username is already in use. Please choose another."},
            status=400,
        )

    try:
        password_validation.validate_password(password)
    except ValidationError as error:
        return JsonResponse(
            {"detail": "Please choose a stronger password.", "errors": {"password": error.messages}},
            status=400,
        )

    try:
        with transaction.atomic():
            user = User.objects.create_user(**{User.USERNAME_FIELD: username, "password": password})
            user.groups.add(Group.objects.get(name="AP Clerk"))
    except IntegrityError:
        return JsonResponse(
            {"detail": "That username is already in use. Please choose another."},
            status=400,
        )

    login(request, user)
    return JsonResponse(_user_payload(user), status=201)


@csrf_protect
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def auth_session(request):
    if request.method == "GET":
        if request.user.is_authenticated:
            user_roles = set(request.user.groups.values_list("name", flat=True))
            if request.user.is_superuser or user_roles.intersection(AP_ROLES):
                return JsonResponse(_user_payload(request.user))
        return JsonResponse({"authenticated": False})

    credentials, error_response = _read_credentials(request, "login")
    if error_response:
        return error_response
    username, password = credentials

    user = authenticate(
        request,
        username=username.strip(),
        password=password,
    )
    if user is None:
        return JsonResponse(
            {"detail": "The username or password is incorrect."},
            status=401,
        )

    user_roles = set(user.groups.values_list("name", flat=True))
    if not user.is_superuser and not user_roles.intersection(AP_ROLES):
        return JsonResponse(
            {"detail": "Your account has no AP role assigned. Contact an administrator."},
            status=403,
        )

    login(request, user)
    return JsonResponse(_user_payload(user))


@csrf_protect
@require_http_methods(["POST"])
def auth_logout(request):
    logout(request)
    return JsonResponse({"authenticated": False})
