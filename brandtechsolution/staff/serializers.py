from django.contrib.auth.models import Group, Permission
from rest_framework import serializers

from .capabilities import CODENAMES


class RoleSerializer(serializers.ModelSerializer):
    # required=False keeps to_representation() from blowing up: Group has no
    # `capabilities` attribute of its own, so DRF's default get_attribute()
    # would raise AttributeError while rendering. to_representation() below
    # always overwrites this field with the computed value, so this only
    # affects the (never-hit) default-representation path, not input
    # validation for POST/PUT, which still requires the key to be present.
    capabilities = serializers.ListField(
        child=serializers.CharField(), allow_empty=True, required=False
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
        return group

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
