import re

from rest_framework import serializers

from .models import Vendor, VendorOnboardingHistory
from .validation import GSTIN_PATTERN


IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


class VendorSerializer(serializers.ModelSerializer):
    bank_account_number = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        max_length=64,
    )
    bank_account_last4 = serializers.CharField(read_only=True)
    onboarding_history = serializers.SerializerMethodField()

    class Meta:
        model = Vendor
        fields = [
            "id",
            "name",
            "gstin",
            "tax_id",
            "contact_email",
            "contact_phone",
            "address",
            "bank_account_name",
            "bank_account_number",
            "bank_account_last4",
            "bank_ifsc",
            "onboarding_status",
            "onboarding_history",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "onboarding_status",
            "onboarding_history",
            "created_at",
            "updated_at",
        ]

    def get_onboarding_history(self, vendor):
        return VendorOnboardingHistorySerializer(
            vendor.onboarding_history.all(),
            many=True,
        ).data

    def validate_gstin(self, value):
        value = value.strip().upper()
        if not value:
            return value

        if not GSTIN_PATTERN.fullmatch(value):
            raise serializers.ValidationError(
                "Enter a valid 15-character Indian GSTIN format."
            )

        existing = Vendor.objects.filter(gstin__iexact=value)
        if self.instance:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(
                "A vendor with this GSTIN already exists."
            )

        return value

    def validate_bank_ifsc(self, value):
        value = value.strip().upper()
        if value and not IFSC_PATTERN.fullmatch(value):
            raise serializers.ValidationError(
                "Enter a valid 11-character IFSC code."
            )
        return value

    def validate(self, attrs):
        if (
            self.instance
            and self.instance.onboarding_status == "UNDER_REVIEW"
            and attrs
        ):
            raise serializers.ValidationError(
                "Vendor details cannot be changed while onboarding review is in progress."
            )

        account_number = attrs.get(
            "bank_account_number",
            self.instance.bank_account_number if self.instance else "",
        )
        ifsc = attrs.get(
            "bank_ifsc",
            self.instance.bank_ifsc if self.instance else "",
        )

        if bool(account_number) != bool(ifsc):
            raise serializers.ValidationError({
                "bank_details": (
                    "Provide both a bank account number and IFSC code, "
                    "or leave both blank."
                )
            })

        return attrs


class VendorOnboardingHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = VendorOnboardingHistory
        fields = ["id", "action", "comment", "actor_name", "created_at"]
        read_only_fields = fields
