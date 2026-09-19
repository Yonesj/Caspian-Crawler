from rest_framework import serializers

from core.listings.enums import PropertyType, TransactionType
from core.locations.models import City, Province, Region
from core.sources.enums import Source
from core.sources.errors import SourceError

from .models import CrawlJob, CrawlJobEvent, create_job, queue_job


class CrawlScopeInputSerializer(serializers.Serializer):
    province_id = serializers.PrimaryKeyRelatedField(
        source='province',
        queryset=Province.objects.filter(is_active=True),
        required=False,
    )
    city_id = serializers.PrimaryKeyRelatedField(
        source='city', queryset=City.objects.filter(is_active=True), required=False
    )
    region_id = serializers.PrimaryKeyRelatedField(
        source='region', queryset=Region.objects.filter(is_active=True), required=False
    )

    def validate(self, attrs):
        if len(attrs) != 1:
            raise serializers.ValidationError(
                'Select exactly one province_id, city_id, or region_id.'
            )
        return attrs


class CrawlJobEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = CrawlJobEvent
        fields = (
            'id',
            'from_status',
            'to_status',
            'level',
            'reason',
            'message',
            'context',
            'created_at',
        )


class CrawlScopeSerializer(serializers.Serializer):
    level = serializers.ChoiceField(
        choices=('province', 'city', 'region'), read_only=True
    )
    id = serializers.IntegerField(read_only=True)
    code = serializers.CharField(read_only=True)
    name_fa = serializers.CharField(read_only=True)
    name_en = serializers.CharField(read_only=True)

    def to_representation(self, instance):
        for level in ('region', 'city', 'province'):
            target = getattr(instance, level)
            if target is not None:
                return {
                    'level': level,
                    'id': target.pk,
                    'code': target.code,
                    'name_fa': target.name_fa,
                    'name_en': target.name_en,
                }
        return None


class PublicReportField(serializers.JSONField):
    """Expose outcome details without source-internal routing snapshots."""

    _INTERNAL_KEYS = frozenset({'source_external_id', 'source_category'})

    def to_representation(self, value):
        public = {
            key: item for key, item in (value or {}).items()
            if key not in self._INTERNAL_KEYS
        }
        return super().to_representation(public)


class CrawlJobSerializer(serializers.ModelSerializer):
    requested_by = serializers.CharField(
        source='requested_by.get_username', allow_null=True, read_only=True
    )
    scope = CrawlScopeSerializer(source='*', read_only=True)
    events = CrawlJobEventSerializer(many=True, read_only=True)
    report = PublicReportField(read_only=True)

    class Meta:
        model = CrawlJob
        fields = (
            'id',
            'source',
            'scope',
            'transaction_type',
            'property_type',
            'page_limit',
            'status',
            'requested_by',
            'pages_fetched',
            'stubs_seen',
            'details_fetched',
            'listings_created',
            'listings_updated',
            'listings_skipped',
            'listings_out_of_scope',
            'errors',
            'error',
            'report',
            'created_at',
            'updated_at',
            'queued_at',
            'started_at',
            'finished_at',
            'events',
        )

class CrawlJobListSerializer(CrawlJobSerializer):
    class Meta(CrawlJobSerializer.Meta):
        fields = CrawlJobSerializer.Meta.fields[:-1]


class CrawlJobCreateSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=Source.choices)
    transaction_type = serializers.ChoiceField(
        choices=TransactionType.choices, default=TransactionType.UNSPECIFIED
    )
    property_type = serializers.ChoiceField(
        choices=PropertyType.choices, default=PropertyType.OTHER
    )
    page_limit = serializers.IntegerField(
        min_value=1, max_value=32767, required=False, allow_null=True
    )
    scope = CrawlScopeInputSerializer()

    def create(self, validated_data):
        scope = validated_data.pop('scope')
        try:
            job = create_job(
                **validated_data,
                **scope,
                requested_by=self.context['request'].user,
            )
        except SourceError as exc:
            raise serializers.ValidationError({'scope': str(exc)}) from exc
        queue_job(job)
        return job

    def to_representation(self, instance):
        return CrawlJobSerializer(instance, context=self.context).data


class CrawlOptionsSerializer(serializers.Serializer):
    sources = serializers.ListField(child=serializers.DictField())
    transaction_types = serializers.ListField(child=serializers.DictField())
    property_types = serializers.ListField(child=serializers.DictField())
