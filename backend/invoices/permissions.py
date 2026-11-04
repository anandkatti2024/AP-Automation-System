from rest_framework.permissions import BasePermission


AP_ROLES = {
    "AP Clerk",
    "Approver",
    "Payment Clerk",
    "Administrator",
}


class HasInvoiceRole(BasePermission):
    message = "Your account does not have permission to perform this action."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True

        roles = set(
            user.groups.values_list("name", flat=True)
        )
        if "Administrator" in roles:
            return True

        required_roles = getattr(
            view,
            "required_roles_by_method",
            {},
        ).get(request.method)
        if required_roles is None:
            return bool(roles & AP_ROLES)
        return bool(roles & required_roles)
