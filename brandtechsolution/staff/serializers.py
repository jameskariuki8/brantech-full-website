from django.contrib.auth.models import Group, Permission
from django.db.models import Count
from rest_framework import serializers

from .capabilities import CODENAMES


class RoleSerializer(serializers.ModelSerializer):
    # write_only=True keeps to_representation() from blowing up: Group has no
    # `capabilities` attribute of its own, so DRF's default get_attribute()
    # would raise AttributeError while rendering. A write-only field is
    # excluded from _readable_fields, so get_attribute() is never called on
    # read - to_representation() below always overwrites this field with the
    # computed value anyway, so the field is never missing from the response.
    # On write the field stays mandatory: a non-partial request (POST/PUT)
    # missing the key correctly fails validation with a 400, while PATCH
    # still skips it as partial-update semantics require.
    capabilities = serializers.ListField(
        child=serializers.CharField(), allow_empty=True, write_only=True
    )
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Group
        fields = ["id", "name", "capabilities", "member_count"]

    def validate_capabilities(self, value):
        unknown = sorted(set(value) - set(CODENAMES))
        if unknown:
            raise serializers.ValidationError(
                f"Unknown capabilities: {', '.join(unknown)}"
            )
        return value

    def _apply(self, group, codenames):
        group.permissions.set(
            Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )

    def create(self, validated_data):
        codenames = validated_data.pop("capabilities")
        group = Group.objects.create(**validated_data)
        self._apply(group, codenames)
        # Group.objects.create() bypasses the view's annotated queryset
        # (Count("user") -> member_count), so re-fetch through it to keep
        # the create response shape consistent with list/retrieve/update.
        return Group.objects.annotate(member_count=Count("user")).get(pk=group.pk)

    def update(self, instance, validated_data):
        codenames = validated_data.pop("capabilities", None)
        instance.name = validated_data.get("name", instance.name)
        instance.save()
        if codenames is not None:
            self._apply(instance, codenames)
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["capabilities"] = sorted(
            instance.permissions.filter(
                content_type__app_label="staff"
            ).values_list("codename", flat=True)
        )
        return data
